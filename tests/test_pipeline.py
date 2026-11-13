from maude_rag.ask import build_prompt
from maude_rag.index import chunk
from maude_rag.ingest import slim


def test_short_text_is_one_chunk():
    assert chunk("pump alarm sounded", size=5, overlap=2) == ["pump alarm sounded"]


def test_chunks_overlap_and_cover_every_word():
    words = [str(n) for n in range(12)]
    pieces = chunk(" ".join(words), size=5, overlap=2)
    assert pieces[0].split() == words[:5]
    assert pieces[1].split()[:2] == words[3:5]  # shares the overlap
    assert pieces[-1].split()[-1] == words[-1]
    assert all(len(p.split()) <= 5 for p in pieces)


def test_slim_keeps_reporter_narrative_only():
    report = {
        "report_number": "R1",
        "mdr_text": [
            {"text_type_code": "Description of Event or Problem", "text": "Pump stopped."},
            {"text_type_code": "Additional Manufacturer Narrative", "text": "Boilerplate."},
        ],
        "device": [{"brand_name": "ACME"}],
    }
    slimmed = slim(report)
    assert slimmed["narrative"] == "Pump stopped."
    assert slimmed["brand_name"] == "ACME"


def test_slim_drops_reports_without_a_narrative():
    assert slim({"report_number": "R2", "mdr_text": []}) is None


def test_prompt_carries_report_number_and_question():
    hit = {"report_number": "R1", "date_received": "20250101", "brand_name": "ACME",
           "event_type": "Malfunction", "text": "Pump stopped."}
    prompt = build_prompt("Why did it stop?", [hit])
    assert 'number="R1"' in prompt and prompt.endswith("Question: Why did it stop?")


# Step 2: filters and keyword search

from maude_rag.ask import where_clause
from maude_rag.keyword import bm25, rrf


def test_no_filters_means_no_where_clause():
    assert where_clause() is None


def test_single_filter_is_not_wrapped():
    assert where_clause(brands=["MINIMED 780G"]) == {"brand_name": {"$in": ["MINIMED 780G"]}}


def test_several_filters_are_anded_with_a_date_range():
    clause = where_clause(event_type="Death", since=20250601, until=20250630)
    assert clause == {"$and": [
        {"event_type": "DEATH"},
        {"date_received": {"$gte": 20250601}},
        {"date_received": {"$lte": 20250630}},
    ]}


def test_bm25_ranks_the_doc_with_the_rare_word_first():
    docs = ["pump alarm sounded", "pump occlusion alarm", "pump battery died"]
    scores = bm25("occlusion alarm", docs)
    assert max(range(3), key=scores.__getitem__) == 1
    assert scores[2] == 0  # shares no query words


def test_bm25_handles_an_empty_pool():
    assert bm25("anything", []) == []


def test_rrf_rewards_items_found_by_both_lists():
    assert rrf(["a", "b", "c"], ["c", "d"])[0] == "c"


def test_month_is_spread_across_days_and_tops_up_short_days(monkeypatch):
    from maude_rag import ingest

    def fake_day(year, month, day, wanted):
        if day % 7 in (0, 6):  # pretend weekends have no reports
            return []
        return [{"day": day}] * wanted

    monkeypatch.setattr(ingest, "fetch_day", fake_day)
    reports = ingest.fetch_month(2025, 6, 250)
    days = {r["day"] for r in reports}
    assert len(reports) == 250
    assert min(days) == 1 and max(days) >= 28  # not just the first few days


# Evaluation scoring

from maude_rag.evaluate import correct_reports, passes, score


def test_score_counts_hit_precision_and_rank():
    s = score(["A", "B", "C", "D"], correct={"C", "D"}, judged={"A", "B", "C", "D"})
    assert s == {"hit": True, "precision": 0.5, "reciprocal_rank": 1 / 3, "unjudged": 0}


def test_score_with_nothing_correct():
    s = score(["A", "B"], correct={"Z"})
    assert s["hit"] is False and s["precision"] == 0 and s["reciprocal_rank"] == 0


def test_score_flags_reports_nobody_has_read():
    assert score(["A", "NEW"], correct={"A"}, judged={"A"})["unjudged"] == 1


def test_filters_match_like_the_command_line():
    report = {"event_type": "Death", "brand_name": "MINIMED 780G US", "manufacturer": "MEDTRONIC",
              "date_received": "20250615"}
    assert passes(report, {"event_type": "DEATH", "brand": "780g", "since": 20250601, "until": 20250630})
    assert not passes(report, {"until": 20250531})
    assert not passes(report, {"manufacturer": "tandem"})


def test_pattern_questions_check_every_report_that_passes_the_filters():
    reports = [
        {"report_number": "R1", "narrative": "Pump error 35.", "event_type": "Malfunction",
         "brand_name": "X", "manufacturer": "M", "date_received": "20250101"},
        {"report_number": "R2", "narrative": "Pump error 350.", "event_type": "Malfunction",
         "brand_name": "X", "manufacturer": "M", "date_received": "20250101"},
    ]
    question = {"judged_by": "pattern", "pattern": r"ERROR\s*35\b", "filters": {}}
    assert correct_reports(question, reports) == ({"R1"}, None)


def test_pattern_questions_can_exclude_false_matches():
    reports = [{"report_number": "R1", "narrative": "No occlusion was found.", "event_type": "Malfunction",
                "brand_name": "X", "manufacturer": "M", "date_received": "20250101"}]
    question = {"judged_by": "pattern", "pattern": "OCCLUSION", "filters": {}, "exclude": ["R1"]}
    assert correct_reports(question, reports) == (set(), None)

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

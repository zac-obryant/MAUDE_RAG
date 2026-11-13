# `tests/test_pipeline.py` and `tests/test_steps_3_to_5.py`

## Purpose

These files check that the small building blocks of the pipeline behave as intended. Each test feeds a function a tiny made-up input and confirms the output is what it should be.

Tests exist so that a later change which accidentally breaks something is caught straight away. Run them with:

```bash
python -m pytest
```

They finish in a few seconds, need no internet connection and no API key, and do not touch the real data.

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `pytest` | Installed package | Finds every function whose name starts with `test_`, runs it, and reports passes and failures |
| `chunk` from `index.py` | This project | The function under test |
| `slim` from `ingest.py` | This project | The function under test |
| `build_prompt` from `ask.py` | This project | The function under test |
| Functions from `sql.py`, `router.py`, `agent.py`, `llm.py`, `evaluate_llm.py` | This project | Tested in `tests/test_steps_3_to_5.py` (section 9) |

Every test relies on `assert`, which means "this must be true". If it is not, the test fails and pytest shows what went wrong.

## Step by step with code snippets

### 1. Short text stays in one piece

```python
def test_short_text_is_one_chunk():
    assert chunk("pump alarm sounded", size=5, overlap=2) == ["pump alarm sounded"]
```

**In plain steps**

```
test: short text is one chunk
    chunk the text "pump alarm sounded", allowing 5 words per chunk
    the result must be a list holding that one text, unchanged
```

**Key elements**

| Code | What it means |
|---|---|
| `def test_...():` | Define a test. pytest runs every function whose name begins with `test_`; the rest of the name describes what is being checked |
| `assert` | "This must be true." If it is not, the test fails |
| `chunk("pump alarm sounded", size=5, overlap=2)` | Run the `chunk` function on a three-word text, with small settings chosen to make the test easy to follow |
| `==` | "Is equal to" |
| `["pump alarm sounded"]` | The expected answer: a list containing one text |

**Explanation**

A three-word text with a five-word limit should come back unchanged as a single chunk. This protects the most common case, since most narratives are shorter than the limit.

### 2. Long text is split with overlap and nothing is lost

```python
def test_chunks_overlap_and_cover_every_word():
    words = [str(n) for n in range(12)]
    pieces = chunk(" ".join(words), size=5, overlap=2)
    assert pieces[0].split() == words[:5]
    assert pieces[1].split()[:2] == words[3:5]  # shares the overlap
    assert pieces[-1].split()[-1] == words[-1]
    assert all(len(p.split()) <= 5 for p in pieces)
```

**In plain steps**

```
test: chunks overlap and cover every word
    words  = the twelve "words" 0, 1, 2, ... 11
    pieces = chunk them, with 5 words per chunk and 2 words of overlap

    the first chunk must be exactly words 0 to 4
    the first two words of the second chunk must be words 3 and 4
    the last word of the last chunk must be the last word, 11
    every chunk must have 5 words or fewer
```

With these settings the chunks come out as `0 1 2 3 4`, `3 4 5 6 7`, `6 7 8 9 10` and `9 10 11`.

**Key elements**

| Code | What it means |
|---|---|
| `range(12)` | The numbers 0 to 11 |
| `str(n)` | Turn a number into text, so `7` becomes `"7"`. The chunk function works on text |
| `[str(n) for n in range(12)]` | Build a list by doing that for each number |
| `" ".join(words)` | Glue them into one text: `"0 1 2 ... 11"` |
| `pieces[0]` | The first chunk |
| `pieces[1]` | The second chunk |
| `pieces[-1]` | The last chunk. A negative position counts from the end |
| `.split()` | Cut a chunk back into its separate words so they can be compared |
| `words[:5]` | The first five words (positions 0 to 4) |
| `words[3:5]` | The words at positions 3 and 4 |
| `[:2]` | The first two items |
| `all(... for p in pieces)` | "Is this true for every chunk?" |
| `len(p.split()) <= 5` | "Does this chunk have five words or fewer?" |

**Explanation**

The "text" is the numbers 0 to 11, which makes it easy to see where each chunk starts and ends. The four checks confirm that:

1. the first chunk is the first five words;
2. the second chunk starts with the last two words of the first (the overlap);
3. the final chunk ends with the final word, so the end of the text is not dropped;
4. no chunk is longer than the limit.

### 3. Only the reporter's narrative is kept

```python
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
```

**In plain steps**

```
test: slim keeps the reporter's narrative only
    report = a made-up report with:
        report number "R1"
        two text blocks:
            the reporter's description, saying "Pump stopped."
            the manufacturer's narrative, saying "Boilerplate."
        one device with the brand name "ACME"

    slimmed = run slim on that report

    its narrative must be exactly "Pump stopped."
    its brand name must be "ACME"
```

**Key elements**

| Code | What it means |
|---|---|
| `report = { ... }` | A made-up report, built by hand in the same shape the FDA uses |
| `"mdr_text": [ ... ]` | The field holding the report's text blocks, as a list |
| `{"text_type_code": ..., "text": ...}` | One text block: its label and its words |
| `"device": [{"brand_name": "ACME"}]` | A list holding one device record |
| `slim(report)` | Run the function being tested |
| `slimmed["narrative"]` | Look up the narrative field in the result |

**Explanation**

A made-up report with both kinds of text block goes in. The test confirms that the reporter's description is kept, the manufacturer's block is left out, and the brand name is picked up from the device section.

### 4. Reports with no narrative are skipped

```python
def test_slim_drops_reports_without_a_narrative():
    assert slim({"report_number": "R2", "mdr_text": []}) is None
```

**In plain steps**

```
test: slim drops reports without a narrative
    run slim on a made-up report that has no text blocks
    the result must be "nothing"
```

**Key elements**

| Code | What it means |
|---|---|
| `"mdr_text": []` | An empty list: this report has no text blocks at all |
| `is None` | "Is exactly nothing". For checking against `None`, Python uses `is` instead of `==` |

**Explanation**

A report with no text should return `None`, the signal to leave it out. Without this, empty entries would end up in the database.

### 5. The prompt contains the citation and the question

```python
def test_prompt_carries_report_number_and_question():
    hit = {"report_number": "R1", "date_received": "20250101", "brand_name": "ACME",
           "event_type": "Malfunction", "text": "Pump stopped."}
    prompt = build_prompt("Why did it stop?", [hit])
    assert 'number="R1"' in prompt and prompt.endswith("Question: Why did it stop?")
```

**In plain steps**

```
test: the prompt carries the report number and the question
    hit    = a made-up search result for report "R1"
    prompt = build a prompt from the question "Why did it stop?" and that one result

    the prompt must contain the text  number="R1"
    and the prompt must end with      Question: Why did it stop?
```

**Key elements**

| Code | What it means |
|---|---|
| `hit = { ... }` | A made-up search result, in the same shape `retrieve` produces |
| `[hit]` | A list holding that single result, because `build_prompt` expects a list |
| `'number="R1"'` | The text to look for. Single quotes on the outside allow double quotes inside |
| `in prompt` | "Appears somewhere in the prompt" |
| `and` | Both checks must be true |
| `prompt.endswith("...")` | "Does the prompt finish with exactly this text?" |

**Explanation**

This confirms that the report number appears in the prompt, since the model cannot cite a number it was never shown, and that the question comes at the end.

### 6. Step 2: filters and keyword search

```python
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
    assert scores[2] == 0

def test_bm25_handles_an_empty_pool():
    assert bm25("anything", []) == []

def test_rrf_rewards_items_found_by_both_lists():
    assert rrf(["a", "b", "c"], ["c", "d"])[0] == "c"
```

**In plain steps**

```
test: with no filters, there is no database condition at all
test: one filter is handed back on its own, not wrapped in "all of these"
test: several filters are wrapped in "all of these", and the event type is put in capitals

test: of three made-up chunks, the one containing "occlusion" ranks first,
      and the one sharing no words with the question scores 0
test: scoring an empty pool gives an empty list instead of crashing

test: when "c" is in both lists, it comes out on top after merging,
      even though "a" was first in one list
```

**Key elements**

| Code | What it means |
|---|---|
| `is None` | "Is this nothing?" |
| `max(range(3), key=scores.__getitem__)` | The position (0, 1 or 2) with the highest score |
| `[0]` after `rrf(...)` | The first item of the merged list |

**Explanation**

These pin down the rules from [ask.md](ask.md) step 3 and [keyword.md](keyword.md). The BM25 test shows the key idea in miniature: "pump" and "alarm" are common, "occlusion" is rare, so the chunk with "occlusion" wins.

### 7. A month's download covers the whole month

```python
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
    assert min(days) == 1 and max(days) >= 28
```

**In plain steps**

```
test: a month's download covers the whole month
    replace the real one-day download with a fake one that:
        returns nothing on some days (pretend weekends)
        returns exactly as many made-up reports as asked for on the others

    reports = collect June 2025, asking for 250
    days    = the days those reports came from

    there must be exactly 250 reports
    they must start on day 1 and reach at least day 28
```

**Key elements**

| Code | What it means |
|---|---|
| `monkeypatch` | A pytest tool that swaps a function for a stand-in during one test, then puts the original back |
| `monkeypatch.setattr(ingest, "fetch_day", fake_day)` | "While this test runs, `fetch_day` means `fake_day`", so no request goes to the FDA |
| `day % 7 in (0, 6)` | `%` gives the remainder after dividing. This picks two days in every seven |
| `[{"day": day}] * wanted` | A list of `wanted` copies of a tiny made-up report that records its day |
| `{r["day"] for r in reports}` | The set of distinct days, with repeats removed |

**Explanation**

This guards the fix described in [ingest.md](ingest.md) step 4. It checks both halves: the sample reaches late in the month instead of stopping after a day or two, and days with no reports do not leave the month short of 250.

### 8. Evaluation scoring

```python
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
    reports = [ ...report R1 says "Pump error 35.", report R2 says "Pump error 350."... ]
    question = {"judged_by": "pattern", "pattern": r"ERROR\s*35\b", "filters": {}}
    assert correct_reports(question, reports) == ({"R1"}, None)

def test_pattern_questions_can_exclude_false_matches():
    reports = [ ...report R1 says "No occlusion was found."... ]
    question = {"judged_by": "pattern", "pattern": "OCCLUSION", "filters": {}, "exclude": ["R1"]}
    assert correct_reports(question, reports) == (set(), None)
```

**In plain steps**

```
test: four reports retrieved, the 3rd and 4th correct
      -> a hit, half are correct, first correct at position 3 so reciprocal rank 1/3
test: nothing correct retrieved -> no hit, all scores zero
test: a retrieved report nobody has read is counted as unjudged

test: a June death report for a 780G brand passes matching filters,
      fails an end date in May, and fails a Tandem manufacturer filter

test: the pattern "error 35" matches "error 35" but not "error 350"
test: a report that matches the pattern but is on the exclude list does not count
```

**Key elements**

| Code | What it means |
|---|---|
| `{"C", "D"}` | A set of report numbers |
| `1 / 3` | One third, written as a division |
| `r"ERROR\s*35\b"` | A pattern: "ERROR", optional spaces, "35", then a word boundary, so "350" does not match |

**Explanation**

These pin down the arithmetic in [evaluate.md](evaluate.md) steps 1 to 3, so a scoring mistake cannot quietly change the results. The last test guards against a classic pattern bug: without `\b`, "error 35" would also match "error 350".

### 9. Steps 3 to 5 (`tests/test_steps_3_to_5.py`)

These tests cover the SQL path, the router, the agent's recall lookup and the shared LLM helper, without calling Claude or the internet. Where code would call Claude, the test swaps in a stand-in that returns a fixed reply.

```python
@pytest.mark.parametrize("sql", [
    "DELETE FROM reports",
    "WITH x AS (SELECT 1) DELETE FROM reports",
    "SELECT 1; DROP TABLE reports",
])
def test_queries_cannot_change_the_database(db, sql):
    with pytest.raises((ValueError, sqlite3.Error)):
        run_sql(sql, db)
    assert run_sql("SELECT COUNT(*) FROM reports", db)["rows"] == [(2,)]
```

**In plain steps**

```
build a tiny database with two made-up reports              (the "db" fixture)

test: the database stores the month and puts names in capitals
test: a problem listed twice for one report is stored once
test: three attempts to change the database all fail,      (the example above)
      and both reports are still there afterwards
test: a result longer than the row limit is cut off and marked as cut off
test: query results count as the same despite row order, capitals, 3 vs 3.0,
      or an extra label column, but not with a different number or an extra row
test: the recall address covers all four insulin pump codes, the firm, and newest-first order
test: the router drops filters the question did not state
test: a JSON reply from the LLM is turned into a record
test: a declined request raises an error instead of returning an empty answer
```

**Key elements**

| Code | What it means |
|---|---|
| `@pytest.fixture` | A helper that prepares something several tests need, here a fresh tiny database |
| `tmp_path` | A temporary folder pytest provides and cleans up, so tests never touch `data/` |
| `@pytest.mark.parametrize("sql", [...])` | Run the same test once for each value in the list |
| `pytest.raises((ValueError, sqlite3.Error))` | "The indented line must fail with one of these errors" |
| `monkeypatch.setattr(...)` | Swap a setting or function for a stand-in during one test only |
| `SimpleNamespace(...)` | A quick made-up object with named fields, used to imitate a reply from Claude |

**Explanation**

The most important test here is the one shown. In step 3 the LLM writes the SQL, so the query cannot be trusted. Three independent guards protect the data: only queries starting with `SELECT` or `WITH` are accepted, the database is opened read-only, and SQLite refuses two statements in one go. The test tries a plain delete, a delete disguised behind `WITH`, and a delete hidden after a harmless query, and checks the data is unchanged each time.

## What is not tested

These tests cover the pieces that are pure logic. They do not call the FDA, the embedding model, the real database or the LLM (nor the `matching` helper, which reads the downloaded reports), so they say nothing about whether search results or answers are any good. Answer quality is measured separately by `evaluate.py` and `evaluate_llm.py`. Measuring that needs a set of test questions with known good answers, which is a later step.

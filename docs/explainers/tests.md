# `tests/test_pipeline.py`

## Purpose

This file checks that the small building blocks of the pipeline behave as intended. Each test feeds a function a tiny made-up input and confirms the output is what it should be.

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

## What is not tested

These tests cover the pieces that are pure logic. They do not call the FDA, the embedding model, the database or the LLM, so they say nothing about whether search results or answers are any good. Measuring that needs a set of test questions with known good answers, which is a later step.

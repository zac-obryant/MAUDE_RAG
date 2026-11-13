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

A made-up report with both kinds of text block goes in. The test confirms that the reporter's description is kept, the manufacturer's block is left out, and the brand name is picked up from the device section.

### 4. Reports with no narrative are skipped

```python
def test_slim_drops_reports_without_a_narrative():
    assert slim({"report_number": "R2", "mdr_text": []}) is None
```

A report with no text should return `None`, the signal to leave it out. Without this, empty entries would end up in the database.

### 5. The prompt contains the citation and the question

```python
def test_prompt_carries_report_number_and_question():
    hit = {"report_number": "R1", "date_received": "20250101", "brand_name": "ACME",
           "event_type": "Malfunction", "text": "Pump stopped."}
    prompt = build_prompt("Why did it stop?", [hit])
    assert 'number="R1"' in prompt and prompt.endswith("Question: Why did it stop?")
```

This confirms that the report number appears in the prompt, since the model cannot cite a number it was never shown, and that the question comes at the end.

## What is not tested

These tests cover the pieces that are pure logic. They do not call the FDA, the embedding model, the database or the LLM, so they say nothing about whether search results or answers are any good. Measuring that needs a set of test questions with known good answers, which is a later step.

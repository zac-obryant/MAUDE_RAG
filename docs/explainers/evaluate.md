# `maude_rag/evaluate.py`

## Purpose

This file measures how well the search finds the right reports. It asks a fixed set of questions, checks which retrieved reports are correct, and prints a score for each search method.

It completes step 1 of the roadmap, which calls for a baseline measured on a small test set, and gives every later step something to beat. It scores retrieval only, not the written answer, so no API key is needed.

```bash
python -m maude_rag.evaluate                  # score all three search methods
python -m maude_rag.evaluate --mode vector -v # one method, with a row per question
```

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `argparse` | Built into Python | Reads the options from the command line |
| `json` | Built into Python | Reads the question file and the downloaded reports |
| `re` | Built into Python | Matches text patterns for pattern-judged questions |
| `pathlib.Path` | Built into Python | Finds `eval/questions.json` relative to the project |
| `ask.py` | This project | Supplies `retrieve` and `filters_to_where`, so questions are searched exactly as the command line searches them |
| `config.py` | This project | Supplies the report file location and the number of chunks to retrieve |

It needs `data/reports.jsonl` and `data/chroma`, so steps 7.2 and 7.3 of the README must have been run first.

## The test set: `eval/questions.json`

The questions live in a separate file so they can be read, reviewed and changed without touching code. Each question is one record:

| Field | Meaning |
|---|---|
| `id` | A short label, `Q01` to `Q20` |
| `type` | `exact` (asks for a specific term, such as an error code), `paraphrase` (says it in different words from the reports), or `filtered` (uses one or more filters) |
| `question` | The text that is searched |
| `filters` | Filter options, written as the command line would take them, for example `{"manufacturer": "insulet"}` |
| `criterion` | In plain words, what makes a report a correct answer |
| `judged_by` | `pattern` or `reading`; see below |
| `pattern` | For pattern-judged questions: the text pattern a correct report's narrative contains |
| `exclude` | Optional, for pattern-judged questions: reports the pattern matches wrongly, such as one saying "no occlusion" |
| `judged` | For reading-judged questions: every report a person read for this question |
| `relevant` | For reading-judged questions: the ones that met the criterion |
| `reviewed` | `false` until a person has checked the question and its correct reports |

**Two ways of judging.** Some criteria are about wording: "mentions pump error 35" can be checked by a pattern, against every downloaded report. Others are about meaning: "the person passed out from low blood sugar" needs a person to read the report. For those, the candidates were found by *pooling*: running all three search methods, taking each one's top 10 reports, and reading the combined list. Pooling is the standard way to build a test set for search, because it does not favour any one method.

## Step by step with code snippets

### 1. Does a report pass the question's filters? (`passes`)

```python
def passes(report, filters):
    date = int(report["date_received"] or 0)
    return (
        filters.get("event_type", report["event_type"]).upper() == report["event_type"].upper()
        and filters.get("brand", "").upper() in report["brand_name"].upper()
        and filters.get("manufacturer", "").upper() in report["manufacturer"].upper()
        and filters.get("since", date) <= date <= filters.get("until", date)
    )
```

**In plain steps**

```
to check a report against the filters:
    date = the report's date as a number

    the report passes only if all of these hold:
        its event type equals the filter's      (no filter: compare with itself, always true)
        its brand contains the filter's text    (no filter: empty text, always contained)
        its manufacturer contains the filter's text
        its date is on or after "since" and on or before "until"
```

**Key elements**

| Code | What it means |
|---|---|
| `filters.get("brand", "")` | The brand filter if there is one; otherwise empty text |
| `"" in "ANYTHING"` | Empty text is contained in every text, so a missing filter lets everything through |
| `a <= date <= b` | "Is the date between a and b, inclusive?" |
| `and` | Every condition must be true |

**Explanation**

Pattern-judged questions check every downloaded report, so they need the same filters in Python that the database applies during search. The trick of using a default that always passes ("compare with itself", "empty text") avoids a separate `if` for each missing filter.

### 2. Which reports are correct? (`correct_reports`)

```python
def correct_reports(question, reports):
    if question["judged_by"] == "pattern":
        pattern = re.compile(question["pattern"])
        correct = {
            r["report_number"]
            for r in reports
            if passes(r, question["filters"]) and pattern.search(r["narrative"].upper())
        }
        return correct - set(question.get("exclude", [])), None
    return set(question["relevant"]), set(question["judged"])
```

**In plain steps**

```
to find the correct reports for a question:
    if it is judged by pattern:
        correct = every report that passes the filters and whose narrative matches the pattern
        remove any reports listed under "exclude"
        hand back the correct reports, and "nothing to flag as unjudged"
    otherwise (judged by reading):
        hand back the reports a person marked relevant, and the reports they read
```

**Key elements**

| Code | What it means |
|---|---|
| `re.compile(...)` | Prepare the text pattern for searching |
| `pattern.search(text)` | "Does the pattern appear anywhere in this text?" |
| `{ ... for r in reports if ... }` | Build a *set*: a collection with no repeats, here of report numbers |
| `correct - set(...)` | Set subtraction: the correct reports, minus any in the exclude list. `.get("exclude", [])` gives an empty list when there is none |
| `set(question["relevant"])` | Turn the list from the file into a set, which is quick to check against |
| `None` | Every report was checked, so none can be unjudged |

**Explanation**

The function hands back two things. The first is the correct reports. The second is the set of reports a person has read, so the scorer can tell "read and wrong" apart from "never read". For pattern questions every report was checked, so the second is `None`.

### 3. Score one question (`score`)

```python
def score(ranked, correct, judged=None):
    first = next((i for i, r in enumerate(ranked, 1) if r in correct), None)
    found = sum(r in correct for r in ranked)
    return {
        "hit": first is not None,
        "precision": found / len(ranked) if ranked else 0.0,
        "reciprocal_rank": 1 / first if first else 0.0,
        "unjudged": 0 if judged is None else sum(r not in judged for r in ranked),
    }
```

**In plain steps**

```
to score one ranked list of reports:
    first = the position of the first correct report (1, 2, 3...), or none
    found = how many of the retrieved reports are correct

    hit             = was any correct report retrieved?
    precision       = found / number retrieved
    reciprocal rank = 1 / first   (1 if first, 1/2 if second, 1/3 if third... 0 if none)
    unjudged        = how many retrieved reports nobody has read
```

**Key elements**

| Code | What it means |
|---|---|
| `enumerate(ranked, 1)` | Walk the list while counting positions from 1 |
| `next(..., None)` | Take the first item that fits, or `None` if nothing does |
| `sum(r in correct for r in ranked)` | Count the reports that are correct. Each yes counts as 1, each no as 0 |
| `x if condition else y` | `x` when the condition holds, `y` otherwise. Here it avoids dividing by zero |

**Explanation**

Three numbers, each answering a different question:

- **Hit:** did the search find anything useful at all? If not, the LLM has nothing to answer from.
- **Precision:** how much of what was retrieved is useful? Wrong reports in the prompt can mislead the answer.
- **Reciprocal rank:** how high was the first useful report? Higher is better.

There is deliberately no *recall* (the share of all correct reports that were found). Some questions have hundreds of correct reports, and only 8 chunks are retrieved, so recall would always be tiny and say nothing.

### 4. Score one search method on every question (`evaluate`)

```python
def evaluate(mode, questions, reports, k=TOP_K):
    rows = []
    for q in questions:
        hits = retrieve(q["question"], k, filters_to_where(**q["filters"]), mode)
        ranked = list(dict.fromkeys(h["report_number"] for h in hits))
        correct, judged = correct_reports(q, reports)
        rows.append({"id": q["id"], "type": q["type"], "correct_total": len(correct),
                     **score(ranked, correct, judged)})
    return rows
```

**In plain steps**

```
to evaluate a search method:
    for each question:
        turn its filters into a database condition, exactly as the command line would
        retrieve the top 8 chunks with this method
        ranked = their report numbers, in order, each report listed once
        find the correct reports for the question
        record the question's id, type, how many correct reports exist, and its scores
    hand back one record per question
```

**Key elements**

| Code | What it means |
|---|---|
| `filters_to_where(**q["filters"])` | `**` unpacks the filters record into named inputs, so `{"manufacturer": "insulet"}` becomes `manufacturer="insulet"` |
| `dict.fromkeys(...)` | Remove repeats while keeping the order. A long report can have two chunks retrieved; it should only count once |
| `**score(...)` | Copy the four scores into this record |

**Explanation**

Search works on chunks, but correctness is decided per report, so repeated reports are removed first. Because `retrieve` and `filters_to_where` are the same functions the command line uses, the scores describe the real system, not a copy of it.

### 5. Average the scores (`summarise`)

```python
def summarise(rows):
    n = len(rows)
    return {
        "questions": n,
        "hit_rate": sum(r["hit"] for r in rows) / n,
        "precision": sum(r["precision"] for r in rows) / n,
        "mrr": sum(r["reciprocal_rank"] for r in rows) / n,
        "unjudged": sum(r["unjudged"] for r in rows),
    }
```

**In plain steps**

```
to summarise a group of questions:
    hit rate  = the share of questions with a hit
    precision = the average precision
    MRR       = the average reciprocal rank ("mean reciprocal rank")
    unjudged  = the total number of unjudged reports
```

**Explanation**

`main` calls this once per question type and once for all questions, for each method. Splitting by type matters: an average over all 20 questions can hide one method being strong on exact terms and weak on reworded ones.

### 6. Print the tables (`main`)

`main` reads the options, loads the questions and reports, runs `evaluate` for each method, and prints a summary table. With `-v` it adds a table per method with one row per question. The tables are in Markdown, so they can be pasted into a results record or a post. It ends by listing any questions not yet reviewed by a person.

## What to keep in mind

- **The test set was drafted by Claude and has not yet been reviewed by a person.** Every question has `"reviewed": false` until that is done.
- **A good question is one some method can get wrong.** Questions where every candidate is correct, or where a filter leaves fewer reports than are retrieved, give every method the same score. Run 2 of the results replaced six such questions; see `eval/results/2026-11-13-2.md`. Q15 still has this property for hit rate and precision (its filter leaves 8 reports), so only its MRR is informative.
- 20 questions is small. One question is 5 percentage points of hit rate, so small differences between methods are noise.
- Reading-judged questions only know about the reports that were read. If a later step retrieves a report nobody has read, it counts as wrong, and the `Unjudged` column shows it. A non-zero `Unjudged` means more reading is needed before the score can be trusted.
- If the data is downloaded again, pattern-judged questions update automatically; reading-judged ones may refer to reports that no longer exist and need checking.

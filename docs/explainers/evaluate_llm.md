# `maude_rag/evaluate_llm.py`

## Purpose

This file measures the two steps where the LLM makes a decision that can be checked against a known right answer:

- **Counting (step 3):** does the LLM write a SQL query that gives the right numbers? See [sql.md](sql.md).
- **Routing (step 4):** does the router send each question to the right method: search, SQL, or the agent? The router lives in `router.py`.

[evaluate.md](evaluate.md) does the same job for search, which needs no LLM. This file is its counterpart for the LLM steps, so each change to a prompt or model can be scored rather than judged by eye.

Unlike `evaluate.py`, every run calls the LLM. It **needs an Anthropic API key** in `ANTHROPIC_API_KEY`, and **every run costs money**: one LLM call per counting question (12 calls), or one per routing question (41 calls).

```bash
python -m maude_rag.evaluate_llm --suite counting -v   # score the SQL step, a row per question
python -m maude_rag.evaluate_llm --suite routing -v    # score the router, a row per question
python -m maude_rag.evaluate_llm --suite routing       # only the questions it got wrong, plus the summary
```

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `argparse` | Built into Python | Reads `--suite` and `-v` from the command line |
| `json` | Built into Python | Reads the three question files |
| `collections.Counter` | Built into Python | Counts values when comparing rows, and tallies routing decisions |
| `pathlib.Path` | Built into Python | Finds the `eval` folder relative to the project |
| `llm.py` | This project | Supplies `Declined`, so a refusal is scored as wrong instead of stopping the run |
| `sql.py` | This project | Supplies `write_sql` (the LLM writes a query) and `run_sql` (run a query safely) |
| `router.py` | This project | Supplies `route`, the LLM call that picks a method |

It needs the database `data/reports.db` (built by `index.py` or `python -m maude_rag.sql --build`).

## The test files

The questions live in three files in `eval/`, so they can be reviewed without reading code.

**`eval/counting.json`** holds 12 counting questions. Each has:

| Field | Meaning |
|---|---|
| `id` | `C01` to `C12` |
| `question` | The question as a user would type it |
| `reference_sql` | A query written by a person that gives the right answer |
| `note` | Optional: why the reference query is written the way it is. It is for human readers; the code does not use it |

Two questions were reworded so that one answer is clearly right. C09 asks for narratives that "use the word ketoacidosis", so the reference searches for that word alone; an earlier version also counted `DKA`, which a reasonable query could leave out. C11 asks which company has the most injury reports "counting all spellings of its name together". The answer is Medtronic, but a correct query could label it `MEDTRONIC`, `Medtronic Inc` or anything else, so the reference returns only the count, 457. Its `note` explains this, and that grouping by the raw spelling gives 415, which is wrong.

The questions range from simple ("How many death reports are there?") to ones with traps: matching a company under several spellings (C04, C11), counting coded problems without double counting (C05, C08), and joining the two tables (C12).

Running the reference queries against the current database gives these reference answers. They are what the LLM's queries are compared with. They come from the person-written queries, not from the LLM.

| ID | Question (shortened) | Reference answer |
|---|---|---|
| C01 | How many reports in the database? | 2,984 |
| C02 | Reports of each event type | DEATH 8, INJURY 704, MALFUNCTION 2,272 |
| C03 | How many death reports? | 8 |
| C04 | Reports with Beta Bionics as manufacturer | 298 |
| C05 | Five most common device problems | Obstruction of Flow 434, Pumping Stopped 379, Adverse Event Without Identified Device or Use Problem 349, Break 206, Incorrect, Inadequate or Imprecise Result or Readings 198 |
| C06 | Tandem injury reports | 92 |
| C07 | Reports received each month | 250 in every month except August, which has 234 |
| C08 | Reports with 'Battery Problem' | 150 |
| C09 | Narratives using the word ketoacidosis | 56 |
| C10 | Reports per product code | LZG 35, OZO 33, OZP 1,532, QFG 1,384 |
| C11 | Company with most injury reports, all spellings together | 457 (only the count is compared) |
| C12 | Omnipod reports with 'Material Twisted/Bent' | 19 |

**`eval/routing.json`** holds 9 questions chosen to test the router's harder decisions. Each has an `id` (`R01` to `R09`), the `question`, and the `expected` route: `"search"`, `"sql"` or `"agent"`. Five expect `agent`: questions about recalls, or ones that combine a count with examples. Two are counting questions phrased less obviously ("What percentage...", "Which month had the most..."), and two are reading questions.

**`eval/questions.json`** is the search test set from [evaluate.md](evaluate.md). Only its 20 questions are used here, not its correct reports. All of them ask what reports say, so the router should send them all to search.

## Step by step with code snippets

### 1. Make values comparable (`normalise`)

```python
def normalise(value):
    """Compare numbers by value (3 == 3.0) and text ignoring case and spaces at either end."""
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return str(value).strip().upper()
```

**In plain steps**

```
to put a value in a standard form:
    if it is a number:
        turn it into a decimal, rounded to 2 places      (3 -> 3.0, 2.999 -> 3.0)
    otherwise:
        turn it into text, remove spaces at either end, and put it in capitals
```

**Key elements**

| Code | What it means |
|---|---|
| `isinstance(value, (int, float))` | "Is this value a whole number or a decimal?" |
| `round(float(value), 2)` | Turn it into a decimal and round it to 2 decimal places |
| `str(value)` | Turn the value into text |
| `.strip()` | Remove spaces and line breaks from the start and end |
| `.upper()` | Put the text in capitals |

**Explanation**

Two queries can give the same answer in slightly different forms. One might return `3`, another `3.0`; one might return `Battery Problem`, another `BATTERY PROBLEM`. Putting every value in a standard form first stops these differences being counted as wrong answers. Spaces inside text still count: `BETA BIONICS` and `BETABIONICS` are different.

### 2. Do two results match? (`same_result`)

```python
def same_result(reference: list, generated: list) -> bool:
    """True if both have the same number of rows and each reference row's values
    appear in a different generated row (extra columns allowed)."""
    if len(reference) != len(generated):
        return False
    remaining = [Counter(map(normalise, row)) for row in generated]
    for row in reference:
        wanted = Counter(map(normalise, row))
        match = next((i for i, have in enumerate(remaining) if not wanted - have), None)
        if match is None:
            return False
        remaining.pop(match)
    return True
```

**In plain steps**

```
to compare the reference result with the LLM's result:
    if they have a different number of rows: not a match

    remaining = each of the LLM's rows, as a bag of standardised values

    for each reference row:
        wanted = its values, standardised
        find the first remaining LLM row that contains all the wanted values
        if there is none: not a match
        otherwise: set that LLM row aside, so it cannot be used again

    every reference row found its own LLM row: a match
```

**Key elements**

| Code | What it means |
|---|---|
| `len(reference) != len(generated)` | "Do they have a different number of rows?" `!=` means "is not equal to" |
| `map(normalise, row)` | Apply `normalise` (step 1) to every value in the row |
| `Counter(...)` | A tally of values: which values appear, and how many times each. Column order is ignored |
| `wanted - have` | Tally subtraction: the wanted values that are missing from `have`. Empty means none are missing |
| `not wanted - have` | "Is nothing missing?" An empty tally counts as false, so `not` turns it into yes |
| `next((...), None)` | The position of the first row that fits, or `None` if none does |
| `remaining.pop(match)` | Remove that row from the list |

**Explanation**

This is how a query is marked correct. It compares **results**, not the SQL text, because many different queries give the same answer. For "how many death reports are there?", these all return 8:

```sql
SELECT COUNT(*) FROM reports WHERE event_type = 'DEATH'
SELECT COUNT(report_number) FROM reports WHERE event_type LIKE 'death'
SELECT COUNT(*) AS deaths FROM reports WHERE event_type IN ('DEATH')
```

Comparing the text would mark two of them wrong. Comparing results treats them all as correct, which is what a user cares about.

The rules for a match are:

- **Same number of rows.** An extra row or a missing row is wrong. Asking for the five most common problems and getting six is a wrong answer.
- **Every value of each reference row must appear in a different LLM row.** The "different" part matters: two reference rows cannot both be matched by the same LLM row.
- **Extra columns are allowed.** The reference for C03 is the single value `8`. An LLM query returning `DEATH | 8` is still correct; the label beside the count is helpful, not wrong.
- **Row order is ignored.** The reference rows can be found in any order.
- **Numbers are compared by value, text without case** (step 1).

### 3. Score the counting questions (`score_counting`)

```python
def score_counting(verbose: bool) -> None:
    from .sql import run_sql, write_sql

    questions = json.loads((EVAL / "counting.json").read_text())
    correct = 0
    print("| ID | Question | Correct | Generated query |\n|---|---|---|---|")
    for q in questions:
        reference = run_sql(q["reference_sql"])["rows"]
        sql = ""
        try:
            sql = write_sql(q["question"])["sql"]
            ok = same_result(reference, run_sql(sql)["rows"])
        except Declined:
            sql, ok = "(declined)", False
        except Exception as e:  # a query that fails to run is simply wrong
            sql, ok = f"{sql}  -- error: {e}", False
        correct += ok
        if verbose:
            print(f"| {q['id']} | {q['question']} | {'yes' if ok else 'no'} | `{sql}` |")
    print(f"\n{correct} of {len(questions)} counting questions answered correctly ({correct / len(questions):.0%}).")
```

**In plain steps**

```
to score the counting questions:
    load the questions from eval/counting.json
    correct = 0
    print a table heading

    for each question:
        reference = run the person-written query and keep its rows
        try:
            sql = ask the LLM to write a query for the question
            ok  = does running it give the same result as the reference? (step 2)
        if the model declined: record "(declined)", and count it wrong
        if anything else went wrong (for example the query had an error):
            record the query and the error, and count it wrong
        if ok: add 1 to correct
        with -v: print a row: id, question, yes/no, and the LLM's query

    print "N of 12 counting questions answered correctly (percentage)"
```

**Key elements**

| Code | What it means |
|---|---|
| `from .sql import run_sql, write_sql` | Bring in the two functions from `sql.py`. Done inside the function so the routing suite does not need them |
| `EVAL / "counting.json"` | The file path: the `eval` folder, then the file name |
| `.read_text()` | Read the whole file as text |
| `run_sql(q["reference_sql"])["rows"]` | Run the reference query through the same safe function the LLM's query uses, and keep the rows |
| `write_sql(q["question"])["sql"]` | Ask the LLM for a query and take the `sql` field of its reply |
| `except Exception as e:` | Catch any other problem, call it `e` |
| `correct += ok` | Add `ok` to the total. Yes counts as 1, no as 0 |
| `:.0%` | Show a fraction as a whole percentage, so `0.75` becomes `75%` |

**Explanation**

The reference answer is computed fresh from the database each time, not stored in the file. If the data is downloaded again, the reference answers change with it, and the questions stay valid. The reference query is run through `run_sql`, the same function used for the LLM's query, so both are subject to the same 200-row limit.

Every kind of failure counts as wrong: a refusal, a query with an error, a query `run_sql` refuses, or a query that runs but gives different numbers. A failure does not stop the run; the next question is scored.

This suite calls `write_sql` once per question. `ask_sql` in [sql.md](sql.md) retries once if the first query fails; this evaluation does not. As the file's own description says, it scores the first attempt only, so it is a slightly stricter test than what a user gets.

The table is in Markdown, so it can be pasted into a results record in `eval/results/`.

### 4. Score the router (`score_routing`)

```python
def score_routing(verbose: bool) -> None:
    from .router import route

    cases = (
        [(q["id"], q["question"], "search") for q in json.loads((EVAL / "questions.json").read_text())]
        + [(q["id"], q["question"], "sql") for q in json.loads((EVAL / "counting.json").read_text())]
        + [(q["id"], q["question"], q["expected"]) for q in json.loads((EVAL / "routing.json").read_text())]
    )
    confusion = Counter()
    print("| ID | Question | Expected | Chosen |\n|---|---|---|---|")
    for qid, question, expected in cases:
        try:
            chosen = route(question)["route"]
        except Declined:
            chosen = "declined"
        confusion[expected, chosen] += 1
        if verbose or chosen != expected:
            print(f"| {qid} | {question} | {expected} | {chosen} |")
    right = sum(n for (e, c), n in confusion.items() if e == c)
    print(f"\n{right} of {len(cases)} questions routed as expected ({right / len(cases):.0%}).")
    for expected in ["search", "sql", "agent"]:
        row = {c: n for (e, c), n in confusion.items() if e == expected}
        print(f"  expected {expected}: {row}")
```

**In plain steps**

```
to score the router:
    cases = a list of (id, question, expected route), made from:
        every question in questions.json, expected "search"
        every question in counting.json,  expected "sql"
        every question in routing.json,   expected the route written beside it

    confusion = an empty tally of (expected, chosen) pairs
    print a table heading

    for each case:
        ask the router which route it chooses
        if the model declined: call the choice "declined"
        add 1 to the tally for (expected, chosen)
        print a row if -v was typed, or if the choice was wrong

    right = the total of all tallies where expected and chosen agree
    print "N of 41 questions routed as expected (percentage)"
    for each expected route: print what the router actually chose, with counts
```

**Key elements**

| Code | What it means |
|---|---|
| `(q["id"], q["question"], "search")` | A *tuple*: a small fixed group of values, here the id, the question and the expected route |
| `[... for q in ...] + [...] + [...]` | Build three lists and join them into one |
| `route(question)["route"]` | Ask the router (see `router.py`) and take the `route` field of its decision |
| `confusion[expected, chosen] += 1` | Add 1 to the tally for this pair, for example `("sql", "search")` |
| `if verbose or chosen != expected:` | Print the row when `-v` was typed, or when the router got it wrong |
| `for (e, c), n in confusion.items()` | Go through every tallied pair `(e, c)` and its count `n` |
| `{c: n for ... if e == expected}` | Build a record of choices and counts, for one expected route |

**Explanation**

The router is tested on 41 questions. The first 32 are reused from the other test sets, and their correct route follows from what they are: the search questions only make sense as search, the counting questions only as SQL. The 9 in `routing.json` add the cases the other files do not cover, mainly the agent route, plus counting and reading questions phrased in ways that could mislead.

Without `-v`, only the wrong choices are printed. This keeps the output short when most choices are right.

The last lines print a *confusion summary*: for each expected route, what the router actually chose. A line like

```
  expected sql: {'sql': 13, 'search': 1}
```

would mean 13 counting questions went to SQL and 1 went to search by mistake. (This is an illustration of the format, not an observed result.) A single overall percentage hides which way the mistakes go. Sending a counting question to search gives a guessed number; sending a reading question to SQL gives a table where the user wanted excerpts. These are different failures, and the summary shows which one is happening.

### 5. Choose the suite (`main`)

```python
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=["counting", "routing"], required=True)
    parser.add_argument("-v", "--verbose", action="store_true", help="show every question")
    args = parser.parse_args()
    (score_counting if args.suite == "counting" else score_routing)(args.verbose)
```

**In plain steps**

```
accept --suite, which must be "counting" or "routing" and must be given
accept -v, an on/off switch for showing every question
if the suite is "counting": run step 3
otherwise: run step 4
```

**Key elements**

| Code | What it means |
|---|---|
| `choices=[...]` | Only these values are accepted |
| `required=True` | The option must be given; there is no default |
| `(a if condition else b)(args.verbose)` | Pick one of two functions, then run it with the `-v` setting |

**Explanation**

The suite must be named because each run costs money. There is no "run everything" default, so a run is never more expensive than intended.

## What to keep in mind

- **Not yet run.** No API key was available when this file was written, so neither suite has been run against the real API and there are no results to report. The reference answers above come from the person-written queries, not from the LLM.
- **The test sets are small.** 12 counting questions means one question is about 8 percentage points. 9 routing questions cover the agent route with only 5 examples. Small differences between runs are noise.
- **The LLM's answers can vary between runs.** The same question can produce a different query or route on another run. A single run is one sample, not a fixed property of the system.
- **The reference queries were written by a person and encode choices.** Each question should have one clearly right answer, and C09 and C11 were reworded for that reason. Text searches of narratives remain rough: `LIKE '%KETOACIDOSIS%'` finds the word, not every report describing the condition.
- **C11 compares only the count.** A query that returns 457 beside the wrong company name would still pass. Only 457 is checked.
- **Allowing extra columns can let a lucky match through.** A reference row holding a single number matches any LLM row that contains that number in any column. With the row count also required to match, this is unlikely, but possible.
- **Routing is scored on the route only.** The router also extracts filters, such as a brand or event type, for the search method. Whether those filters are right is not scored here.
- **The counting suite scores the first attempt only**, without the retry the real `ask_sql` makes, and it does not score the written explanation at all.

# `maude_rag/sql.py`

## Purpose

This file answers counting questions: "how many", "which is most common", "how many per month". It does this by having the LLM write a database query, running that query, and then having the LLM explain the result in plain words.

It is step 3 of the roadmap. Steps 1 and 2 cannot count. Search hands the LLM only the 8 most relevant excerpts (see [ask.md](ask.md)), so a question such as "how many death reports are there?" would be answered from 8 excerpts out of about 3,000 reports. Any number the LLM gave would be a guess.

A database, by contrast, can look at every report. The reports are copied into a small database file, `data/reports.db`, using *SQLite*, a database that lives in a single file and comes built into Python. Questions to it are written in *SQL* (Structured Query Language), the standard language for asking a database questions. A single question in SQL is called a *query*. For example:

```sql
SELECT event_type, COUNT(*) FROM reports GROUP BY event_type
```

reads as "from the reports table, list each event type and how many reports have it". The LLM's job is to turn the user's question into a query like this.

```bash
# Build the database from data/reports.jsonl (index.py now does this automatically)
python -m maude_rag.sql --build

# Show exactly what the LLM is told about the database: no API key needed
python -m maude_rag.sql --show-schema

# Ask a counting question: needs ANTHROPIC_API_KEY
python -m maude_rag.sql "How many reports per manufacturer were deaths or injuries?"
```

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `argparse` | Built into Python | Reads the question and options from the command line |
| `json` | Built into Python | Reads the downloaded reports, and writes the query result as text for the LLM |
| `sqlite3` | Built into Python | Creates, opens and queries the database file |
| `time` | Built into Python | Measures how long a query has been running, so a slow one can be stopped |
| `config.py` | This project | Supplies the database location (`DB_PATH`), the row limit (`MAX_SQL_ROWS`), the product code names and the report file location |
| `llm.py` | This project | Supplies `ask_claude` to call the LLM and `Declined` for refusals (see [llm.md](llm.md)) |

Building the database needs `data/reports.jsonl`, from `ingest.py`. Since step 3, `index.py` calls `build` at the end of every run, so the database is rebuilt whenever the search index is. Asking a question needs an Anthropic API key and makes two LLM calls, three if the first query fails.

## Step by step with code snippets

### 1. Describe the two tables (`TABLES`)

```python
TABLES = """\
CREATE TABLE reports (
    report_number TEXT PRIMARY KEY,
    date_received INTEGER,   -- YYYYMMDD as a number, e.g. 20250314
    month INTEGER,           -- 1 to 12
    event_type TEXT,         -- 'MALFUNCTION', 'INJURY' or 'DEATH'
    brand_name TEXT,         -- upper case, long and inconsistent: match with LIKE
    manufacturer TEXT,       -- upper case, several spellings per company: match with LIKE
    product_code TEXT,       -- FDA product code, see below
    narrative TEXT           -- the reporter's description, upper case
);
CREATE TABLE problems (      -- FDA-coded device problems; a report can have several
    report_number TEXT,
    problem TEXT             -- e.g. 'Obstruction of Flow', 'Battery Problem'
);"""
```

**In plain steps**

```
TABLES = the SQL that creates two tables:

    reports: one row per report, with columns for
        its report number (each one unique)
        the date received, the month, the event type
        the brand, the manufacturer, the product code
        the narrative

    problems: one row per (report, problem) pair
        a report with three coded problems has three rows here
```

**Key elements**

| Code | What it means |
|---|---|
| `"""\` | The start of a block of text running over several lines. The `\` stops it starting with a blank line |
| `CREATE TABLE reports (...)` | SQL for "make a table called reports with these columns". A *table* is like a spreadsheet tab: rows are reports, columns are fields |
| `TEXT`, `INTEGER` | The kind of value each column holds: text or a whole number |
| `PRIMARY KEY` | This column is unique: no two rows can share a report number |
| `-- ...` | A comment in SQL. The database ignores it, but the LLM reads it |

**Explanation**

The text does two jobs. `build` (step 2) runs it to create the tables. `schema_notes` (step 4) sends the same text to the LLM, so the LLM learns the table layout, called the *schema*. The comments are written for the LLM: they tell it, for example, that event types are in capitals and that brand names should be matched loosely.

Problems get their own table because a report can have several. These are the FDA's coded device problem terms, such as `Obstruction of Flow` or `Battery Problem`, chosen from a fixed list by whoever filed the report. Being a fixed list makes them countable in a way the free-text narrative is not. To count reports with a problem, the query looks in `problems`; to combine that with brand or event type, it joins the two tables on `report_number`.

### 2. Copy the reports into the database (`build`)

```python
def build(reports: list[dict], path=DB_PATH) -> None:
    """Write the reports into a fresh SQLite file."""
    path.unlink(missing_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(TABLES)
        for r in reports:
            date = int(r["date_received"] or 0)
            db.execute(
                "INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (r["report_number"], date, date // 100 % 100, r["event_type"].upper(),
                 r["brand_name"].upper(), r["manufacturer"].upper(), r["product_code"],
                 r["narrative"].upper()),
            )
            db.executemany("INSERT INTO problems VALUES (?, ?)",
                           [(r["report_number"], p) for p in dict.fromkeys(r["product_problems"])])  # openFDA repeats them
```

**In plain steps**

```
to build the database from the downloaded reports:
    delete the old database file, if there is one
    open a new, empty database file
    create the two tables from step 1

    for each report:
        date  = its date received as a number (0 if missing)
        month = the middle two digits of the date (20250314 -> 03 -> 3)
        add one row to "reports":
            report number, date, month, and event type, brand, manufacturer
            and narrative all in capitals, plus the product code
        add one row to "problems" for each of its coded problems,
            after removing repeats
    save and close the file
```

**Key elements**

| Code | What it means |
|---|---|
| `path.unlink(missing_ok=True)` | Delete the file. `missing_ok=True` means "and do not complain if it is not there" |
| `with sqlite3.connect(path) as db:` | Open the database file, and save the changes when the indented lines finish |
| `db.executescript(TABLES)` | Run the table-creating SQL from step 1 |
| `"INSERT INTO reports VALUES (?, ...)"` | SQL for "add a row". Each `?` is a blank filled in, in order, from the values that follow |
| `date // 100 % 100` | `//` divides and drops the remainder; `%` keeps only the remainder. `20250314 // 100` is `202503`, and `202503 % 100` is `3` |
| `.upper()` | Turn text into capitals |
| `db.executemany(...)` | Run the same `INSERT` once for each item in a list |
| `dict.fromkeys(r["product_problems"])` | Remove repeats from the list while keeping the order |

**Explanation**

Filling the blanks with `?` instead of pasting the values into the SQL text matters. A narrative containing a quotation mark would otherwise break the SQL. The database inserts the values safely by itself.

Everything except the product code is stored in capitals, so the LLM can match names without worrying about case. The narratives in MAUDE are already mostly in capitals.

The separate `month` column exists because "per month" is a common question, and pulling the month out of a number like `20250314` inside a query is easy to get wrong.

The `dict.fromkeys` step fixes a quirk in the source data. openFDA, the FDA's public data service, lists each coded problem twice in a report. Without removing the repeats, every problem would be counted double.

### 3. Run a query safely (`run_sql`)

At the top of the file:

```python
QUERY_SECONDS = 10  # a query running longer than this is stopped
```

```python
def run_sql(sql: str, path=DB_PATH) -> dict:
    """Run one query on a read-only connection. Returns columns, rows, and whether rows were cut off."""
    if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
        raise ValueError("Only SELECT queries are allowed.")
    # mode=ro: the database file cannot be changed, whatever the query says.
    # sqlite3 also refuses to run more than one statement per execute().
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    deadline = time.monotonic() + QUERY_SECONDS
    db.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)  # True stops the query
    try:
        cursor = db.execute(sql)
        rows = cursor.fetchmany(MAX_SQL_ROWS + 1)
        columns = [c[0] for c in cursor.description]
    finally:
        db.close()
    return {"columns": columns, "rows": rows[:MAX_SQL_ROWS], "truncated": len(rows) > MAX_SQL_ROWS}
```

**In plain steps**

```
to run a query:
    if it does not start with SELECT or WITH (ignoring spaces and case):
        refuse it

    open the database in read-only mode
    deadline = now plus 10 seconds
    tell the database: every so often while working, check the clock,
                       and stop the query if the deadline has passed
    try:
        run the query
        rows    = fetch up to 201 rows of the result
        columns = the names of the result's columns
    whatever happened: close the database connection

    hand back:
        the column names
        the first 200 rows
        "truncated": yes if there were more than 200 rows
```

**Key elements**

| Code | What it means |
|---|---|
| `sql.lstrip()` | The query with any spaces or line breaks at the start removed |
| `.startswith(("SELECT", "WITH"))` | "Does it begin with either of these words?" `SELECT` reads data; `WITH` starts a query that names a sub-result first |
| `raise ValueError(...)` | Stop and report a problem |
| `f"file:{path}?mode=ro", uri=True` | Open the file with an option attached. `mode=ro` means read-only |
| `time.monotonic()` | The current time on a clock that only moves forward, in seconds. Used for measuring how long something takes |
| `db.set_progress_handler(check, 10_000)` | Ask the database to run `check` regularly while it works (every 10,000 small internal steps). If `check` answers yes, the query is stopped with an "interrupted" error |
| `lambda: time.monotonic() > deadline` | A one-line function with no name that answers "has the deadline passed?" |
| `try:` ... `finally:` | Run the `try` lines; then run the `finally` lines whether they succeeded or failed |
| `db.close()` | Close the connection to the database file |
| `db.execute(sql)` | Run one SQL statement |
| `cursor.fetchmany(MAX_SQL_ROWS + 1)` | Fetch at most 201 rows (`MAX_SQL_ROWS` is 200 in `config.py`) |
| `cursor.description` | Information about the result's columns. `c[0]` is each column's name |
| `rows[:MAX_SQL_ROWS]` | The first 200 rows |
| `len(rows) > MAX_SQL_ROWS` | "Were there more than 200?" Fetching one extra row is how the code finds out without fetching everything |

**Explanation**

This function is a *trust boundary*: the point where text written by the LLM is run on this computer. The LLM is not malicious, but it can make mistakes, and its input includes the user's question. So the query is treated as untrusted, and three separate guards stop it changing anything:

1. **The first word must be `SELECT` or `WITH`.** These are the words that start a read. A query beginning `DELETE` or `DROP` is refused before it reaches the database.
2. **The connection is read-only.** Even if a query got past the first check, the database file cannot be changed. Trying `WITH x AS (SELECT 1) DELETE FROM reports`, which passes the first check, gives the error "attempt to write a readonly database".
3. **One statement only.** Python's `sqlite3` refuses to run two statements in one call, so `SELECT 1; DELETE FROM reports` fails with "You can only execute one statement at a time."

The read-only connection is the guard that matters most. The other two give a clearer error sooner.

A fourth guard limits time rather than changes. A badly written query, for example one that pairs every report with every other report, could run for minutes. After `QUERY_SECONDS` (10 seconds) the query is stopped with the error "interrupted". `ask_sql` treats that like any other failed query (step 7). The `finally` line makes sure the connection is closed even when the query fails or is stopped.

The row limit protects the next step rather than the database. A query that lists every narrative would produce thousands of rows, too many to send to the LLM. The result is cut off at 200 rows, and `truncated` says so, so the explanation can mention that rows are missing.

### 4. Tell the LLM what is in the database (`schema_notes`)

```python
def schema_notes(path=DB_PATH) -> str:
    """The table definitions plus real values, so the LLM knows what to match against."""
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        top = lambda q: ", ".join(f"{v} ({n})" for v, n in db.execute(q))
        manufacturers = top("SELECT manufacturer, COUNT(*) n FROM reports GROUP BY 1 ORDER BY n DESC LIMIT 12")
        problems = top("SELECT problem, COUNT(*) n FROM problems GROUP BY 1 ORDER BY n DESC LIMIT 25")
        n, first, last = db.execute("SELECT COUNT(*), MIN(date_received), MAX(date_received) FROM reports").fetchone()
    codes = ", ".join(f"{c} = {name}" for c, name in PRODUCT_CODES.items())
    return (
        f"{TABLES}\n\n"
        f"The database holds a SAMPLE of {n} insulin pump reports received {first} to {last}, "
        f"about {n // 12} per month spread across the days. It is not every report the FDA received.\n"
        f"Product codes: {codes}\n"
        f"Manufacturers (report count): {manufacturers}\n"
        f"Most common problems (report count): {problems}"
    )
```

**In plain steps**

```
to write the notes the LLM is given:
    open the database read-only
    manufacturers = the 12 most common manufacturer spellings, each with its count
    problems      = the 25 most common coded problems, each with its count
    n, first, last = the number of reports, and the earliest and latest dates
    codes = each product code with its name

    hand back:
        the table definitions from step 1
        a note that this is a SAMPLE of n reports between those dates
        the product codes
        the manufacturers
        the most common problems
```

**Key elements**

| Code | What it means |
|---|---|
| `lambda q: ...` | A one-line function with no name. Here `top(query)` runs the query and writes each value with its count in brackets |
| `COUNT(*) n` | Count the rows and call the count `n` |
| `GROUP BY 1` | Make one result row per distinct value of the first column |
| `ORDER BY n DESC LIMIT 12` | Sort by count, largest first, and keep the first 12 |
| `MIN(...)`, `MAX(...)` | The smallest and largest value in the column |
| `.fetchone()` | Fetch the single result row |
| `n, first, last = ...` | Store the three values of that row under three names |
| `n // 12` | The number of reports divided by 12 months, dropping any remainder |
| `PRODUCT_CODES.items()` | Each product code and its name, from `config.py` |

**Explanation**

The table layout alone is not enough to write a correct query. The LLM also needs to know what the values actually look like. Running the command shows what it is told today (shortened):

```
The database holds a SAMPLE of 2984 insulin pump reports received 20250101 to 20251231, about 248 per month spread across the days. It is not every report the FDA received.
Product codes: LZG = Pump, Infusion, Insulin, QFG = Alternate Controller Enabled Insulin Infusion Pump, ...
Manufacturers (report count): MEDTRONIC PUERTO RICO OPERATIONS CO. (1396), TANDEM DIABETES CARE (1020), BETA BIONICS INC. (196), MEDTRONIC MINIMED (184), INSULET CORPORATION (84), BETA BIONICS, INC. (51), BETA BIONICS INC (40), ...
Most common problems (report count): Obstruction of Flow (434), Pumping Stopped (379), ..., Battery Problem (150), ...
```

Three things in these notes prevent likely mistakes:

- **Manufacturer spellings.** Beta Bionics appears under six spellings and Medtronic under three. A query for `manufacturer = 'BETA BIONICS INC.'` would miss about a third of their reports. Seeing the real spellings tells the LLM to match loosely, with `LIKE '%BETA BIONIC%'`.
- **Problem wording.** Coded problems must be matched exactly as written, such as `Obstruction of Flow`, not "occlusion". The list gives the LLM the real terms.
- **The sample warning.** The download takes a sample of about 250 reports per month (see [ingest.md](ingest.md)), not every report. The notes say so in capitals, so the explanation in step 7 does not present the counts as FDA totals.

The notes are computed from the database each time, so they stay correct if the data is downloaded again. The "per month" figure is the report count divided by 12, which assumes the data covers a whole year.

### 5. The instructions and the reply shape (`WRITE_SYSTEM`, `QUERY_SCHEMA`, `ANSWER_SYSTEM`)

```python
WRITE_SYSTEM = """You write one SQLite query that answers a question about FDA MAUDE \
insulin pump reports. Use only the tables described. Match brand and manufacturer \
names with LIKE and upper-case wildcards (e.g. manufacturer LIKE '%TANDEM%'), because \
names are long and spelled several ways. Count reports with COUNT(DISTINCT \
report_number) when joining to problems. Keep the result small: aggregate rather \
than listing rows, and use LIMIT when listing."""

QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string", "description": "One SQLite SELECT query"},
        "explanation": {"type": "string", "description": "One sentence on what the query counts"},
    },
    "required": ["sql", "explanation"],
    "additionalProperties": False,
}

ANSWER_SYSTEM = """You explain the result of a database query about FDA MAUDE insulin \
pump reports. Answer the question in a few sentences using only the numbers in the \
result. Say what was counted. Always note that these are counts within a sample of \
about 3,000 reports from 2025, not all reports, and that report counts are not rates: \
they do not show how often a problem happens to patients."""
```

**In plain steps**

```
WRITE_SYSTEM = standing instructions for writing the query:
    write one query, using only the tables described
    match brand and manufacturer names loosely
    count each report once when joining to the problems table
    keep the result small

QUERY_SCHEMA = the shape the reply must have:
    a field "sql" holding the query, as text
    a field "explanation" holding one sentence, as text
    both are required, and nothing else is allowed

ANSWER_SYSTEM = standing instructions for explaining the result:
    answer in a few sentences, using only the numbers given
    say what was counted
    always say this is a sample, and that counts are not rates
```

**Key elements**

| Code | What it means |
|---|---|
| `LIKE '%TANDEM%'` | SQL for "contains TANDEM". `%` stands for any text, including none |
| `COUNT(DISTINCT report_number)` | Count each report number once, however many rows it appears in |
| `"type": "object"` | The reply must be a set of labelled fields |
| `"required": [...]` | These fields must be present |
| `"additionalProperties": False` | No other fields are allowed |

**Explanation**

Each line of `WRITE_SYSTEM` heads off a specific mistake. The `COUNT(DISTINCT ...)` rule matters when joining: a report with three problems appears three times after joining to `problems`, so a plain `COUNT(*)` would count it three times.

`QUERY_SCHEMA` is passed to `ask_claude` as the reply's shape. With structured output the reply is guaranteed to have exactly these two fields, so the code can read `query["sql"]` directly (see [llm.md](llm.md), step 3a).

`ANSWER_SYSTEM` carries the most important caveat in the project. A count of reports is not a rate of failure. A device with more reports may simply have more users, and MAUDE reporting is voluntary for patients and uneven across companies. The instructions require every answer to say this.

### 6. Ask the LLM for a query (`write_sql`)

```python
def write_sql(question: str, error: str | None = None, previous: str | None = None) -> dict:
    prompt = f"<schema>\n{schema_notes()}\n</schema>\n\nQuestion: {question}"
    if error:  # one retry: show the failed query and the error
        prompt += f"\n\nThis query failed:\n{previous}\nError: {error}\nWrite a corrected query."
    return ask_claude(WRITE_SYSTEM, prompt, schema=QUERY_SCHEMA)
```

**In plain steps**

```
to get a query for a question (optionally, after a failed attempt):
    prompt = the schema notes inside <schema> tags, then "Question: " and the question
    if this is a retry:
        add the failed query, the error message, and "Write a corrected query."
    ask the LLM, with the query-writing instructions and the reply shape
    hand back its reply: {"sql": ..., "explanation": ...}
```

**Key elements**

| Code | What it means |
|---|---|
| `error: str \| None = None` | An optional input: the error from a failed attempt, or nothing |
| `<schema>` ... `</schema>` | Tags marking where the notes start and end, as `ask.py` does with reports |
| `prompt += ...` | Add more text to the end of the prompt |
| `schema=QUERY_SCHEMA` | Ask for a reply in the shape from step 5 |

**Explanation**

The same function writes the first attempt and the retry. On a retry the LLM sees exactly what went wrong, such as "no such column: brand", which is usually enough for it to fix the query.

### 7. Write, run, and explain (`ask_sql`)

```python
def ask_sql(question: str) -> dict:
    """Write a query, run it (retrying once if it fails), and explain the result."""
    query = write_sql(question)
    try:
        result = run_sql(query["sql"])
    except (sqlite3.Error, ValueError) as e:
        query = write_sql(question, error=str(e), previous=query["sql"])
        result = run_sql(query["sql"])  # a second failure is reported to the user
    table = json.dumps({"columns": result["columns"], "rows": result["rows"],
                        "truncated": result["truncated"]})
    answer = ask_claude(ANSWER_SYSTEM, f"Question: {question}\nQuery: {query['sql']}\nResult: {table}")
    return {**query, **result, "answer": answer}
```

**In plain steps**

```
to answer a counting question:
    query = ask the LLM for a query (step 6)
    try to run it (step 3)
    if it fails, either as bad SQL or as a refused non-SELECT:
        ask the LLM again, showing the failed query and the error
        run the new query; if this fails too, the error is passed up to main (step 8)

    table  = the result's columns, rows and "truncated" flag, written as JSON text
    answer = ask the LLM to explain the result, giving it the question, the query and the table

    hand back the query, its explanation, the result and the written answer, all together
```

**Key elements**

| Code | What it means |
|---|---|
| `try:` ... `except (...) as e:` | Attempt the indented lines; if they report one of these problems, call it `e` and run the `except` lines instead |
| `sqlite3.Error` | Any error from the database, such as a misspelt column or a refused write |
| `ValueError` | The error `run_sql` raises for a query that does not start with `SELECT` or `WITH` |
| `str(e)` | The error's message, as text |
| `json.dumps(...)` | Write a dictionary as JSON text, ready to paste into the prompt |
| `{**query, **result, "answer": answer}` | One dictionary combining the fields of `query`, the fields of `result`, and the answer |

**Explanation**

There are two LLM calls in the normal case. The first writes the query; the second reads the numbers and explains them. Separating them means the numbers come from the database, not from the LLM's memory, and the second call is told to use "only the numbers in the result".

The explanation call is shown the query as well as the result, so it can say what was counted, for example "reports whose manufacturer contains TANDEM". This matters because a query can be valid and still count the wrong thing.

Only one retry is allowed. A query that fails twice is likely a question the database cannot answer, and repeated attempts would cost more without much chance of success.

### 8. The command line (`print_table`, `main`)

```python
def print_table(columns: list[str], rows: list, truncated: bool) -> None:
    print(" | ".join(columns))
    for row in rows:
        print(" | ".join(str(v) for v in row))
    if truncated:
        print(f"... cut off at {MAX_SQL_ROWS} rows")
```

```python
    parser.add_argument("question", nargs="?")
    parser.add_argument("--build", action="store_true", help="rebuild the database from the downloaded reports")
    parser.add_argument("--show-schema", action="store_true", help="print what the LLM is told about the database")
    args = parser.parse_args()

    if args.build:
        build([json.loads(line) for line in RAW_REPORTS.open()])
        print(f"Built {DB_PATH}")
    if args.show_schema:
        print(schema_notes())
    if not args.question:
        return
    try:
        out = ask_sql(args.question)
    except Declined as e:
        print(e)
        return
    except (sqlite3.Error, ValueError) as e:
        print(f"The query failed twice, so there is no answer. Last error: {e}")
        return
    print(f"Query: {out['sql']}\n({out['explanation']})\n")
    print_table(out["columns"], out["rows"], out["truncated"])
    print("\n" + out["answer"])
```

**In plain steps**

```
to print a table:
    print the column names, separated by " | "
    print each row the same way
    if rows were cut off, say so

main:
    accept a question (optional), --build and --show-schema
    if --build was typed: rebuild the database from data/reports.jsonl
    if --show-schema was typed: print the notes the LLM is given
    if no question was typed: stop here

    answer the question (step 7)
        if the model declined: say so and stop
        if the query failed twice: say so, show the last error, and stop
    print the query and its one-sentence explanation
    print the result table
    print the written answer
```

**Key elements**

| Code | What it means |
|---|---|
| `nargs="?"` | The question may be left out, so `--build` and `--show-schema` work alone |
| `action="store_true"` | An on/off switch: typing the option turns it on |
| `json.loads(line) for line in RAW_REPORTS.open()` | Read the reports file one line at a time; each line is one report written as JSON |
| `except Declined as e:` | If the model declined (see [llm.md](llm.md)), print its message instead of crashing |
| `except (sqlite3.Error, ValueError) as e:` | If the second query also failed, or was stopped by the time limit, print a plain message with the error |

**Explanation**

The output shows the query and the raw table before the written answer. That order is deliberate: a reader who knows a little SQL can check what was counted before trusting the sentence that summarises it. `--show-schema` lets anyone see exactly what the LLM was told, without an API key.

## What to keep in mind

- **The LLM parts have not yet been run.** No API key was available when this step was written, so there are no observed results for how often the LLM writes a correct query. [evaluate_llm.md](evaluate_llm.md) describes how that will be measured.
- **Counts are within a sample.** The database holds 2,984 reports from 2025, about 250 per month. Every count is a count within that sample, not an FDA total.
- **Counts are not rates.** More reports for one manufacturer can mean more users, not a worse device. There is no data here on how many devices are in use.
- **Name matching is only as good as the `LIKE` pattern.** `'%MEDTRONIC%'` catches all three Medtronic spellings, but a pattern that is too loose can catch the wrong company, and one too strict misses spellings.
- **Text searches of narratives are rough.** A query such as `narrative LIKE '%DKA%'` counts any narrative containing those letters, including inside other words, and misses reports that describe the condition in other words.
- **A valid query can still answer the wrong question.** The safeguards stop the query changing data; they do not check that it counts the right thing. Showing the query to the reader is the only check.
- **The time limit is a blunt cut-off.** A legitimate query that needs more than 10 seconds is stopped too. On a database of about 3,000 reports this is unlikely.
- **Other failures still end with a Python error message.** `main` catches refusals and query failures. A cut-off reply or a network problem from the LLM call is not caught.

"""Step 3: answer counting questions by having the LLM write a SQL query.

    python -m maude_rag.sql "How many reports per manufacturer were deaths or injuries?"
    python -m maude_rag.sql --show-schema

Search can only show a handful of reports, so it cannot count. For questions
like "how many" or "which is most common", the reports are copied into a small
SQLite database, the LLM writes a query, the query runs on a read-only
connection, and the LLM explains the result.
"""

import argparse
import json
import sqlite3
import time

from .config import DB_PATH, MAX_SQL_ROWS, PRODUCT_CODES, RAW_REPORTS
from .llm import Declined, ask_claude

QUERY_SECONDS = 10  # a query running longer than this is stopped

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


def write_sql(question: str, error: str | None = None, previous: str | None = None) -> dict:
    prompt = f"<schema>\n{schema_notes()}\n</schema>\n\nQuestion: {question}"
    if error:  # one retry: show the failed query and the error
        prompt += f"\n\nThis query failed:\n{previous}\nError: {error}\nWrite a corrected query."
    return ask_claude(WRITE_SYSTEM, prompt, schema=QUERY_SCHEMA)


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


def print_table(columns: list[str], rows: list, truncated: bool) -> None:
    print(" | ".join(columns))
    for row in rows:
        print(" | ".join(str(v) for v in row))
    if truncated:
        print(f"... cut off at {MAX_SQL_ROWS} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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


if __name__ == "__main__":
    main()

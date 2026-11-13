"""Step 5: an agent for questions that need several steps.

    python -m maude_rag.agent "Compare the problems reported for Tandem and Insulet pumps, then check for recalls"

The LLM is given three tools and decides which to call, in what order, and
when it has enough to answer:

- search_reports: find report excerpts (steps 1 and 2)
- run_sql:        run a read-only counting query (step 3)
- check_recalls:  look up FDA recalls for insulin pumps, live from openFDA

Each tool call, and a preview of what it returned, is printed so the
reasoning can be followed and checked.
"""

import argparse
import json

import requests
from anthropic import beta_tool

from .config import AGENT_MAX_STEPS, ANSWER_MODEL, PRODUCT_CODES, RECALL_API
from .llm import FALLBACK, client

SYSTEM = """You answer multi-step questions about insulin pump safety using FDA data. \
You have three tools: search_reports (read what adverse event reports say), \
run_sql (count reports in a database), and check_recalls (FDA recall records).

Plan briefly, call the tools you need, then answer. Cite report numbers in square \
brackets for anything taken from reports, and recall event numbers for recalls. \
Keep these limits in mind and state them where they matter: the reports are a \
sample of about 3,000 from 2025, not all reports; reports are unverified and do \
not show that a device caused an event; counts are not rates; recalls come from a \
separate FDA database and may cover devices or years outside the sample.

Database schema for run_sql:
{schema}"""


def recall_url(firm: str = "", limit: int = 100) -> str:
    """openFDA query for insulin pump recalls, newest first, optionally for one firm."""
    codes = "+".join(f"product_code:{c}" for c in PRODUCT_CODES)
    search = f"({codes})"
    if firm:
        # Built by hand because openFDA needs literal "+" between words and terms.
        search += f'+AND+recalling_firm:"{"+".join(firm.split())}"'
    return f"{RECALL_API}?search={search}&sort=event_date_initiated:desc&limit={limit}"


def summarise_recalls(records: list[dict], max_events: int = 10) -> str:
    """One entry per recall event. openFDA returns one record per recalled product,
    so the same event can appear many times."""
    events = {}
    for r in records:
        events.setdefault(r.get("res_event_number"), r)
    entries = []
    for r in list(events.values())[:max_events]:
        text = lambda field, n: (r.get(field) or "")[:n]  # fields can be missing or empty
        entries.append(
            f"Recall {r.get('res_event_number')} ({r.get('recall_status')}), initiated {r.get('event_date_initiated')}, "
            f"{r.get('recalling_firm')}, product code {r.get('product_code')}.\n"
            f"Product: {text('product_description', 200)}\n"
            f"Reason: {text('reason_for_recall', 400)}\n"
            f"Root cause: {r.get('root_cause_description')}"
        )
    more = f"\n\n(At least {len(events) - max_events} older recall events not shown.)" if len(events) > max_events else ""
    return "\n\n".join(entries) + more


def show(tool: str, result: str) -> str:
    """Print a short preview of what a tool returned, so each step can be checked."""
    if SHOW_STEPS:
        print(f"   {tool} returned: {result[:150].replace(chr(10), ' ')}...")
    return result


SHOW_STEPS = True


@beta_tool
def search_reports(query: str, event_type: str = "", brand: str = "", manufacturer: str = "",
                   since: int = 0, until: int = 0) -> str:
    """Search adverse event report narratives by meaning and keywords. Returns up to 8 excerpts.

    Args:
        query: What to look for, in plain words.
        event_type: Optional: Malfunction, Injury or Death.
        brand: Optional: part of a brand name, e.g. 780G or Omnipod.
        manufacturer: Optional: part of a company name, e.g. Tandem.
        since: Optional: received on or after this date, YYYYMMDD. 0 for no limit.
        until: Optional: received on or before this date, YYYYMMDD. 0 for no limit.
    """
    from .ask import filters_to_where, retrieve

    try:
        where = filters_to_where(event_type or None, brand or None, manufacturer or None, since or None, until or None)
    except LookupError:
        return show("search_reports", "No brand or manufacturer contains that text. Try a shorter part of "
                    "the name, or leave it empty and put the name in the query instead.")
    hits = retrieve(query, where=where)
    return show("search_reports", "\n\n".join(
        f"[{h['report_number']}] {h['brand_name']}, {h['event_type']}, received {h['date_received']}: {h['text']}"
        for h in hits
    ) or "No matching reports.")


@beta_tool
def run_sql(sql: str) -> str:
    """Run one read-only SQLite SELECT query on the reports database and return the rows as JSON.

    Args:
        sql: A single SELECT query using the tables in the schema.
    """
    from .sql import run_sql as run

    try:
        return show("run_sql", json.dumps(run(sql)))
    except Exception as e:  # show the error to the model so it can fix the query
        return show("run_sql", f"Query failed: {e}")


@beta_tool
def check_recalls(firm: str = "") -> str:
    """Look up FDA recalls of insulin pumps, newest first, from openFDA. Returns up to 10 recall events.

    Args:
        firm: Optional: part of the recalling company's name, e.g. Tandem. Leave empty for all firms.
    """
    try:
        response = requests.get(recall_url(firm), timeout=60)
        if response.status_code == 404:  # openFDA's way of saying "no results"
            return show("check_recalls", "No recalls found.")
        response.raise_for_status()
        records = response.json()["results"]
    except (requests.RequestException, ValueError, KeyError) as e:
        return show("check_recalls", f"Recall lookup failed: {e}")
    return show("check_recalls", summarise_recalls(records))


TOOLS = [search_reports, run_sql, check_recalls]


def run_agent(question: str) -> str:
    """Let the LLM call tools until it can answer. Returns the final answer."""
    from .sql import schema_notes

    runner = client().beta.messages.tool_runner(
        model=ANSWER_MODEL,
        max_tokens=16000,
        max_iterations=AGENT_MAX_STEPS,
        system=SYSTEM.format(schema=schema_notes()),
        tools=TOOLS,
        messages=[{"role": "user", "content": question}],
        **FALLBACK,
    )
    final = None
    for message in runner:  # one message per model turn
        final = message
        if SHOW_STEPS:
            for block in message.content:
                if block.type == "tool_use":
                    print(f"-> {block.name}({json.dumps(block.input)})")
    if final.stop_reason == "refusal":
        return "The model declined to answer this question."
    text = "".join(block.text for block in final.content if block.type == "text")
    if final.stop_reason == "tool_use":  # stopped by the round limit, not by choice
        text += f"\n\n(Stopped after {AGENT_MAX_STEPS} rounds of tool calls; the answer may be incomplete.)"
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    args = parser.parse_args()
    print("\n" + run_agent(args.question))


if __name__ == "__main__":
    main()

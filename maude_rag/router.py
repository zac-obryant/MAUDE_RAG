"""Step 4: decide how to answer a question, then answer it (Adaptive RAG).

    python -m maude_rag.router "What do reports say about pumps getting wet?"
    python -m maude_rag.router "How many death reports were there per manufacturer?"
    python -m maude_rag.router --route-only "Compare Tandem and Insulet, then check for recalls"

Different questions need different machinery. One quick LLM call (low effort) reads the
question and picks one of three routes:

- search: find and quote reports (steps 1 and 2), with any filters it implies
- sql:    count or rank reports with a database query (step 3)
- agent:  several steps, such as comparing two things or checking recalls (step 5)
"""

import argparse

from .llm import Declined, ask_claude

ROUTES = ["search", "sql", "agent"]

SYSTEM = """You route questions about FDA MAUDE insulin pump adverse event reports \
to one of three answering methods. Choose:

- "search" when the answer comes from reading what reports say: what happened, \
what problems are described, examples of an issue.
- "sql" when the answer is a number or a ranking: how many, how often, which is \
most common, counts per month or per manufacturer.
- "agent" when the question needs several steps or a source other than the \
reports: comparing two devices or companies across several aspects, combining \
counts with examples, or anything about recalls.

Also extract filters that the question states outright, for the search method. \
Use "" or 0 for a filter the question does not state. Dates are YYYYMMDD numbers; \
the reports are from 2025."""

SCHEMA = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": ROUTES},
        "reason": {"type": "string", "description": "One short sentence"},
        "filters": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "enum": ["", "Malfunction", "Injury", "Death"]},
                "brand": {"type": "string", "description": "Part of a brand name, e.g. 780G or Omnipod"},
                "manufacturer": {"type": "string", "description": "Part of a company name, e.g. Tandem"},
                "since": {"type": "integer", "description": "Received on or after, YYYYMMDD"},
                "until": {"type": "integer", "description": "Received on or before, YYYYMMDD"},
            },
            "required": ["event_type", "brand", "manufacturer", "since", "until"],
            "additionalProperties": False,
        },
    },
    "required": ["route", "reason", "filters"],
    "additionalProperties": False,
}


def route(question: str) -> dict:
    """Ask the LLM which route fits. Returns route, reason, and the filters it stated."""
    decision = ask_claude(SYSTEM, question, schema=SCHEMA, effort="low")
    decision["filters"] = {k: v for k, v in decision["filters"].items() if v}  # drop "" and 0
    return decision


def answer_by_search(question: str, filters: dict) -> None:
    from .ask import answer, filters_to_where, retrieve

    try:
        where = filters_to_where(**filters)
    except LookupError:  # a name the router guessed matches nothing: keep the other filters
        print("No brand or manufacturer contains the name the router picked; searching without it.")
        filters = {k: v for k, v in filters.items() if k not in ("brand", "manufacturer")}
        where = filters_to_where(**filters)
    hits = retrieve(question, where=where)
    for h in hits:
        print(f"  {h['found_by']:<7}  {h['report_number']}  {h['brand_name']}: {h['text'][:70]}...")
    print("\n" + (answer(question, hits) if hits else "No matching reports."))


def answer_by_sql(question: str) -> None:
    from .sql import ask_sql, print_table

    out = ask_sql(question)
    print(f"Query: {out['sql']}\n")
    print_table(out["columns"], out["rows"], out["truncated"])
    print("\n" + out["answer"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--route-only", action="store_true", help="show the decision without answering")
    args = parser.parse_args()

    try:
        decision = route(args.question)
        print(f"Route: {decision['route']} ({decision['reason']})")
        if decision["filters"]:
            print(f"Filters: {decision['filters']}")
        print()
        if args.route_only:
            return
        if decision["route"] == "search":
            answer_by_search(args.question, decision["filters"])
        elif decision["route"] == "sql":
            answer_by_sql(args.question)
        else:
            from .agent import run_agent

            print(run_agent(args.question))
    except Declined as e:
        print(e)


if __name__ == "__main__":
    main()

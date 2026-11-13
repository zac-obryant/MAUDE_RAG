"""Score the steps that use the LLM: SQL counting (step 3) and the router (step 4).

    python -m maude_rag.evaluate_llm --suite counting -v
    python -m maude_rag.evaluate_llm --suite routing -v

Needs an Anthropic API key and makes one or more LLM calls per question.

- counting: each question in eval/counting.json has a reference query written by
  a person. The LLM's query is correct if it returns the same rows. Extra
  columns are allowed (a label beside a count), extra or missing rows are not.
  Only the first query is scored, without the one retry that `ask_sql` allows,
  so this is slightly stricter than what a user gets.
- routing: the router should send every retrieval question (eval/questions.json)
  to "search", every counting question to "sql", and each question in
  eval/routing.json to the route listed there.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from .llm import Declined

EVAL = Path(__file__).resolve().parent.parent / "eval"


def normalise(value):
    """Compare numbers by value (3 == 3.0) and text ignoring case and spaces at either end."""
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return str(value).strip().upper()


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=["counting", "routing"], required=True)
    parser.add_argument("-v", "--verbose", action="store_true", help="show every question")
    args = parser.parse_args()
    (score_counting if args.suite == "counting" else score_routing)(args.verbose)


if __name__ == "__main__":
    main()

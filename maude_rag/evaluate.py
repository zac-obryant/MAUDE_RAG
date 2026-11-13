"""Measure how well retrieval finds the right reports for a fixed set of questions.

    python -m maude_rag.evaluate                  # score every search mode
    python -m maude_rag.evaluate --mode vector -v # one mode, with per-question detail

The questions and the reports that count as correct are in eval/questions.json.
Each question is judged one of two ways:

- "pattern": a report is correct if its narrative matches a text pattern and it
  passes the question's filters. Used where the criterion is about wording,
  such as an error code. Checked against every downloaded report. An optional
  "exclude" list removes reports the pattern matches wrongly, such as "no occlusion".
- "reading": a person read the candidate reports ("judged") and listed the
  correct ones ("relevant"). A retrieved report nobody has read is "unjudged";
  it counts as wrong, and the scorer reports how many there were.

No API key is needed: only retrieval is scored, not the written answer.
"""

import argparse
import json
import re
from pathlib import Path

from .ask import filters_to_where, retrieve
from .config import RAW_REPORTS, TOP_K

QUESTIONS = Path(__file__).resolve().parent.parent / "eval" / "questions.json"
MODES = ["vector", "keyword", "hybrid"]


def passes(report: dict, filters: dict) -> bool:
    """Does this report pass the question's filters? Mirrors the --filter options."""
    date = int(report["date_received"] or 0)
    return (
        filters.get("event_type", report["event_type"]).upper() == report["event_type"].upper()
        and filters.get("brand", "").upper() in report["brand_name"].upper()
        and filters.get("manufacturer", "").upper() in report["manufacturer"].upper()
        and filters.get("since", date) <= date <= filters.get("until", date)
    )


def correct_reports(question: dict, reports: list[dict]) -> tuple[set[str], set[str] | None]:
    """Return (the correct report numbers, the judged report numbers or None if all are judged)."""
    if question["judged_by"] == "pattern":
        pattern = re.compile(question["pattern"])
        correct = {
            r["report_number"]
            for r in reports
            if passes(r, question["filters"]) and pattern.search(r["narrative"].upper())
        }
        return correct - set(question.get("exclude", [])), None
    return set(question["relevant"]), set(question["judged"])


def score(ranked: list[str], correct: set[str], judged: set[str] | None = None) -> dict:
    """Score one ranked list of report numbers against the correct ones."""
    first = next((i for i, r in enumerate(ranked, 1) if r in correct), None)
    found = sum(r in correct for r in ranked)
    return {
        "hit": first is not None,  # at least one correct report retrieved
        "precision": found / len(ranked) if ranked else 0.0,  # share of retrieved that are correct
        "reciprocal_rank": 1 / first if first else 0.0,  # 1 if correct report is first, 1/2 if second...
        "unjudged": 0 if judged is None else sum(r not in judged for r in ranked),
    }


def evaluate(mode: str, questions: list[dict], reports: list[dict], k: int = TOP_K) -> list[dict]:
    rows = []
    for q in questions:
        hits = retrieve(q["question"], k, filters_to_where(**q["filters"]), mode)
        ranked = list(dict.fromkeys(h["report_number"] for h in hits))  # one entry per report
        correct, judged = correct_reports(q, reports)
        rows.append({"id": q["id"], "type": q["type"], "correct_total": len(correct),
                     **score(ranked, correct, judged)})
    return rows


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        "questions": n,
        "hit_rate": sum(r["hit"] for r in rows) / n,
        "precision": sum(r["precision"] for r in rows) / n,
        "mrr": sum(r["reciprocal_rank"] for r in rows) / n,
        "unjudged": sum(r["unjudged"] for r in rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=MODES, help="score one mode (default: all)")
    parser.add_argument("-k", type=int, default=TOP_K, help="number of chunks retrieved per question")
    parser.add_argument("-v", "--verbose", action="store_true", help="show every question")
    args = parser.parse_args()

    questions = json.loads(QUESTIONS.read_text())
    reports = [json.loads(line) for line in RAW_REPORTS.open()]

    print(f"{len(questions)} questions, top {args.k} chunks each\n")
    results = {mode: evaluate(mode, questions, reports, args.k) for mode in ([args.mode] if args.mode else MODES)}

    print("| Mode | Question type | Questions | Hit rate | Precision | MRR | Unjudged |")
    print("|---|---|---|---|---|---|---|")
    for mode, rows in results.items():
        for kind in sorted({r["type"] for r in rows}) + ["all"]:
            s = summarise([r for r in rows if kind in ("all", r["type"])])
            print(f"| {mode} | {kind} | {s['questions']} | {s['hit_rate']:.0%} | "
                  f"{s['precision']:.0%} | {s['mrr']:.2f} | {s['unjudged']} |")

    if args.verbose:
        for mode, rows in results.items():
            print(f"\n**{mode}**\n")
            print("| ID | Type | Correct reports in data | Hit | Precision | Reciprocal rank | Unjudged |")
            print("|---|---|---|---|---|---|---|")
            for r in rows:
                print(f"| {r['id']} | {r['type']} | {r['correct_total']} | {'yes' if r['hit'] else 'no'} | "
                      f"{r['precision']:.0%} | {r['reciprocal_rank']:.2f} | {r['unjudged']} |")
    unreviewed = [q["id"] for q in questions if not q["reviewed"]]
    if unreviewed:
        print(f"\nNot yet reviewed by a person: {', '.join(unreviewed)} (see eval/questions.json).")


if __name__ == "__main__":
    main()

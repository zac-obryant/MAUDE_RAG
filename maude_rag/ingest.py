"""Step 1a: download insulin pump adverse event reports from openFDA.

    python -m maude_rag.ingest --year 2025 --per-month 250

Reports are spread evenly across every day of one year, so the sample is not
dominated by a few days' submissions. Output: data/reports.jsonl, one slimmed
report per line.
"""

import argparse
import calendar
import json
import time

import requests

from .config import NARRATIVE_TYPE, PRODUCT_CODES, RAW_REPORTS

API = "https://api.fda.gov/device/event.json"
PAGE = 1000  # openFDA's maximum page size


def slim(report: dict) -> dict | None:
    """Keep only the fields the pipeline uses. Returns None if there is no narrative."""
    narrative = " ".join(
        t["text"].strip()
        for t in report.get("mdr_text", [])
        if t.get("text_type_code") == NARRATIVE_TYPE and t.get("text")
    )
    if not narrative:
        return None
    device = (report.get("device") or [{}])[0]
    return {
        "report_number": report.get("report_number", ""),
        "date_received": report.get("date_received", ""),
        "event_type": report.get("event_type", ""),
        "brand_name": device.get("brand_name", ""),
        "generic_name": device.get("generic_name", ""),
        "manufacturer": device.get("manufacturer_d_name", ""),
        "product_code": device.get("device_report_product_code", ""),
        "product_problems": report.get("product_problems") or [],
        "narrative": narrative,
    }


def fetch_day(year: int, month: int, day: int, wanted: int) -> list[dict]:
    """Up to `wanted` reports received on one day (fewer if the day has fewer)."""
    if wanted <= 0:
        return []
    codes = "+".join(PRODUCT_CODES)
    date = f"{year}{month:02d}{day:02d}"
    # Built by hand because openFDA needs literal "+" and "[ ]" in the query.
    url = (
        f"{API}?search=device.device_report_product_code:({codes})"
        f"+AND+date_received:[{date}+TO+{date}]&limit={min(PAGE, wanted)}"
    )
    response = requests.get(url, timeout=60)
    time.sleep(0.3)  # stay well inside the unauthenticated rate limit
    if response.status_code == 404:  # openFDA's way of saying "no results"
        return []
    response.raise_for_status()
    return [r for r in map(slim, response.json()["results"]) if r][:wanted]


def fetch_month(year: int, month: int, wanted: int) -> list[dict]:
    """Spread `wanted` reports across every day of the month.

    openFDA returns reports in date order, so taking the first 250 of a month
    gives the first day or two only. Instead each day gets an even share, and a
    day that falls short (a weekend, say) passes its unused share to the days after it.
    """
    days = calendar.monthrange(year, month)[1]
    kept: list[dict] = []
    for day in range(1, days + 1):
        days_left = days - day + 1
        share = -(-(wanted - len(kept)) // days_left)  # round up
        kept.extend(fetch_day(year, month, day, share))
    # ponytail: within a day, openFDA's first N are still in its own order;
    # randomise with skip offsets if same-day manufacturer batches skew results.
    return kept[:wanted]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--per-month", type=int, default=250)
    args = parser.parse_args()

    RAW_REPORTS.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    with RAW_REPORTS.open("w") as out:
        for month in range(1, 13):
            reports = fetch_month(args.year, month, args.per_month)
            new = [r for r in reports if r["report_number"] not in seen]
            seen.update(r["report_number"] for r in new)
            for report in new:
                out.write(json.dumps(report) + "\n")
            print(f"{args.year}-{month:02d}: {len(new)} reports")
    print(f"Saved {len(seen)} reports to {RAW_REPORTS}")


if __name__ == "__main__":
    main()

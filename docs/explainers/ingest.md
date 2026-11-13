# `maude_rag/ingest.py`

## Purpose

This file downloads insulin pump adverse event reports from the FDA and saves a trimmed-down copy of each one to your computer. It is the first step of the pipeline: nothing else can run until the data is on disk.

Run it with:

```bash
python -m maude_rag.ingest --year 2025 --per-month 250
```

The result is `data/reports.jsonl`, a text file with one report per line.

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `argparse` | Built into Python | Reads the options typed on the command line (`--year`, `--per-month`) |
| `calendar` | Built into Python | Tells us how many days are in a given month |
| `json` | Built into Python | Converts each report to a line of text for saving |
| `time` | Built into Python | Pauses briefly between requests |
| `requests` | Installed package | Fetches data from a web address |
| `config.py` | This project | Supplies the product codes, narrative type and output file location |

The data comes from **openFDA**, the FDA's free public data service. No account or key is needed for this amount of data.

## Step by step with code snippets

### 1. Set the address and page size

```python
API = "https://api.fda.gov/device/event.json"
PAGE = 1000  # openFDA's maximum page size
```

`API` is the web address for device adverse event reports. openFDA hands over at most 1,000 reports per request, so larger downloads have to be fetched a page at a time.

### 2. Trim each report down to what we need (`slim`)

A raw report has more than 80 fields, most of them addresses and administrative codes. This function keeps nine.

```python
narrative = " ".join(
    t["text"].strip()
    for t in report.get("mdr_text", [])
    if t.get("text_type_code") == NARRATIVE_TYPE and t.get("text")
)
if not narrative:
    return None
```

A report's text blocks live in a list called `mdr_text`. This looks through that list, keeps only the blocks labelled "Description of Event or Problem", and joins them into one piece of text. If a report has no such text, the function returns `None`, which means "skip this one": a report with no narrative has nothing to search.

```python
device = (report.get("device") or [{}])[0]
return {
    "report_number": report.get("report_number", ""),
    "date_received": report.get("date_received", ""),
    "event_type": report.get("event_type", ""),
    "brand_name": device.get("brand_name", ""),
    ...
    "narrative": narrative,
}
```

A report can list more than one device; this takes the first. It then builds a small record holding the report number (used later for citations), the date, the event type (malfunction, injury or death), the device details, and the narrative. Writing `.get("field", "")` means a missing field becomes an empty value instead of crashing the program.

### 3. Download one month of reports (`fetch_month`)

```python
last_day = calendar.monthrange(year, month)[1]
codes = "+".join(PRODUCT_CODES)
search = (
    f"device.device_report_product_code:({codes})"
    f"+AND+date_received:[{year}{month:02d}01+TO+{year}{month:02d}{last_day}]"
)
```

This builds the search request. In plain words it says: "reports whose product code is one of our four insulin pump codes, **and** which the FDA received between the first and last day of this month". `calendar.monthrange` supplies the last day so that February and 31-day months are both handled.

```python
while len(kept) < wanted:
    url = f"{API}?search={search}&limit={min(PAGE, wanted)}&skip={skip}"
    response = requests.get(url, timeout=60)
    if response.status_code == 404:  # openFDA's way of saying "no results"
        break
    response.raise_for_status()
    results = response.json()["results"]
    kept.extend(r for r in map(slim, results) if r)
    if len(results) < min(PAGE, wanted):
        break
    skip += len(results)
    time.sleep(0.3)
return kept[:wanted]
```

This loop keeps asking for pages until it has enough reports:

1. Build the web address. `limit` is how many reports to return and `skip` is how many to jump past, which is how you ask for page two, three, and so on.
2. Fetch it, waiting at most 60 seconds.
3. openFDA answers "404 not found" when a search matches nothing, so that is treated as "no more reports", not as an error. Any other failure stops the program with a clear message (`raise_for_status`).
4. Run every report through `slim` and keep the ones that had a narrative.
5. If the page came back short, there are no more reports, so stop.
6. Otherwise move `skip` forward, wait a third of a second to be polite to the FDA's servers, and go round again.

### 4. Loop over the year and save (`main`)

```python
parser.add_argument("--year", type=int, default=2025)
parser.add_argument("--per-month", type=int, default=250)
```

These define the two command-line options and their default values.

```python
seen: set[str] = set()
with RAW_REPORTS.open("w") as out:
    for month in range(1, 13):
        reports = fetch_month(args.year, month, args.per_month)
        new = [r for r in reports if r["report_number"] not in seen]
        seen.update(r["report_number"] for r in new)
        for report in new:
            out.write(json.dumps(report) + "\n")
        print(f"{args.year}-{month:02d}: {len(new)} reports")
```

For each of the twelve months it downloads the reports, drops any whose report number has already been saved (`seen` remembers them), and writes the rest to the file, one per line.

**Why month by month?** Insulin pumps generate over a thousand reports a day. Simply asking for "the latest 3,000" would return only two or three days of submissions. Taking 250 from every month gives a sample spread across the whole year.

## What to keep in mind

- Running it again overwrites `data/reports.jsonl`.
- Within a month, the reports are whichever ones openFDA returns first, not a random sample.

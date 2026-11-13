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

**In plain steps**

```
API  = the web address where the FDA publishes device event reports
PAGE = 1000   (the most reports the FDA will send in one go)
```

**Key elements**

| Code | What it means |
|---|---|
| `API` | Short for "application programming interface": a web address meant to be read by programs, not people |
| `# openFDA's maximum page size` | A comment. Everything after `#` on a line is a note for human readers; the computer skips it |

**Explanation**

`API` is the web address for device adverse event reports. openFDA hands over at most 1,000 reports per request, so larger downloads have to be fetched a page at a time.

### 2. Trim each report down to what we need (`slim`)

A raw report has more than 80 fields, most of them addresses and administrative codes. This function keeps nine.

#### 2a. Pull out the narrative

```python
narrative = " ".join(
    t["text"].strip()
    for t in report.get("mdr_text", [])
    if t.get("text_type_code") == NARRATIVE_TYPE and t.get("text")
)
if not narrative:
    return None
```

**In plain steps**

```
start with an empty pile of text pieces

for each text block in the report (if the report has none, do nothing):
    if the block is labelled "Description of Event or Problem"
       and the block actually contains some text:
           take the block's text
           trim the blank space off both ends
           add it to the pile

narrative = every piece in the pile, joined into one text with a space between each

if narrative is empty:
    stop here and hand back "nothing"
```

**Key elements**

| Code | What it means |
|---|---|
| `report.get("mdr_text", [])` | Look up the field called `mdr_text` in the report. If the report has no such field, use an empty list `[]` instead of crashing |
| `for t in ...` | Go through the text blocks one at a time. While working on a block, call it `t` |
| `t["text"]` | From block `t`, take the value stored under the label `text`: the words themselves |
| `.strip()` | Remove spaces and line breaks from the start and end of the text |
| `t.get("text_type_code")` | The block's label, saying what kind of text it is |
| `== NARRATIVE_TYPE` | "Is it equal to the label we want?" Two equals signs ask a question |
| `and t.get("text")` | "...and is there any text at all?" Empty text counts as "no" |
| `" ".join(...)` | Glue all the pieces into a single text, putting a space (`" "`) between each |
| `if not narrative:` | "If the narrative is empty". Empty text counts as "not" |
| `return None` | Finish immediately and hand back `None`, Python's word for "nothing" |

Note that Python lets you write the action first and the loop after it, which is why `t["text"].strip()` appears above `for t in ...`. Read it bottom-up: *for* each block, *if* it qualifies, *take* its trimmed text.

**Explanation**

A report's text blocks live in a list called `mdr_text`. This looks through that list, keeps only the blocks labelled "Description of Event or Problem", and joins them into one piece of text. If a report has no such text, the function returns `None`, which means "skip this one": a report with no narrative has nothing to search.

#### 2b. Build the slim record

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

**In plain steps**

```
device = the first device listed in the report
         (if no device is listed, use a blank record instead)

hand back a new record with these fields:
    report_number = the report's number        (blank if missing)
    date_received = the date the FDA got it    (blank if missing)
    event_type    = malfunction, injury, death (blank if missing)
    brand_name    = the device's brand name    (blank if missing)
    ...and a few more device fields...
    narrative     = the text gathered in step 2a
```

**Key elements**

| Code | What it means |
|---|---|
| `report.get("device")` | Look up the list of devices in the report |
| `or [{}]` | "If that turned up nothing, use this instead": a list holding one blank record |
| `[0]` | Take the first item. Python counts from 0, so `[0]` is first and `[1]` is second |
| `return { ... }` | Hand back a dictionary: a record of labelled values |
| `"report_number": ...` | One field of the record. Label on the left of the colon, value on the right |
| `report.get("report_number", "")` | Look up `report_number`. If it is missing, use empty text `""` |
| `device.get("brand_name", "")` | The same kind of lookup, but in the device record instead of the whole report |
| `...` | Not real code. It marks lines left out of this snippet to keep it short |

**Explanation**

A report can list more than one device; this takes the first. It then builds a small record holding the report number (used later for citations), the date, the event type (malfunction, injury or death), the device details, and the narrative. Writing `.get("field", "")` means a missing field becomes an empty value instead of crashing the program.

### 3. Download one month of reports (`fetch_month`)

#### 3a. Write the search request

```python
last_day = calendar.monthrange(year, month)[1]
codes = "+".join(PRODUCT_CODES)
search = (
    f"device.device_report_product_code:({codes})"
    f"+AND+date_received:[{year}{month:02d}01+TO+{year}{month:02d}{last_day}]"
)
```

**In plain steps**

```
last_day = how many days this month has          (for March 2025: 31)
codes    = the four product codes joined by "+"   ("LZG+QFG+OZP+OZO")

search   = "product code is one of (LZG+QFG+OZP+OZO)
            AND date received is between 20250301 and 20250331"
```

For March 2025 the finished `search` text is:

```
device.device_report_product_code:(LZG+QFG+OZP+OZO)+AND+date_received:[20250301+TO+20250331]
```

**Key elements**

| Code | What it means |
|---|---|
| `calendar.monthrange(year, month)` | Ask Python's calendar for facts about a month. It answers with two numbers: the weekday the month starts on, and how many days it has |
| `[1]` | Take the second of those two numbers: the number of days |
| `"+".join(PRODUCT_CODES)` | Glue the four codes together with a `+` between each |
| `f"..."` | Text with blanks to fill in. The `f` in front switches this on |
| `{codes}` | A blank. It is replaced by whatever `codes` holds |
| `{month:02d}` | A blank with a format: write the month as two digits, so 3 becomes `03` |
| `( ... )` around the two lines | Lets one long piece of text be written across two lines. Python joins them |

**Explanation**

This builds the search request. In plain words it says: "reports whose product code is one of our four insulin pump codes, **and** which the FDA received between the first and last day of this month". `calendar.monthrange` supplies the last day so that February and 31-day months are both handled.

#### 3b. Fetch pages until there are enough

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

**In plain steps**

```
keep going while we have fewer reports than we want:
    build the web address: the search, how many to send, how many to skip
    fetch that address (give up after 60 seconds)

    if the FDA answers "nothing found":
        stop looping
    if the FDA answers with any other error:
        stop the whole program and show the error

    results = the list of reports in the FDA's answer
    trim each report with slim, and keep the ones that had a narrative

    if the FDA sent fewer reports than we asked for:
        stop looping (there are no more)

    remember to skip past these reports next time
    wait 0.3 seconds

hand back the reports kept, cut down to the number wanted
```

**Key elements**

| Code | What it means |
|---|---|
| `while len(kept) < wanted:` | Repeat the indented lines for as long as the count of kept reports is less than the number wanted |
| `len(kept)` | How many items are in the list `kept` |
| `min(PAGE, wanted)` | Whichever of the two numbers is smaller |
| `?search=...&limit=...&skip=...` | The options added to the end of a web address. `?` starts them and `&` separates them |
| `requests.get(url, timeout=60)` | Fetch that web address, like a browser loading a page. Stop waiting after 60 seconds |
| `response.status_code` | A number every web server sends back. 200 means success; 404 means "not found" |
| `break` | Leave the loop straight away |
| `response.raise_for_status()` | If the server reported an error, stop the program and show it |
| `response.json()` | Read the server's answer as structured data, not plain text |
| `["results"]` | From that data, take the part labelled `results` |
| `map(slim, results)` | Run `slim` on every report in the list |
| `kept.extend(...)` | Add all of those to the end of the `kept` list |
| `... for r in ... if r` | Keep only the ones that are not "nothing" |
| `skip += len(results)` | Increase `skip` by the number of reports just received |
| `time.sleep(0.3)` | Pause for 0.3 seconds |
| `kept[:wanted]` | The first `wanted` items of the list, in case slightly too many were collected |

**Explanation**

This loop keeps asking for pages until it has enough reports:

1. Build the web address. `limit` is how many reports to return and `skip` is how many to jump past, which is how you ask for page two, three, and so on.
2. Fetch it, waiting at most 60 seconds.
3. openFDA answers "404 not found" when a search matches nothing, so that is treated as "no more reports", not as an error. Any other failure stops the program with a clear message (`raise_for_status`).
4. Run every report through `slim` and keep the ones that had a narrative.
5. If the page came back short, there are no more reports, so stop.
6. Otherwise move `skip` forward, wait a third of a second to be polite to the FDA's servers, and go round again.

### 4. Loop over the year and save (`main`)

#### 4a. Read the command-line options

```python
parser.add_argument("--year", type=int, default=2025)
parser.add_argument("--per-month", type=int, default=250)
```

**In plain steps**

```
accept an option called --year      (a whole number; use 2025 if not given)
accept an option called --per-month (a whole number; use 250 if not given)
```

**Key elements**

| Code | What it means |
|---|---|
| `parser` | The tool that reads what was typed after the program's name on the command line |
| `.add_argument("--year", ...)` | Teach the parser to recognise an option called `--year` |
| `type=int` | The value must be a whole number (`int` is short for *integer*) |
| `default=2025` | The value to use when the option is left out |

**Explanation**

These define the two command-line options and their default values.

#### 4b. Download each month and write it to the file

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

**In plain steps**

```
seen = an empty collection of report numbers already saved

open the output file for writing, and call it "out":
    for each month from 1 to 12:
        reports = download this month's reports
        new     = only the reports whose number is not already in "seen"
        add the numbers of the new reports to "seen"

        for each new report:
            turn the report into one line of text
            write that line to the file

        show a progress line, such as "2025-03: 250 reports"

(the file is closed automatically here)
```

**Key elements**

| Code | What it means |
|---|---|
| `set()` | An empty *set*: a collection that holds each item only once and can check very quickly whether it already has something |
| `seen: set[str]` | A note for human readers saying `seen` will hold pieces of text. It does not change what the program does |
| `with ... as out:` | Open the file, call it `out` for the indented lines, and close it automatically afterwards, even if something goes wrong |
| `.open("w")` | Open for **w**riting. This replaces whatever was in the file before |
| `range(1, 13)` | The numbers 1 up to, but not including, 13: that is, 1 to 12 |
| `args.year` | The value given for `--year` on the command line |
| `[r for r in reports if ...]` | Build a new list by going through `reports` and keeping only the ones that pass the test |
| `r["report_number"]` | The report's number, looked up by its label |
| `not in seen` | "Is not already in the `seen` collection" |
| `seen.update(...)` | Add several items to the set at once |
| `json.dumps(report)` | Turn the record into a single line of text in JSON, a standard format for storing data |
| `+ "\n"` | Add a line break to the end. `\n` is how a new line is written in code |
| `out.write(...)` | Write that text into the file |
| `print(...)` | Show a message on the screen |

**Explanation**

For each of the twelve months it downloads the reports, drops any whose report number has already been saved (`seen` remembers them), and writes the rest to the file, one per line.

**Why month by month?** Insulin pumps generate over a thousand reports a day. Simply asking for "the latest 3,000" would return only two or three days of submissions. Taking 250 from every month gives a sample spread across the whole year.

## What to keep in mind

- Running it again overwrites `data/reports.jsonl`.
- Within a month, the reports are whichever ones openFDA returns first, not a random sample.

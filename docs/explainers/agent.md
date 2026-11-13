# `maude_rag/agent.py`

## Purpose

This file answers questions that need several steps, such as "Compare the problems reported for Tandem and Insulet pumps, then check for recalls". No single earlier step can answer that. It needs examples from the reports (search), perhaps some counts (SQL), and recall records, which are not in the reports at all.

It does this with an *agent*. In the earlier steps, the code fixes the order of work: retrieve, then answer; or write a query, run it, then explain. In an agent, the LLM is given a set of *tools* and decides for itself which tools to call, with what inputs, in what order, and when it has enough to answer. A *tool* is an ordinary Python function the LLM is allowed to ask for. The LLM never runs code itself: it replies "please run `check_recalls` with firm = Tandem", the program runs the function, and the result is sent back for the LLM to read.

The agent has three tools:

- **`search_reports`:** find report excerpts by meaning and keywords (steps 1 and 2).
- **`run_sql`:** run a read-only counting query on the reports database (step 3).
- **`check_recalls`:** look up FDA recalls of insulin pumps, live from the openFDA website.

It completes step 5 of the roadmap. The router ([router.md](router.md)) sends questions here when it chooses the `agent` route; the file can also be run directly.

```bash
# Needs ANTHROPIC_API_KEY to be set
python -m maude_rag.agent "Compare the problems reported for Tandem and Insulet pumps, then check for recalls"

# Through the router, which may send the question here
python -m maude_rag.router "Have there been any FDA recalls of Omnipod pods?"
```

Both commands call the Anthropic API. The agent has not yet been run against the real API, so this explainer contains no agent transcripts or answers. The tools themselves are plain Python and do not need the API; the outputs shown below come from running the tools directly.

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `argparse` | Built into Python | Reads the question from the command line |
| `json` | Built into Python | Turns query results and tool inputs into text |
| `requests` | Installed package | Fetches recall records from the openFDA website |
| `anthropic.beta_tool` | Installed package (Anthropic's Python SDK) | Turns a Python function into a tool the LLM can call |
| `llm.py` | This project | Supplies `client` (the connection to the API) and `FALLBACK` (retry on a fallback model if the request is declined) |
| `config.py` | This project | Supplies the model name, the round limit, the four insulin pump product codes and the openFDA recall address |
| `ask.py` | This project | Supplies `retrieve` and `filters_to_where` for `search_reports` |
| `sql.py` | This project | Supplies the read-only `run_sql` and `schema_notes`, the description of the database |

It needs `data/chroma` (built by `index.py`), `data/reports.db` (built by `python -m maude_rag.sql --build`), an internet connection for the recall lookup, and an Anthropic API key in the `ANTHROPIC_API_KEY` environment variable.

## Step by step with code snippets

### 1. The standing instructions (`SYSTEM`)

```python
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
```

**In plain steps**

```
SYSTEM = instructions telling the LLM:
    its job, and the three tools it has
    to plan briefly, use the tools, then answer
    to cite report numbers and recall event numbers
    the limits of the data, to be stated where they matter:
        the reports are a sample, not every report
        reports are unverified and do not prove the device caused the event
        counts are not rates
        recalls are a separate database and may not line up with the sample
    a blank, {schema}, to be filled with the database description
```

**Key elements**

| Code | What it means |
|---|---|
| `"""..."""` | Text that runs over several lines |
| `\` at the end of a line | "This sentence continues on the next line." No line break goes into the text |
| `{schema}` | A blank. In step 8a, `SYSTEM.format(schema=...)` fills it with the database description |

**Explanation**

The limits are the same ones the earlier steps put in their prompts, plus one new one about recalls. The recall data comes from a different FDA database. A recall can concern a device model, or a year, that has no reports in the 3,000-report sample, and a report in the sample is not evidence that a recall applies to it.

The `{schema}` blank is filled with `schema_notes()` from `sql.py`: the table layouts, plus real values such as the most common manufacturer spellings and problem names. The query writer in `sql.py` is given the same description, so `run_sql` queries are written with the same knowledge.

### 2. Build the recall address (`recall_url`)

```python
def recall_url(firm: str = "", limit: int = 100) -> str:
    """openFDA query for insulin pump recalls, newest first, optionally for one firm."""
    codes = "+".join(f"product_code:{c}" for c in PRODUCT_CODES)
    search = f"({codes})"
    if firm:
        # Built by hand because openFDA needs literal "+" between words and terms.
        search += f'+AND+recalling_firm:"{"+".join(firm.split())}"'
    return f"{RECALL_API}?search={search}&sort=event_date_initiated:desc&limit={limit}"
```

**In plain steps**

```
to build the recall address:
    codes = "product_code:LZG+product_code:QFG+product_code:OZP+product_code:OZO"
            (any of the four insulin pump product codes)
    search = those codes, in brackets
    if a firm name was given:
        add "+AND+recalling_firm:" and the firm name in quotes, with "+" between its words
    the address = the openFDA recall address
                  + the search
                  + "newest first"
                  + "at most 100 records"
```

**Key elements**

| Code | What it means |
|---|---|
| `firm: str = ""` | An input called `firm`, which is text. If none is given, it is empty |
| `limit: int = 100` | An input called `limit`, a whole number, 100 unless another is given |
| `"+".join(...)` | Join several pieces of text into one, with `+` between them |
| `for c in PRODUCT_CODES` | Go through the four product codes in `config.py`: LZG, QFG, OZP and OZO |
| `firm.split()` | Split the firm name into words at the spaces |
| `sort=event_date_initiated:desc` | Sort by the date the recall started, newest (`desc`, descending) first |

**Explanation**

The address is assembled by hand rather than handed to `requests` as a list of options. openFDA's search language uses a literal `+` between terms, where a space would normally go. If `requests` built the address itself, it would encode each `+` as `%2B`, and openFDA would read it differently. Building the text directly keeps the `+` signs as they are.

Limiting the search to the four product codes keeps the recalls to insulin pumps, matching the products the reports were downloaded for. 100 records are fetched because openFDA keeps one record per recalled *product*, so a single recall event can fill many records; step 3 reduces them to one entry per event. Running it gives:

```
>>> recall_url('Tandem Diabetes')
https://api.fda.gov/device/recall.json?search=(product_code:LZG+product_code:QFG+product_code:OZP+product_code:OZO)+AND+recalling_firm:"Tandem+Diabetes"&sort=event_date_initiated:desc&limit=100
```

### 3. Reduce recall records to one per event (`summarise_recalls`)

```python
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
```

**In plain steps**

```
to summarise recall records:
    events = an empty record book, keyed by recall event number
    for each record (newest first):
        if its event number is not in the book yet: add it
        (later records for the same event are ignored)
    for each of the first 10 events:
        write: event number, status, start date, firm, product code
               the first 200 characters of the product description
               the first 400 characters of the reason for recall
               the root cause
        (a missing or empty field is written as blank, not an error)
    if there were more than 10 events:
        add "(At least N older recall events not shown.)"
    hand back all the entries, separated by blank lines
```

**Key elements**

| Code | What it means |
|---|---|
| `events.setdefault(key, r)` | Store `r` under this key only if nothing is stored there yet |
| `r.get("res_event_number")` | The record's recall event number, or `None` if it has none |
| `lambda field, n: ...` | A one-line function with no name, stored as `text` and set up afresh for each event `r`. `text('reason_for_recall', 400)` gives the first 400 characters of that field for the current event |
| `(r.get(field) or "")` | The field's value, or empty text if it is missing or empty. This avoids an error when openFDA leaves a field out |
| `list(events.values())[:max_events]` | The first 10 stored events. Records arrive newest first, so these are the 10 newest events |
| `x if condition else ""` | The "not shown" note only when some events were left out |

**Explanation**

openFDA's recall database has one record per recalled product, and one recall event (one company action, with one event number) can cover many products. Without this step the LLM would read the same recall several times and might count it as several recalls. Keeping only the first record per event number gives one entry each. The entry shows the product code and description of that first record only; other products in the same event are not listed.

The "older recall events not shown" note tells the LLM that the list is not complete. It counts only events within the 100 records fetched, so the real number can be higher; that is why it says "at least".

### 4. Print a preview of each tool result (`show`, `SHOW_STEPS`)

```python
def show(tool: str, result: str) -> str:
    """Print a short preview of what a tool returned, so each step can be checked."""
    if SHOW_STEPS:
        print(f"   {tool} returned: {result[:150].replace(chr(10), ' ')}...")
    return result


SHOW_STEPS = True
```

**In plain steps**

```
SHOW_STEPS = yes (a switch: print the steps or not)

to show a tool result:
    if the switch is on:
        print the tool name and the first 150 characters of its result, on one line
    hand back the result unchanged
```

**Key elements**

| Code | What it means |
|---|---|
| `result[:150]` | The first 150 characters |
| `.replace(chr(10), ' ')` | Replace every line break with a space, so the preview fits on one line. `chr(10)` is the line-break character |
| `SHOW_STEPS = True` | A setting for the whole file. Setting it to `False` turns off both the previews and the tool-call lines in step 8b |

**Explanation**

Every tool passes its result through `show` on the way back. The result reaches the LLM unchanged; the preview is for the person watching. Together with the printed tool calls (step 8b), it shows what the LLM asked for and what it got back.

### 5. Tool 1: search the reports (`search_reports`)

```python
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
```

**In plain steps**

```
(mark this function as a tool the LLM may call)

to search the reports, given what to look for and optional filters:
    turn the filters into a database condition, as the command line does
        (empty text or 0 means "no filter")
    if a brand or manufacturer name matches nothing:
        hand back advice as text: try a shorter name, or put the name in the query
    hits = the top 8 chunks, by hybrid search (roadmap step 2)
    hand back one paragraph per chunk:
        [report number] brand, event type, date received: the chunk's text
    if there were no chunks: hand back "No matching reports."
    (either way, print a preview first)
```

**Key elements**

| Code | What it means |
|---|---|
| `@beta_tool` | A label placed on the function below it. It turns the function into a tool: it reads the function's name, inputs and description, and builds the form the LLM sees |
| `"""..."""` under `def` | The function's *docstring*: its description. `@beta_tool` copies the first paragraph into the tool's description, and each line under `Args:` into the description of that input |
| `query: str` | An input that is text and must be given |
| `event_type: str = ""`, `since: int = 0` | Inputs that may be left out; they are then empty or 0 |
| `event_type or None` | The value if it has one; otherwise `None` ("no filter"). `0` and `""` both count as "no value" |
| `show("search_reports", ...)` | Print a preview (step 4) and hand the text back |
| `"\n\n".join(...)` | Join the excerpts into one text, with a blank line between each |
| `... or "No matching reports."` | If the joined text is empty, use this message instead |

**Explanation**

The docstring is not a comment for programmers here; it is the instruction the LLM reads. `@beta_tool` turns the function's name, inputs, types and docstring into a description the LLM is sent with every request. Running `search_reports.to_dict()` on an earlier version of this tool (before the date inputs were added) produced, shortened:

```
name:        search_reports
description: Search adverse event report narratives by meaning and keywords. Returns up to 8 excerpts.
inputs:      query (text, required): What to look for, in plain words.
             event_type (text, default ""): Optional: Malfunction, Injury or Death.
             brand (text, default ""): Optional: part of a brand name, e.g. 780G or Omnipod.
             manufacturer (text, default ""): Optional: part of a company name, e.g. Tandem.
```

`since` and `until` are added the same way, as whole numbers with a default of 0. Changing the wording of the docstring changes how the LLM uses the tool.

The tool reuses steps 1 and 2 unchanged: the same `filters_to_where` and the same `retrieve`, with the same five filters the command line offers. Each excerpt starts with its report number in square brackets, the same form the LLM is told to cite.

A name that matches nothing is returned as text, not raised as an error, and the text says what to do next. The LLM can retry with a shorter name, or drop the filter and put the name in the search words. Running the tool with a made-up brand prints:

```
   search_reports returned: No brand or manufacturer contains that text. Try a shorter part of the name, or leave it empty and put the name in the query instead....
```

### 6. Tool 2: run a counting query (`run_sql`)

```python
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
```

**In plain steps**

```
(mark this function as a tool the LLM may call)

to run a query written by the LLM:
    run it with the read-only runner from roadmap step 3 (sql.py)
    hand back the columns, rows, and "was it cut off?" as text
    if anything goes wrong:
        hand back "Query failed:" and the error, so the LLM can correct the query
    (either way, print a preview first)
```

**Key elements**

| Code | What it means |
|---|---|
| `from .sql import run_sql as run` | Bring in `run_sql` from `sql.py`, renamed `run` here so it does not clash with this tool, which has the same name |
| `json.dumps(...)` | Turn the result into JSON text, the format the LLM is sent |
| `except Exception as e:` | Catch any error at all |

**Explanation**

This is a thin wrapper around the query runner from roadmap step 3 (`sql.py`), so the same safety rules apply: only queries starting with `SELECT` or `WITH` are accepted, the database is opened read-only, and at most 200 rows come back. The LLM writes the query itself, using the schema in its instructions.

In `sql.py`, a failed query gets one retry, written into the code. Here the LLM decides: the error comes back as text, and it can write a corrected query on its next round. Running the tool directly prints:

```
>>> run_sql.call({'sql': 'SELECT event_type, COUNT(*) FROM reports GROUP BY 1'})
   run_sql returned: {"columns": ["event_type", "COUNT(*)"], "rows": [["DEATH", 8], ["INJURY", 704], ["MALFUNCTION", 2272]], "truncated": false}...

>>> run_sql.call({'sql': 'DELETE FROM reports'})
   run_sql returned: Query failed: Only SELECT queries are allowed....
```

### 7. Tool 3: check for recalls (`check_recalls`)

```python
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
```

**In plain steps**

```
(mark this function as a tool the LLM may call)

to check recalls, optionally for one firm:
    fetch the recall address from step 2, waiting at most 60 seconds
    if openFDA answers "not found": hand back "No recalls found."
    if the website gave any other error, could not be reached,
    or sent back something that is not the expected data:
        hand back "Recall lookup failed:" and the reason, as text
    records = the list of recall records in the reply
    hand back one entry per recall event, up to 10 (see summarise_recalls above)
    (either way, print a preview first)
```

**Key elements**

| Code | What it means |
|---|---|
| `requests.get(address, timeout=60)` | Fetch a web address; give up after 60 seconds |
| `response.status_code == 404` | The website's reply code. 404 normally means "page not found"; openFDA uses it for "no records match" |
| `response.raise_for_status()` | Turn any other error reply from the website into a Python error |
| `response.json()["results"]` | Read the reply as data and take its list of records |
| `except (requests.RequestException, ValueError, KeyError) as e:` | Catch a network or website error, a reply that is not valid data (`ValueError`), or a reply with no `results` list (`KeyError`) |

**Explanation**

This is the only part of the project that reaches outside the downloaded data. It queries openFDA's device recall database live, each time it is called, so its answers can change from day to day. No key is needed for openFDA.

The firm filter matches part of the company name, so `"insulet"` finds "Insulet Corporation". Every failure is handed back as text, like the other tools' errors, so the agent can carry on and report that the lookup failed rather than stopping.

Running `check_recalls.call({'firm': 'insulet'})` on 13 November 2026 returned entries beginning (shortened):

```
Recall 99034 (Open, Classified), initiated 2026-05-20, Insulet Corporation, product code QFG.
Product: Omnipod 5 Pods. Includes the below Model/REF Numbers: ...
Reason: External soft cannula damage during manufacturing that results in insulin leaking around
the Pod instead of being delivered to the user ...
Root cause: Process design
...
(At least 3 older recall events not shown.)
```

With no firm given, the same day's result listed 10 events, from 2026-01-30 to 2026-09-23, then "(At least 47 older recall events not shown.)". Note the dates: these recalls are from 2026, while the report sample is from 2025. That is the mismatch the instructions in step 1 warn about.

### 8. Run the agent loop (`run_agent`)

#### 8a. Set up the tool runner

```python
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
```

**In plain steps**

```
TOOLS = the three tools

to run the agent on a question:
    set up a tool runner with:
        the model from config.py
        room for a long reply
        a limit of 10 rounds (AGENT_MAX_STEPS)
        the instructions, with the database description filled in
        the three tools
        the question
        the fallback setting from llm.py
```

**Key elements**

| Code | What it means |
|---|---|
| `TOOLS = [...]` | A list of the three tools. The runner sends their descriptions to the LLM with every request |
| `client()` | The connection to the Anthropic API, from `llm.py`. It reads the API key from the environment |
| `.beta.messages.tool_runner(...)` | The SDK's *tool runner*: a ready-made loop that handles the back and forth between the LLM and the tools |
| `max_iterations=AGENT_MAX_STEPS` | Stop after this many rounds, even if the LLM still wants more tools. `config.py` sets it to 10 |
| `SYSTEM.format(schema=schema_notes())` | Fill the `{schema}` blank in the instructions with the database description |
| `messages=[{"role": "user", "content": question}]` | The conversation so far: one message, from the user, holding the question |
| `**FALLBACK` | Copy in the fallback settings from `llm.py`: if the model declines, the API retries on a fallback model |

**Explanation**

Without a tool runner, the program would have to write this loop itself: send the question, read the reply, find any tool requests, run those functions, send the results back, and repeat. The *tool runner* in Anthropic's Python SDK does exactly that. The program only lists the tools and the limit.

Each round goes like this:

```
1. send the conversation so far (instructions, question, earlier tool results) to the LLM
2. the LLM replies with some text and, possibly, requests to run tools
3. if there are no tool requests: the LLM has finished; stop
4. otherwise: run each requested function with the inputs the LLM chose
5. add the results to the conversation, and go back to 1
```

`max_iterations` is a safety cap. Without it, an LLM that kept asking for tools would keep running up cost. One round can include several tool calls if the LLM asks for them at once, so the cap is on rounds, not on individual tool calls; `config.py` describes `AGENT_MAX_STEPS` the same way.

#### 8b. Watch the rounds and print each tool call

```python
    final = None
    for message in runner:  # one message per model turn
        final = message
        if SHOW_STEPS:
            for block in message.content:
                if block.type == "tool_use":
                    print(f"-> {block.name}({json.dumps(block.input)})")
```

**In plain steps**

```
final = nothing yet
for each reply the LLM gives (the runner runs the tools in between):
    remember it as the latest reply
    if steps are being shown:
        for each part of the reply:
            if that part is a tool request:
                print "->", the tool's name, and the inputs the LLM chose
```

**Key elements**

| Code | What it means |
|---|---|
| `for message in runner:` | Each time round, the runner hands over the LLM's next reply. Running the tools happens inside the runner, between replies |
| `message.content` | A reply is made of parts, called *blocks*: some are text, some are tool requests |
| `block.type == "tool_use"` | "Is this part a request to run a tool?" |
| `block.name`, `block.input` | Which tool, and the inputs the LLM filled in |

**Explanation**

Printing every tool call is what makes the agent checkable. A reader sees, in order, each search, query and recall lookup the LLM chose, with the exact inputs, as lines of the form `-> run_sql({"sql": "SELECT ..."})`. When the runner then runs the tool, `show` (step 4) prints a preview of what came back. If an answer looks wrong, the two together show whether the LLM searched for the wrong thing, wrote a query that counted the wrong thing, or misread a correct result.

#### 8c. Turn the last reply into the answer

```python
    if final.stop_reason == "refusal":
        return "The model declined to answer this question."
    text = "".join(block.text for block in final.content if block.type == "text")
    if final.stop_reason == "tool_use":  # stopped by the round limit, not by choice
        text += f"\n\n(Stopped after {AGENT_MAX_STEPS} rounds of tool calls; the answer may be incomplete.)"
    return text
```

**In plain steps**

```
if the last reply was a refusal:
    hand back "The model declined to answer this question."
text = all the text parts of the last reply, joined together
if the last reply was still asking for tools:
    (so the loop ended because of the round limit, not because the LLM was done)
    add a note: "Stopped after 10 rounds of tool calls; the answer may be incomplete."
hand back the text
```

**Key elements**

| Code | What it means |
|---|---|
| `final.stop_reason` | Why the LLM stopped writing its last reply: `"end_turn"` (finished), `"tool_use"` (wants a tool run), `"refusal"` (declined), and others |
| `"".join(...)` | Join the text parts into one piece of text |
| `text += ...` | Add more text to the end of `text` |

**Explanation**

The final answer is the text of the last reply. Two cases need care.

- **Refusal.** If the model declines (after the fallback model has also had a chance), a clear message is returned instead of an empty answer. This matches how `ask_claude` in `llm.py` handles refusals elsewhere.
- **Round limit.** If the last reply was still asking for a tool, the LLM did not choose to stop; the runner stopped it. Whatever text it wrote is returned, with a note saying it may be incomplete, so a cut-off answer is not mistaken for a finished one.

### 9. Read the command line (`main`)

`main` reads the question, runs `run_agent`, and prints the answer. Tool calls and result previews are printed along the way because `SHOW_STEPS` is on. There are no other options.

## What to keep in mind

- **Nothing that calls the Anthropic API has been run yet.** No agent transcripts or answers have been observed. The tools have been run on their own (the outputs above), but how the LLM uses them is untested.
- **The fallback settings passed to the tool runner are unverified.** `**FALLBACK` adds a beta flag and a `fallbacks` option to the tool runner's requests. Whether the API accepts them there will only be known on the first live run.
- **There is no test set for the agent.** The routing score checks that multi-step questions are *sent* to the agent, not that the agent answers them well. Until there is one, judge it by reading the printed tool calls and previews.
- **The order of steps is not fixed.** The same question can lead to different tool calls on different runs, so answers can differ.
- **Recalls are a separate FDA database.** They are fetched live, may cover other years or other device models than the 2025 report sample, and can change from day to day. A recall and a report about the same brand are not linked by anything in the data.
- **Only the 10 newest recall events are shown**, out of the 100 newest product records. Older events are counted in the "not shown" note only if they fall within those 100 records; anything older is not seen unless the LLM narrows the search by firm.
- **Each recall entry describes one product.** When an event covers several products, only the first record's product code and description are shown.
- **Previews are cut to 150 characters.** They show that a tool returned something sensible, not the full result. To check a figure in the answer, rerun the printed query or search by hand.
- **Cost grows with every round.** Each round re-sends the whole conversation so far, including all earlier tool results.

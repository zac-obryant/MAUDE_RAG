# `maude_rag/router.py`

## Purpose

This file decides *how* to answer a question before answering it. It asks the LLM to read the question and pick one of three routes, then hands the question to the matching part of the project:

- **search:** the answer comes from reading what reports say ("What do reports say about pumps getting wet?"). This uses the retrieve-then-answer pipeline from steps 1 and 2 ([ask.md](ask.md)).
- **sql:** the answer is a number or a ranking ("How many death reports were there per manufacturer?"). This uses the database query from step 3 (`sql.py`).
- **agent:** the question needs several steps, or a source other than the reports ("Compare Tandem and Insulet, then check for recalls"). This uses the agent from step 5 ([agent.md](agent.md)).

It completes step 4 of the roadmap.

**Why routing is needed.** Each method is good at one kind of question and poor at the others. Search shows 8 report excerpts, so it can describe problems but cannot count: it never sees the other 2,900 reports. A database query can count every report but cannot read a narrative and say what went wrong. A question like "compare X and Y, then check for recalls" needs both, plus a source outside the reports, and the order of the steps depends on what each step finds. Sending every question down one path would answer some questions badly.

**Adaptive RAG.** *Adaptive RAG* is the name for this pattern: instead of running the same retrieve-then-answer pipeline for every question, a first step looks at the question and chooses how much machinery it needs. A simple question gets a simple path; a harder one gets a more involved path. Here the first step is a single, cheap LLM call that returns a decision, and plain Python code acts on that decision.

```bash
# Route and answer: needs ANTHROPIC_API_KEY to be set
python -m maude_rag.router "What do reports say about pumps getting wet?"
python -m maude_rag.router "How many death reports were there per manufacturer?"

# Show only the decision, without answering
python -m maude_rag.router --route-only "Compare Tandem and Insulet, then check for recalls"

# Measure how often the router picks the expected route
python -m maude_rag.evaluate_llm --suite routing -v
```

Every command above calls the Anthropic API. The router has not yet been run against the real API, so this explainer describes what the code is built to do, not observed decisions.

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `argparse` | Built into Python | Reads the question and the `--route-only` option from the command line |
| `llm.py` | This project | Supplies `ask_claude`, the one place the project calls Claude, and `Declined`, the error raised when the model declines to answer |
| `ask.py` | This project | Supplies `retrieve`, `filters_to_where` and `answer` for the search route |
| `sql.py` | This project | Supplies `ask_sql` and `print_table` for the sql route |
| `agent.py` | This project | Supplies `run_agent` for the agent route |

The search route needs `data/chroma` (built by `index.py`). The sql route needs `data/reports.db` (built by `python -m maude_rag.sql --build`). All routes need an Anthropic API key in the `ANTHROPIC_API_KEY` environment variable.

## Step by step with code snippets

### 1. The routes and the instructions for the LLM

```python
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
```

**In plain steps**

```
ROUTES = the three allowed answers: search, sql, agent

SYSTEM = instructions telling the LLM:
    its job is to pick one of three methods
    pick "search" for "what do the reports say" questions
    pick "sql" for "how many / which is most common" questions
    pick "agent" for multi-step questions, comparisons, or anything about recalls
    also pull out any filters the question states outright
    write "" (empty text) or 0 for a filter the question does not state
```

**Key elements**

| Code | What it means |
|---|---|
| `ROUTES = [...]` | A list of the three route names. It is used again in the schema in step 2, so the names are written only once |
| `"""..."""` | Triple quotation marks hold text that runs over several lines |
| `\` at the end of a line | "This sentence continues on the next line." No line break goes into the text |
| `SYSTEM` | The *system prompt*: standing instructions sent with the question |

**Explanation**

The instructions describe each route by the *kind of answer* the question wants (descriptions, numbers, or several steps), not by keywords. "Anything about recalls" goes to the agent because recalls are not in the reports at all; only the agent has a tool that looks them up.

The last paragraph asks for a second job in the same call: pull out filters. "What happened in death reports for Omnipod in March?" states an event type, a brand and a date range. Pulling them out here means the search route can narrow the search the same way `--event-type`, `--brand` and `--since` do on the command line.

### 2. The shape the answer must take (`SCHEMA`)

```python
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
```

**In plain steps**

```
the answer must be a record with exactly three fields:
    route   = one of: search, sql, agent         (nothing else allowed)
    reason  = a short sentence of text
    filters = a record with exactly five fields:
        event_type   = one of: "", Malfunction, Injury, Death
        brand        = text
        manufacturer = text
        since        = a whole number (a date written YYYYMMDD)
        until        = a whole number
no field may be missing, and no extra fields are allowed
```

**Key elements**

| Code | What it means |
|---|---|
| `SCHEMA = {...}` | A *JSON schema*: a written description of the exact shape a piece of data must have, like a form with fixed fields and allowed values |
| `"type": "object"` | The answer is a record with named fields (a dictionary) |
| `"enum": ROUTES` | *Enum* (short for enumeration): the value must be one of the items in this list, and nothing else |
| `"type": "integer"` | A whole number |
| `"required": [...]` | These fields must always be present |
| `"additionalProperties": False` | No fields other than the ones listed are allowed |
| `"description": "..."` | A hint the LLM reads when filling in that field |

**Explanation**

This schema turns the LLM's answer from free text into a filled-in form. It is used for *structured output*: the API is told to produce an answer that matches the schema, and it constrains the model's writing so the answer is guaranteed to fit it. Without this, the model might reply "I think this is a counting question", which code cannot act on reliably. With it, `route` is always exactly `"search"`, `"sql"` or `"agent"`, so the code in step 6 can compare it directly.

Every filter is required, which means the model must fill all five even when the question mentions none. That is why the instructions say to use `""` or `0` for "not stated". Step 3 removes those blanks.

The guarantee covers the *shape* of the answer, not whether it is right. The schema can force the route to be one of three words; it cannot force it to be the best of the three.

### 3. Ask for the decision (`route`)

```python
def route(question: str) -> dict:
    """Ask the LLM which route fits. Returns route, reason, and the filters it stated."""
    decision = ask_claude(SYSTEM, question, schema=SCHEMA, effort="low")
    decision["filters"] = {k: v for k, v in decision["filters"].items() if v}  # drop "" and 0
    return decision
```

**In plain steps**

```
to route a question:
    send the instructions and the question to Claude
        asking for an answer shaped like SCHEMA
        at low effort (a quick decision, not deep thought)
    decision = the filled-in record that comes back
    keep only the filters that have a real value; drop every "" and 0
    hand back the decision
```

**Key elements**

| Code | What it means |
|---|---|
| `ask_claude(SYSTEM, question, schema=SCHEMA, effort="low")` | Send one prompt to Claude through `llm.py`. Passing `schema` makes it ask for structured output and hand back a dictionary instead of text |
| `effort="low"` | Tell the model to spend little thinking on this. Routing is a quick classification, so it does not need the effort used for writing answers |
| `{k: v for k, v in ... .items() if v}` | Build a new dictionary from the old one, keeping only the entries whose value is not empty. `""` and `0` both count as "empty" in Python, so both are dropped |
| `-> dict` | A note for human readers: this function hands back a dictionary |

**Explanation**

This is the whole router: one LLM call. `llm.py` adds the schema to the request, reads the reply, and turns it from JSON text into a Python dictionary. A decision for a counting question would look something like `{"route": "sql", "reason": "...", "filters": {}}` (an illustration of the shape, not an observed result).

Dropping the blanks matters because the filters go straight into `filters_to_where` from step 2. That function treats a missing filter as "no filter", which is what "not stated" should mean. A date of `0` passed through as `since=0` would also be skipped there, but dropping blanks here keeps the printed `Filters:` line limited to what the question actually said.

The router uses the same model as the rest of the project (`ANSWER_MODEL` in `config.py`), at low effort. It is "quick" in the sense of one short call, not a smaller model.

### 4. Answer by search (`answer_by_search`)

```python
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
```

**In plain steps**

```
to answer by search:
    try to turn the router's filters into a database condition
        (exactly as the command-line options are turned into one)
    if a brand or manufacturer name matches no report:
        say so
        remove the brand and manufacturer filters, keep the rest (event type, dates)
        turn what is left into a database condition
    hits = the top chunks for the question (hybrid search, step 2)
    print one line per chunk: which search found it, report number, brand, start of text
    if there are any hits: have the LLM write an answer from them, and print it
    otherwise: print "No matching reports."
```

**Key elements**

| Code | What it means |
|---|---|
| `from .ask import ...` | Bring in the search tools from `ask.py`. It is done inside the function so the search libraries load only when this route is chosen |
| `filters_to_where(**filters)` | `**` unpacks the dictionary into named inputs, so `{"brand": "omnipod"}` becomes `brand="omnipod"` |
| `try: ... except LookupError:` | Try the first part; if it fails with a "nothing found" error, run the second part instead of stopping |
| `{k: v for k, v in filters.items() if k not in (...)}` | A copy of the filters without the `brand` and `manufacturer` entries |
| `where = None` | No condition: search every report |
| `f"{h['found_by']:<7}"` | Put the value in the text, padded to 7 characters wide so the columns line up |
| `h['text'][:70]` | The first 70 characters of the chunk |
| `x if hits else y` | `x` when there are hits, `y` when there are none |

**Explanation**

This reuses steps 1 and 2 without changing them. The router only adds the filters it pulled out of the question.

The fallback handles a likely mistake. The LLM might guess a brand name that is not how MAUDE spells it, and `filters_to_where` raises a `LookupError` when a brand or manufacturer text matches no stored name. Rather than stop, it says so, drops the brand and manufacturer filters, and searches again with whatever is left. An event type or date range the router found is kept, so "Omnipodd deaths in March" still searches death reports from March, just across all brands.

### 5. Answer by SQL (`answer_by_sql`)

```python
def answer_by_sql(question: str) -> None:
    from .sql import ask_sql, print_table

    out = ask_sql(question)
    print(f"Query: {out['sql']}\n")
    print_table(out["columns"], out["rows"], out["truncated"])
    print("\n" + out["answer"])
```

**In plain steps**

```
to answer by SQL:
    have the LLM write a database query for the question, run it, and explain the result (step 3)
    print the query
    print the result table
    print the LLM's explanation
```

**Key elements**

| Code | What it means |
|---|---|
| `ask_sql(question)` | Step 3 in one call: write a query, run it read-only (retrying once if it fails), and explain the result |
| `out['sql']`, `out['answer']` | Look up the query and the explanation in the record `ask_sql` hands back |
| `\n` | A line break |

**Explanation**

This is a straight hand-off to step 3. The router's filters are not passed on: the query writer reads the question itself and puts any conditions into the query. Printing the query first lets a reader check what was actually counted before trusting the number.

### 6. Read the command line and dispatch (`main`)

```python
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
```

**In plain steps**

```
read the question, and whether --route-only was given

route the question
print the chosen route and the reason for it
if any filters were found: print them

if --route-only was given: stop here

if the route is search: answer by search, using the filters
otherwise if it is sql:  answer by SQL
otherwise (agent):       run the agent and print its answer

if the model declines at any point: print that it declined, instead of crashing
```

**Key elements**

| Code | What it means |
|---|---|
| `action="store_true"` | `--route-only` is a switch: present means yes, absent means no |
| `__doc__.splitlines()[0]` | The first line of the description at the top of the file, used as the help text |
| `elif` | "Otherwise, if": checked only when the line above was false |
| `else:` | Everything left over. The schema allows only three routes, so this can only be `agent` |
| `except Declined as e:` | Catch the "model declined" error from `llm.py` and print its message |

**Explanation**

The dispatch is three plain `if` lines. The LLM makes one decision; ordinary code carries it out. That split keeps the behaviour easy to follow: the only part that can vary between runs is the route and filters, and both are printed before anything else happens.

`--route-only` stops after the decision. It is the cheap way to check the router by hand, since the search, SQL and agent routes all make further LLM calls.

### 7. How the router is scored (`evaluate_llm.py --suite routing`)

The router's accuracy is measured by `python -m maude_rag.evaluate_llm --suite routing`, which is in a separate file. It calls `route` on three groups of questions and compares the chosen route with the expected one:

| Questions from | Expected route |
|---|---|
| `eval/questions.json` (the 20 retrieval test questions from step 1) | `search` |
| `eval/counting.json` (the 12 counting test questions from step 3) | `sql` |
| `eval/routing.json` (9 questions written for this step, such as "Have there been any FDA recalls of Omnipod pods?") | the route listed beside each one |

It prints the share routed as expected, and a breakdown of which route was chosen for each expected route, so a reader can see *which* mistakes happen (for example, counting questions sent to search). It scores the route only, not the extracted filters. It needs an API key and has not been run yet.

## What to keep in mind

- **Nothing in this file has been run against the real API yet.** No routing decisions have been observed, and the routing score does not exist yet.
- **A wrong route gives a confident wrong-shaped answer.** A counting question sent to search gets a description of 8 reports, not a count. Printing the route and reason first is the main defence; `--route-only` and the routing score are the ways to check it.
- **Some questions fit more than one route.** "What are the most common problems with Omnipod pods?" could be a count or a description. The expected routes in the test files reflect one person's judgement.
- **Filters are only used by the search route.** The sql and agent routes read the question again themselves.
- **A bad brand or manufacturer guess drops both name filters**, so the search then covers every brand within the remaining filters. The printed message says so, but the answer may then mix in other brands.
- **Filters are extracted but not scored.** A wrong date range or event type would narrow the search silently. The `Filters:` line is printed so it can be checked.
- **Each question costs at least two LLM calls:** one to route and at least one to answer. The agent route can make many more.

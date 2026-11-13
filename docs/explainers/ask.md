# `maude_rag/ask.py`

## Purpose

This file answers a question. It finds the report chunks most relevant to the question, hands them to an LLM, and asks it to write an answer based only on those chunks, citing the report numbers it used.

Since step 2 it finds chunks two ways, by meaning (vector search) and by exact words (keyword search, see [keyword.md](keyword.md)), and merges the results. Optional filters narrow the search to certain reports first, such as deaths only, or one brand, or one month.

This is the "retrieve, then generate" part that gives RAG its name, and the third step of the pipeline.

```bash
# Search only: no API key needed
python -m maude_rag.ask --retrieve-only "pump screen went blank"

# Search and answer: needs ANTHROPIC_API_KEY to be set
python -m maude_rag.ask "What problems are reported with infusion sets?"

# Filtered: only death reports received from June 2025 onward
python -m maude_rag.ask --retrieve-only --event-type Death --since 20250601 "occlusion"

# Compare search methods on the same question
python -m maude_rag.ask --retrieve-only --mode vector  "E-03 error"
python -m maude_rag.ask --retrieve-only --mode keyword "E-03 error"

# See which brand names the --brand filter accepts
python -m maude_rag.ask --values brand_name
```

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `argparse` | Built into Python | Reads the question and options from the command line |
| `json`, `collections.Counter` | Built into Python | Read the downloaded reports and count values for `--values` |
| `functools.cache` | Built into Python | Remembers a result so slow work is done only once |
| `chromadb` | Installed package | Opens the vector database built by `index.py` |
| `sentence_transformers` | Installed package | Turns the question into a vector |
| `llm.py` | This project | Sends the prompt to Claude and receives the answer (see [llm.md](llm.md)) |
| `config.py` | This project | Supplies model names, database location and the number of chunks to retrieve |
| `keyword.py` | This project | Keyword search and the rule that merges result lists |

It also needs the database in `data/chroma`, so `index.py` must have been run first. The answering step needs an Anthropic API key in the `ANTHROPIC_API_KEY` environment variable; the search step does not.

## Step by step with code snippets

### 1. Write the standing instructions for the LLM

```python
SYSTEM = """You answer questions about insulin pump adverse events using excerpts \
from FDA MAUDE reports.

Use only the excerpts provided. Cite the report number in square brackets after \
each claim, like [1234567-2025-00012]. If the excerpts do not answer the question, \
say so rather than drawing on outside knowledge.

MAUDE is a passive reporting system: reports are unverified, can be duplicated, \
and do not establish that the device caused the event. The excerpts are a small \
sample, so describe what the reports say and do not estimate how common a problem is."""
```

**In plain steps**

```
SYSTEM = a block of instructions, in ordinary English, telling the LLM:
    what its job is
    to use only the excerpts it is given, and to cite report numbers
    to say so when the excerpts do not contain the answer
    what the limits of MAUDE data are
```

**Key elements**

| Code | What it means |
|---|---|
| `"""..."""` | Triple quotation marks hold text that runs over several lines |
| `\` at the end of a line | "This sentence continues on the next line." It keeps the code tidy without putting a line break in the text itself |
| A blank line inside the text | A real paragraph break that the LLM will see |
| `SYSTEM` | The name this text is stored under. It is sent to the LLM as the *system prompt* in step 5 |

**Explanation**

This is the system prompt: instructions that apply to every question. It does three jobs.

- **Keeps the answer grounded.** "Use only the excerpts" and "say so" if they do not contain the answer stop the model filling gaps from its general knowledge.
- **Makes the answer checkable.** Citing a report number after each claim lets a reader look up the original report.
- **Explains the data's limits.** MAUDE reports are unverified and are not a count of how often something happens, so the model is told not to present them that way.

### 2. Load the model and database once

```python
@cache
def _embedder() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)


@cache
def _collection():
    return chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION)
```

**In plain steps**

```
to get the embedder:
    the first time: load the embedding model, remember it, hand it back
    every later time: hand back the one already loaded

to get the collection:
    the first time: open the database, find our collection, remember it, hand it back
    every later time: hand back the one already opened
```

**Key elements**

| Code | What it means |
|---|---|
| `@cache` | A label placed on the function below it. It means "remember the answer after the first run and reuse it" |
| `def _embedder():` | Define a function called `_embedder` that takes no inputs |
| `_` at the start of a name | A convention meaning "internal helper": used inside this file, not meant to be called from elsewhere |
| `-> SentenceTransformer` | A note for human readers saying what kind of thing the function hands back. It does not change behaviour |
| `SentenceTransformer(EMBEDDING_MODEL)` | Load the embedding model named in the settings |
| `chromadb.PersistentClient(path=...)` | Open the database saved on disk |
| `.get_collection(COLLECTION)` | Fetch the existing collection by name. Unlike `create_collection` in `index.py`, this fails if it does not exist yet |

**Explanation**

Loading the embedding model takes a few seconds. `@cache` makes each function do its work the first time it is called and hand back the saved result every time after. Asking many questions in one run therefore loads the model only once.

### 3. Turn the filters into a database condition (`where_clause`, `matching`, `filters_to_where`)

#### 3a. Build the condition (`where_clause`)

```python
def where_clause(event_type=None, brands=None, manufacturers=None, since=None, until=None):
    conditions = []
    if event_type:
        conditions.append({"event_type": event_type.upper()})
    if brands is not None:
        conditions.append({"brand_name": {"$in": brands}})
    if manufacturers is not None:
        conditions.append({"manufacturer": {"$in": manufacturers}})
    if since:
        conditions.append({"date_received": {"$gte": since}})
    if until:
        conditions.append({"date_received": {"$lte": until}})
    if len(conditions) > 1:
        return {"$and": conditions}
    return conditions[0] if conditions else None
```

**In plain steps**

```
to build the condition from whichever filters were given:
    start an empty list of conditions
    if an event type was given:     add "event type must equal it" (in capitals)
    if a list of brands was given:  add "brand must be one of these"
    if a list of manufacturers was given: add "manufacturer must be one of these"
    if a start date was given:      add "date received must be on or after it"
    if an end date was given:       add "date received must be on or before it"

    if there are several conditions: hand back "all of these must hold"
    if there is one: hand back just that one
    if there are none: hand back nothing (no filter)
```

**Key elements**

| Code | What it means |
|---|---|
| `event_type=None` | An optional input. If it is not given, it is `None`, and `if event_type:` skips it |
| `.append(...)` | Add an item to the end of a list |
| `{"event_type": "DEATH"}` | The database's way of writing "event_type equals DEATH" |
| `{"$in": [...]}` | "Is one of these values" |
| `"$gte"`, `"$lte"` | "Greater than or equal to" and "less than or equal to" |
| `{"$and": [...]}` | "Every condition in this list must hold." The database requires this wrapper when there is more than one |

**Explanation**

The database stores each chunk with its report's metadata (see [index.md](index.md)), so it can skip non-matching chunks before ranking anything. This is called *pre-filtering*. It matters because filtering *after* search would leave fewer than eight results, or none, when the filter is strict.

Dates are written as numbers, such as `20250601`, which is why `index.py` stores them as numbers: only numbers can be compared with "on or after".

#### 3b. Expand partial names (`matching`, `filters_to_where`)

```python
def matching(field, text):
    return sorted({v for v, _ in values(field, top=None) if text.upper() in v})


def filters_to_where(event_type=None, brand=None, manufacturer=None, since=None, until=None):
    brands = matching("brand_name", brand) if brand else None
    manufacturers = matching("manufacturer", manufacturer) if manufacturer else None
    if brands == [] or manufacturers == []:
        raise LookupError("No brand or manufacturer contains that text. ...")
    return where_clause(event_type, brands, manufacturers, since, until)
```

**In plain steps**

```
to find the full names matching some typed text:
    go through every distinct value of the field in the downloaded reports
    keep those that contain the text (ignoring capitals), in alphabetical order

to turn the typed filters into a database condition:
    if a brand was typed: brands = every full brand name containing it
    if a manufacturer was typed: manufacturers = every full name containing it
    if either list came out empty: stop with a message saying so
    build the condition with where_clause (step 3a)
```

**Key elements**

| Code | What it means |
|---|---|
| `{v for v, _ in ...}` | Collect the values into a set. `_` is a name for a part that is not needed (here, the count) |
| `top=None` | Ask `values` for every value, not just the 25 most common |
| `raise LookupError(...)` | Stop and report a problem. Whoever called the function decides what to do with it |

**Explanation**

Brand and manufacturer names in MAUDE are long and inconsistent, and the database can only match whole values. Typing `--brand 780g` matches nine stored brand names, from `MINIMED 780G US SYSTEM BLE CONNECT 3.0 MG/DL` to `PUMP MMT-1884L MM780G BLE 3.0 MG/ML`, and `--manufacturer "beta bionics"` matches four spellings of the same company. `filters_to_where` is used by both `main` and the evaluation script ([evaluate.md](evaluate.md)), so filters behave the same everywhere.

### 4. Find the best chunks (`retrieve`)

```python
def retrieve(question, k=TOP_K, where=None, mode="hybrid"):
    found = {}
    rankings = []

    if mode in ("vector", "hybrid"):
        vector = _embedder().encode([question], normalize_embeddings=True)
        hits = _collection().query(query_embeddings=vector.tolist(), n_results=k, where=where)
        for id_, text, distance, metadata in zip(
            hits["ids"][0], hits["documents"][0], hits["distances"][0], hits["metadatas"][0]
        ):
            found[id_] = {"text": text, "similarity": 1 - distance, "found_by": "vector", **metadata}
        rankings.append(hits["ids"][0])

    if mode in ("keyword", "hybrid"):
        pool = _collection().get(where=where, include=["documents", "metadatas"])
        scores = bm25(question, pool["documents"])
        top = [i for i in sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:k] if scores[i] > 0]
        for i in top:
            id_ = pool["ids"][i]
            if id_ in found:
                found[id_]["found_by"] = "both"
            else:
                found[id_] = {"text": pool["documents"][i], "similarity": None, "found_by": "keyword",
                              **pool["metadatas"][i]}
        rankings.append([pool["ids"][i] for i in top])

    return [found[id_] for id_ in rrf(*rankings)[:k]]
```

**In plain steps**

```
to retrieve for a question (8 results, no filter, both searches, unless told otherwise):
    found    = an empty record of every chunk either search turns up
    rankings = an empty list of ranked results

    if vector search is on:
        turn the question into a vector
        ask the database for the 8 closest chunks that pass the filter
        for each result: record its text, similarity, metadata, and "found by vector"
        keep the order as one ranking

    if keyword search is on:
        pool = every chunk that passes the filter
        score every chunk in the pool with BM25
        top  = the 8 highest-scoring chunks, dropping any that scored 0
        for each of them:
            if vector search already found it: mark it "found by both"
            otherwise: record it, marked "found by keyword"
        keep the order as another ranking

    merge the rankings and hand back the top 8 records
```

**Key elements**

| Code | What it means |
|---|---|
| `mode in ("vector", "hybrid")` | "Is the mode one of these two?" |
| `where=where` | Pass the filter from step 3 to the database |
| `hits["ids"]` | Each chunk's unique label, such as `2032227-2025-146042#0`. It is how the same chunk is recognised in both result lists |
| `_collection().get(...)` | Fetch chunks without ranking them; here, every chunk that passes the filter |
| `sorted(range(len(scores)), key=scores.__getitem__, reverse=True)` | List the chunk positions from highest score to lowest |
| `[:k]` | Keep the first 8 |
| `if scores[i] > 0` | Drop chunks that share no words with the question |
| `"similarity": None` | Keyword-only hits have no similarity score, because vector search did not look at them |
| `rrf(*rankings)` | Merge the rankings (see [keyword.md](keyword.md)) |

**Explanation**

Step 1 used vector search alone. It finds chunks with similar meaning, but it handles exact terms such as error codes and model numbers loosely. Keyword search is the reverse: precise on exact words, blind to synonyms. Running both and merging them, called *hybrid search*, covers both weaknesses.

`--mode vector` reproduces step 1 exactly, so the two can be compared on the same question. The `found_by` label printed next to each result shows which search contributed it.

### 5. Assemble the prompt (`build_prompt`)

```python
def build_prompt(question, hits):
    excerpts = "\n\n".join(
        f'<report number="{h["report_number"]}" received="{h["date_received"]}" '
        f'brand="{h["brand_name"]}" event_type="{h["event_type"]}">\n{h["text"]}\n</report>'
        for h in hits
    )
    return f"<reports>\n{excerpts}\n</reports>\n\nQuestion: {question}"
```

**In plain steps**

```
to build the prompt from a question and the retrieved chunks:
    for each retrieved chunk:
        write an opening tag carrying its report number, date, brand and event type
        write the chunk's text on the next line
        write a closing tag on the line after

    excerpts = all of those blocks, with a blank line between each

    hand back: an opening <reports> tag,
               the excerpts,
               a closing </reports> tag,
               a blank line,
               "Question: " followed by the question
```

**Key elements**

| Code | What it means |
|---|---|
| `for h in hits` | Go through the retrieved chunks one at a time, calling the current one `h` (short for "hit") |
| `h["report_number"]` | The report number of this chunk, looked up by its label |
| `f'...{h["text"]}...'` | Text with blanks. Single quotes are used on the outside so that double quotes can appear inside |
| `<report ...>` and `</report>` | Tags: a labelled opening and closing marker around a block of text. They are part of the prompt, not Python |
| `\n` | A line break |
| `"\n\n".join(...)` | Glue the blocks together with two line breaks, that is, one blank line, between each |
| `return f"..."` | Hand back the finished prompt text |

**Explanation**

Each retrieved chunk is wrapped in a labelled tag, and the question is placed at the end. The result looks like this:

```
<reports>
<report number="2032227-2025-146042" received="20250611" brand="MINIMED 780G" event_type="Malfunction">
IT WAS REPORTED THAT THE PUMP WENT BLANK SCREEN...
</report>

...seven more...
</reports>

Question: Why do pump screens go blank?
```

The tags make it unambiguous where one report ends and the next begins, and they put the report number right beside the text so the model can cite it.

### 6. Ask the LLM (`answer`)

```python
def answer(question, hits):
    try:
        return ask_claude(SYSTEM, build_prompt(question, hits))
    except Declined as e:
        return str(e)
```

**In plain steps**

```
to answer a question using the retrieved chunks:
    send the standing instructions (step 1) and the prompt (step 5) to the LLM
    hand back its written answer

    if the LLM declines to answer:
        hand back a short notice saying so instead
```

**Key elements**

| Code | What it means |
|---|---|
| `ask_claude(...)` | The project's one function for calling the LLM, in `llm.py` |
| `try:` ... `except Declined as e:` | Attempt the call; if it reports that the model declined, use the message instead of crashing |
| `str(e)` | The message carried by the error, as text |

**Explanation**

Until step 3, this function talked to the Anthropic service directly. Steps 3 to 5 call the LLM too, so that code moved into one shared function, `ask_claude` in [llm.py](llm.py). It picks the model, asks the service to retry on a fallback model if the first one declines, and raises `Declined` if the request is still declined. Keeping it in one place means every step behaves the same way.

### 7. Tie it together (`main`)

```python
parser.add_argument("question", nargs="?")
parser.add_argument("-k", type=int, default=TOP_K, help="number of chunks to retrieve")
parser.add_argument("--retrieve-only", action="store_true", help="skip the LLM step")
parser.add_argument("--mode", choices=["hybrid", "vector", "keyword"], default="hybrid")
filters = parser.add_argument_group("filters")
filters.add_argument("--event-type", help="e.g. Malfunction, Injury, Death")
filters.add_argument("--brand", help="any part of a brand name, e.g. 780g (see --values brand_name)")
filters.add_argument("--manufacturer", help="any part of a manufacturer name (see --values manufacturer)")
filters.add_argument("--since", type=int, metavar="YYYYMMDD", help="received on or after")
filters.add_argument("--until", type=int, metavar="YYYYMMDD", help="received on or before")
parser.add_argument("--values", metavar="FIELD", help="list common values of a field and exit")
args = parser.parse_args()

if args.values:
    for value, count in values(args.values):
        print(f"{count:6d}  {value}")
    return
if not args.question:
    parser.error("a question is required")

try:
    where = filters_to_where(args.event_type, args.brand, args.manufacturer, args.since, args.until)
except LookupError as e:
    print(e)
    return
hits = retrieve(args.question, args.k, where, args.mode)
if not hits:
    print("No matching reports. Loosen the filters or check spellings with --values.")
    return
print("Retrieved:")
for h in hits:
    score = f"{h['similarity']:.2f}" if h["similarity"] is not None else "  - "
    print(f"  {score}  {h['found_by']:<7}  {h['report_number']}  {h['brand_name']}: {h['text'][:80]}...")
if not args.retrieve_only:
    print("\n" + answer(args.question, hits))
```

**In plain steps**

```
accept a question (optional, because --values does not need one)
accept -k, --retrieve-only, --mode, and the five filter options
accept --values FIELD
read what was actually typed

if --values was typed:
    show the most common values of that field, with counts, and stop
if no question was typed:
    stop with an error

build the filter condition (step 3b); if a name matches nothing, say so and stop
hits = retrieve the best chunks (step 4)
if nothing matched: say so and stop

show the heading "Retrieved:"
for each chunk:
    show its similarity (or "-" if keyword search alone found it),
    which search found it, its report number, brand, and first 80 characters

if --retrieve-only was not typed:
    ask the LLM for an answer and show it
```

**Key elements**

| Code | What it means |
|---|---|
| `nargs="?"` | The question may be left out. It is then `None` |
| `choices=[...]` | Only these values are accepted for `--mode` |
| `add_argument_group("filters")` | Groups the filter options under their own heading in `--help` |
| `metavar="YYYYMMDD"` | How the expected value is shown in `--help` |
| `values(field)` | Counts each value of a field across the downloaded reports, most common first |
| `parser.error(...)` | Stop and print a usage message |
| `try:` ... `except LookupError as e:` | Attempt the indented lines; if they report a `LookupError`, print its message instead of crashing |
| `{h['found_by']:<7}` | Show the label padded to 7 characters, so the columns line up |

**Explanation**

The filters exist because many questions are really about a subset: "what do *death* reports say about occlusions", or "what was reported about *this brand* in *June*". `--values` lists the stored names with their report counts, which helps when choosing what to type for `--brand` or `--manufacturer`.

### 8. One answer as a machine-readable record (`as_json`, `--json`)

```python
# MAUDE report numbers: 1234567-2025-00012, 1234567890-2025-000123, or MW1234567.
REPORT_NUMBER = re.compile(r"\b(?:\d{7,10}-\d{4}-\d{5,6}|MW\d{7})\b")
```

```python
def as_json(question: str, k: int, mode: str) -> dict:
    """One answer in the AIPV harness contract: answer, cited_ids, retrieved_ids, config."""
    hits = retrieve(question, k, None, mode)
    text = answer(question, hits) if hits else ""
    return {
        "answer": text,
        "cited_ids": list(dict.fromkeys(REPORT_NUMBER.findall(text))),
        "retrieved_ids": list(dict.fromkeys(h["report_number"] for h in hits)),
        "config": {
            **LAST_CALL,
            "system_prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest()[:16],
            "embedding_model": EMBEDDING_MODEL,
            "retrieval_mode": mode,
            "top_k": k,
            "index_chunks": _collection().count(),
        },
    }
```

```python
    if args.json:
        print(json.dumps(as_json(args.question or sys.stdin.read().strip(), args.k, args.mode)))
        return
```

```bash
python -m maude_rag.ask --json "What problems are reported with infusion sets?"
echo "What problems are reported with infusion sets?" | python -m maude_rag.ask --json
```

**In plain steps**

```
REPORT_NUMBER = a text pattern that recognises MAUDE report numbers

to produce one answer as a record:
    hits = retrieve the best chunks for the question (no filters)
    text = the LLM's answer, or empty text if nothing was retrieved

    hand back a record with:
        answer        = the answer text
        cited_ids     = every report number that appears in the answer, each once, in order
        retrieved_ids = every report number that was retrieved, each once, in order
        config        = the settings this answer was produced under:
            the model asked for, the model that answered, and the effort (from LAST_CALL)
            a short fingerprint of the standing instructions (SYSTEM)
            the embedding model, the search mode, and how many chunks were retrieved
            how many chunks the database holds

in main, if --json was typed:
    take the question from the command line, or else read it from the input
    print the record as JSON and stop
```

**Key elements**

| Code | What it means |
|---|---|
| `re.compile(r"...")` | Prepare a text pattern. This one matches the three shapes of MAUDE report number: digits-year-digits, or `MW` followed by seven digits |
| `retrieve(question, k, None, mode)` | Search as in step 4. `None` means no filters are applied |
| `REPORT_NUMBER.findall(text)` | Every piece of the answer that matches the pattern |
| `list(dict.fromkeys(...))` | Remove repeats while keeping the order |
| `**LAST_CALL` | Copy in the record of the last LLM call: `model_requested`, `model_served` and `effort` (see [llm.md](llm.md), step 1) |
| `hashlib.sha256(SYSTEM.encode()).hexdigest()[:16]` | A *hash*: a short code calculated from the text of the standing instructions. Any change to the text, even one character, gives a different code. The first 16 characters are kept |
| `_collection().count()` | The number of chunks in the vector database |
| `json.dumps(...)` | Write the record as JSON text |
| `sys.stdin.read().strip()` | Read the question from the command's input instead, for example from another program |

**Explanation**

This step was added for an "AI Process Validation" (AIPV) harness: a separate program that sends questions to this one and checks the answers. Such a program cannot read the normal printed output reliably, so `--json` prints one record in a fixed layout instead. The function's own description calls this layout the harness "contract".

Each part of the record lets the answer be checked or traced:

- **`cited_ids` and `retrieved_ids`** let a checker compare what the answer cites with what was actually retrieved. A cited report number that was never retrieved would mean the answer is citing something it was not given.
- **`config`** records what the answer depended on: which model was requested and which actually answered (they can differ when the fallback is used), the effort level, the standing instructions (by their hash), the embedding model, the search mode, the number of chunks retrieved, and the size of the database. If any of these changes between two runs, a difference in answers can be traced to it. The hash makes a change to the instructions visible without copying the whole text into every record.

## What to keep in mind

- The answer can only be as good as the eight chunks retrieved. If the right reports are not found, the model cannot use them.
- Vector search alone can confuse similar wording: a question about insulin *leaking* can return reports about insulin *not coming out*. Keyword search helps with exact terms, but only matches identical words. Neither is perfect, which is why `found_by` is shown.
- Brand and manufacturer filters match any part of the name, but not misspellings. A misspelt name returns nothing rather than a near match; use `--values` to check.
- Questions that need counting ("how many...") cannot be answered correctly from eight excerpts.

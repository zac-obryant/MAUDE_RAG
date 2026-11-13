# `maude_rag/ask.py`

## Purpose

This file answers a question. It finds the report chunks whose meaning is closest to the question, hands them to an LLM, and asks it to write an answer based only on those chunks, citing the report numbers it used.

This is the "retrieve, then generate" part that gives RAG its name, and the third step of the pipeline.

```bash
# Search only: no API key needed
python -m maude_rag.ask --retrieve-only "pump screen went blank"

# Search and answer: needs ANTHROPIC_API_KEY to be set
python -m maude_rag.ask "What problems are reported with infusion sets?"
```

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `argparse` | Built into Python | Reads the question and options from the command line |
| `functools.cache` | Built into Python | Remembers a result so slow work is done only once |
| `chromadb` | Installed package | Opens the vector database built by `index.py` |
| `sentence_transformers` | Installed package | Turns the question into a vector |
| `anthropic` | Installed package | Sends the prompt to Claude and receives the answer |
| `config.py` | This project | Supplies model names, database location and the number of chunks to retrieve |

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

### 3. Find the closest chunks (`retrieve`)

```python
def retrieve(question, k=TOP_K):
    vector = _embedder().encode([question], normalize_embeddings=True)
    hits = _collection().query(query_embeddings=vector.tolist(), n_results=k)
    return [
        {"text": text, "similarity": 1 - distance, **metadata}
        for text, distance, metadata in zip(
            hits["documents"][0], hits["distances"][0], hits["metadatas"][0]
        )
    ]
```

**In plain steps**

```
to retrieve for a question (asking for 8 results unless told otherwise):
    vector = turn the question into a list of numbers, using the embedding model
    hits   = ask the database for the 8 stored chunks closest to that vector

    the database answers with three lists: texts, distances, metadata

    for each result (taking one text, one distance, one metadata record together):
        build a record holding:
            the chunk's text
            similarity = 1 - distance
            every field from the metadata (report number, brand, date, ...)

    hand back the list of those records
```

**Key elements**

| Code | What it means |
|---|---|
| `_embedder()` | Get the embedding model from step 2 |
| `.encode([question], ...)` | Turn the question into a vector. The square brackets wrap the single question in a list, because the model expects a list of texts |
| `_collection()` | Get the database collection from step 2 |
| `.query(...)` | Ask the collection to search |
| `query_embeddings=vector.tolist()` | "Here is the vector to search with", converted to an ordinary list |
| `n_results=k` | "Send back this many matches" |
| `hits["documents"]` | The part of the answer holding the matching texts |
| `[0]` after it | The results for the first question. The database can search for several questions at once, so it answers with one list per question; we asked only one |
| `zip(a, b, c)` | Walk through three lists side by side, taking the first of each together, then the second of each, and so on |
| `for text, distance, metadata in ...` | Name the three items taken at each step |
| `1 - distance` | Turn distance into similarity. A distance of 0.24 becomes a similarity of 0.76 |
| `**metadata` | "Copy every field of the metadata record into this one", instead of writing each field out |

**Explanation**

1. Turn the question into a vector using the **same** embedding model that was used on the reports. This matters: vectors from different models cannot be compared.
2. Ask the database for the `k` stored vectors nearest to it (8 by default).
3. The database returns three parallel lists: texts, distances and metadata. `zip` walks through them together, and each result is tidied into one record.

The database reports *distance*, where 0 means identical. `1 - distance` flips that into *similarity*, where 1 means identical, which is easier to read. In practice a good match here scores about 0.70 to 0.80.

### 4. Assemble the prompt (`build_prompt`)

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

### 5. Ask the LLM (`answer`)

```python
def answer(question, hits):
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    response = client.beta.messages.create(
        model=ANSWER_MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_prompt(question, hits)}],
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        return "The model declined to answer this question."
    return "".join(block.text for block in response.content if block.type == "text")
```

**In plain steps**

```
to answer a question using the retrieved chunks:
    bring in the Anthropic toolkit
    client = open a connection to Anthropic, using the API key saved on this computer

    response = send a message to the model, including:
        which model to use
        the longest reply allowed
        the standing instructions from step 1
        one message from the "user": the prompt built in step 4
        a request to retry on another model if this one declines

    if the model declined to answer:
        hand back a short notice saying so

    otherwise:
        take every part of the reply that is text
        join them together
        hand that back as the answer
```

**Key elements**

| Code | What it means |
|---|---|
| `import anthropic` | Bring in Anthropic's toolkit for talking to Claude |
| `anthropic.Anthropic()` | Open a connection to the service. It finds your API key by itself, so the key is never written in the code |
| `client.beta.messages.create(...)` | Send a message and wait for the reply. `beta` is the part of the toolkit that offers newer features |
| `model=ANSWER_MODEL` | Which model should answer |
| `max_tokens=16000` | An upper limit on the reply's length. A *token* is a piece of a word; 16,000 tokens is many pages |
| `system=SYSTEM` | The standing instructions from step 1 |
| `messages=[{...}]` | The conversation so far, as a list. Here it holds one message |
| `"role": "user"` | Who the message is from. `user` means the person asking |
| `"content": build_prompt(...)` | What the message says: the prompt built in step 4 |
| `betas=[...]`, `fallbacks="default"` | Switch on the optional retry-on-another-model feature |
| `response.stop_reason` | Why the model stopped writing. `"refusal"` means it declined |
| `response.content` | The reply, delivered as a list of blocks |
| `block.type == "text"` | "Is this block ordinary text?" Some blocks hold other things, such as the model's reasoning |
| `"".join(...)` | Glue the text blocks together with nothing between them |

**Explanation**

- `import anthropic` sits inside the function so that search-only mode works even without that package configured.
- `anthropic.Anthropic()` creates the connection and picks up your API key from the environment, so the key never appears in the code.
- The request sends the model name, the standing instructions (`system`) and the assembled prompt as the user's message. `max_tokens` is an upper limit on the length of the reply.
- `betas` and `fallbacks` switch on an optional feature: if the model declines a request, the service automatically retries it on another model.
- If it is still declined, a plain message is returned instead of an empty answer.
- A reply arrives as a list of blocks, not all of which are text. The last line keeps the text blocks and joins them into the final answer.

### 6. Tie it together (`main`)

```python
parser.add_argument("question")
parser.add_argument("-k", type=int, default=TOP_K, help="number of chunks to retrieve")
parser.add_argument("--retrieve-only", action="store_true", help="skip the LLM step")
args = parser.parse_args()

hits = retrieve(args.question, args.k)
print("Retrieved:")
for h in hits:
    print(f"  {h['similarity']:.2f}  {h['report_number']}  {h['brand_name']}: {h['text'][:90]}...")
if not args.retrieve_only:
    print("\n" + answer(args.question, hits))
```

**In plain steps**

```
expect a question to be typed on the command line
accept an optional -k number             (use 8 if not given)
accept an optional --retrieve-only switch (off unless typed)
read what was actually typed

hits = retrieve the closest chunks for the question

show the heading "Retrieved:"
for each chunk:
    show its similarity score, report number, brand, and first 90 characters

if --retrieve-only was not typed:
    ask the LLM for an answer and show it
```

**Key elements**

| Code | What it means |
|---|---|
| `parser.add_argument("question")` | Expect one piece of text with no dashes in front: the question itself. It is required |
| `"-k"`, `"--retrieve-only"` | Options. A name starting with dashes is optional |
| `type=int` | The value must be a whole number |
| `default=TOP_K` | Use the setting from `config.py` when `-k` is not given |
| `help="..."` | The description shown when someone runs the program with `--help` |
| `action="store_true"` | This option is a switch. Typing it turns it on; it takes no value |
| `parser.parse_args()` | Read what was typed and store the results in `args` |
| `args.question`, `args.k` | The values that were typed |
| `{h['similarity']:.2f}` | A blank with a format: show the number with two decimal places, such as `0.76` |
| `h['text'][:90]` | A slice: the first 90 characters of the chunk's text |
| `if not args.retrieve_only:` | "If the switch is off" |
| `"\n" + answer(...)` | A blank line, followed by the answer from step 5 |

**Explanation**

It reads the question and options, retrieves the chunks, and prints each one's similarity score, report number, brand and first 90 characters. Seeing what was retrieved is the quickest way to tell whether a bad answer came from bad search or bad writing. Unless `--retrieve-only` was given, it then prints the LLM's answer.

## What to keep in mind

- The answer can only be as good as the eight chunks retrieved. If the right reports are not found, the model cannot use them.
- Search here is by meaning alone. A question about insulin *leaking* can return reports about insulin *not coming out*, because the wording is similar. Exact terms such as model numbers are also matched loosely. Step 2 of the roadmap addresses this.
- Questions that need counting ("how many...") cannot be answered correctly from eight excerpts.

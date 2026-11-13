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

It reads the question and options, retrieves the chunks, and prints each one's similarity score, report number, brand and first 90 characters. Seeing what was retrieved is the quickest way to tell whether a bad answer came from bad search or bad writing. Unless `--retrieve-only` was given, it then prints the LLM's answer.

## What to keep in mind

- The answer can only be as good as the eight chunks retrieved. If the right reports are not found, the model cannot use them.
- Search here is by meaning alone. A question about insulin *leaking* can return reports about insulin *not coming out*, because the wording is similar. Exact terms such as model numbers are also matched loosely. Step 2 of the roadmap addresses this.
- Questions that need counting ("how many...") cannot be answered correctly from eight excerpts.

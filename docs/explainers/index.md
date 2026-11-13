# `maude_rag/index.py`

## Purpose

This file makes the downloaded reports searchable by meaning. It cuts each narrative into chunks, turns every chunk into a vector (a list of numbers representing its meaning), and stores the vectors in a database built for finding similar ones.

It is the second step of the pipeline. Run it once after downloading, and again whenever the data or the chunking settings change:

```bash
python -m maude_rag.index
```

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `json` | Built into Python | Reads the saved reports back in |
| `chromadb` | Installed package | The vector database. It stores vectors and finds the nearest ones |
| `sentence_transformers` | Installed package | Loads and runs the embedding model |
| `config.py` | This project | Supplies file locations, the model name and chunk sizes |

It also needs `data/reports.jsonl` to exist, so `ingest.py` must have been run first. The first run downloads the embedding model (about 90 MB) from Hugging Face; after that it works offline.

## Step by step with code snippets

### 1. Cut long text into overlapping pieces (`chunk`)

```python
def chunk(text, size=CHUNK_WORDS, overlap=CHUNK_OVERLAP):
    words = text.split()
    if len(words) <= size:
        return [" ".join(words)]
    step = size - overlap
    return [" ".join(words[i : i + size]) for i in range(0, len(words) - overlap, step)]
```

**In plain steps**

```
to chunk a text (using 150 words per chunk and 30 words of overlap):
    words = the text cut up into separate words

    if there are 150 words or fewer:
        hand back the whole text as one chunk

    step = 150 - 30 = 120   (how far to move forward each time)

    for each starting position 0, 120, 240, ... :
        take the 150 words beginning at that position
        join them back into a piece of text
    hand back the list of those pieces
```

**Key elements**

| Code | What it means |
|---|---|
| `def chunk(...):` | Define a reusable set of steps and name it `chunk`. Other code can now run these steps by writing `chunk(some_text)` |
| `text` | The input: whatever text is handed to the function |
| `size=CHUNK_WORDS` | A second input with a default. If the caller does not say otherwise, `size` is 150 |
| `text.split()` | Cut the text into a list of words wherever there is a space. `"pump alarm sounded"` becomes `["pump", "alarm", "sounded"]` |
| `len(words)` | How many words are in the list |
| `<=` | "Less than or equal to" |
| `" ".join(words)` | The reverse of `split`: glue the words back into one text with a space between each |
| `[ ... ]` around it | Put that one text inside a list, because the function always hands back a list |
| `range(0, len(words) - overlap, step)` | A run of numbers starting at 0 and going up by `step` each time: 0, 120, 240, ... It stops before the end of the text |
| `for i in range(...)` | Do this once for each of those numbers, calling the current number `i` |
| `words[i : i + size]` | A slice: the words from position `i` up to position `i + size`. When `i` is 120, that is words 120 to 269 |

**Explanation**

- Split the text into words.
- If it is already 150 words or fewer, return it whole as a single chunk. Most narratives take this path.
- Otherwise slide a 150-word window along the text, moving forward 120 words each time (`step`). Because the window is wider than the step, each chunk begins with the last 30 words of the previous one.

Example with a 270-word narrative: chunk one is words 1–150, chunk two is words 121–270.

### 2. Load the reports and prepare three matching lists

```python
reports = [json.loads(line) for line in RAW_REPORTS.open()]
ids, texts, metadatas = [], [], []
for report in reports:
    for n, piece in enumerate(chunk(report["narrative"])):
        ids.append(f"{report['report_number']}#{n}")
        texts.append(piece)
        metadatas.append(
            {
                "report_number": report["report_number"],
                "date_received": int(report["date_received"] or 0),
                "event_type": report["event_type"].upper(),
                "brand_name": report["brand_name"].upper(),
                "manufacturer": report["manufacturer"].upper(),
                "product_code": report["product_code"],
            }
        )
```

**In plain steps**

```
reports = read the saved file, turning each line back into a report record

start three empty lists: ids, texts, metadatas

for each report:
    cut its narrative into chunks
    for each chunk (numbered 0, 1, 2, ...):
        add "<report number>#<chunk number>" to ids
        add the chunk's text to texts
        add a small record of facts about the report to metadatas
```

**Key elements**

| Code | What it means |
|---|---|
| `RAW_REPORTS.open()` | Open the saved reports file for reading |
| `for line in ...` | Go through the file one line at a time |
| `json.loads(line)` | Turn one line of JSON text back into a record. The reverse of `json.dumps` in `ingest.py` |
| `ids, texts, metadatas = [], [], []` | Create three empty lists in one line |
| `report["narrative"]` | The narrative text of this report, looked up by its label |
| `chunk(...)` | Run the function from step 1 |
| `enumerate(...)` | Hand out each item together with its position number, starting at 0 |
| `for n, piece in ...` | For each pair, call the position `n` and the chunk `piece` |
| `.append(...)` | Add one item to the end of a list |
| `f"{report['report_number']}#{n}"` | Text with two blanks: the report number, then a `#`, then the chunk's position. For example `2032227-2025-146042#0` |
| `{ "report_number": ..., ... }` | A dictionary: a small record of labelled facts |

**Explanation**

The database wants three things for every chunk, supplied as three lists in the same order:

- **an ID**: the report number plus the chunk's position, such as `2032227-2025-146042#0`. Every ID must be unique.
- **the text** of the chunk.
- **metadata**: facts about the report the chunk came from. These are stored next to the vector so that a search result can say which report, brand and date it belongs to, and, since step 2, so that searches can be filtered by them.

Two adjustments were added in step 2 to make filtering work. The date is stored as a number (`int(...)` turns the text `"20250314"` into the number 20250314), because only numbers can be compared with "on or after"; `or 0` stands in for a missing date. Event type, brand and manufacturer are stored in capitals (`.upper()`), so a filter matches however it is typed.

### 3. Turn every chunk into a vector

```python
model = SentenceTransformer(EMBEDDING_MODEL)
vectors = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=True)
```

**In plain steps**

```
model   = load the embedding model named in the settings
vectors = ask the model to turn every chunk into a list of 384 numbers,
          working through them 64 at a time,
          scaling every result to the same length,
          and showing a progress bar while it works
```

**Key elements**

| Code | What it means |
|---|---|
| `SentenceTransformer(...)` | Load an embedding model so it is ready to use. The first time, this downloads it |
| `model.encode(texts, ...)` | Ask the model to convert the texts into vectors. "Encode" here means "turn into numbers" |
| `batch_size=64` | Process 64 chunks at once. Bigger batches are faster but use more memory |
| `normalize_embeddings=True` | Scale every vector to length 1, so comparisons depend only on direction |
| `show_progress_bar=True` | Display a progress bar, since this step takes a while |
| `vectors` | The result: a grid of numbers with one row per chunk and 384 columns |

**Explanation**

- The first line loads the embedding model.
- The second runs every chunk through it, 64 at a time. Each chunk comes back as a list of 384 numbers.
- `normalize_embeddings=True` scales every vector to the same length. After that, comparing two vectors measures only the direction they point in, which is what captures similarity of meaning.

This is the slow part: about a minute for 3,000 reports on a laptop.

### 4. Create a fresh table in the database

```python
client = chromadb.PersistentClient(path=str(CHROMA_DIR))
if COLLECTION in [c.name for c in client.list_collections()]:
    client.delete_collection(COLLECTION)  # rebuild from scratch each run
collection = client.create_collection(COLLECTION, configuration={"hnsw": {"space": "cosine"}})
```

**In plain steps**

```
client = open the database stored in the data/chroma folder

if a collection with our name already exists in the database:
    delete it

collection = create a new, empty collection with our name,
             set up to compare vectors by cosine similarity
```

**Key elements**

| Code | What it means |
|---|---|
| `chromadb.PersistentClient(...)` | Open a Chroma database that is saved on disk. "Persistent" means it is still there after the program ends |
| `path=str(CHROMA_DIR)` | Where the database lives. `str(...)` converts the folder location into plain text, which Chroma expects |
| `client` | Our handle on the database. Every request to it goes through this |
| `client.list_collections()` | Ask the database for all the collections it holds |
| `[c.name for c in ...]` | Make a list of just their names |
| `COLLECTION in [...]` | "Is our collection's name in that list?" |
| `client.delete_collection(...)` | Remove that collection and everything in it |
| `client.create_collection(...)` | Make a new, empty collection |
| `configuration={...}` | Settings for the new collection, given as a dictionary |
| `"hnsw"` | The name of the indexing method Chroma uses to make searches fast |
| `"space": "cosine"` | Measure closeness between vectors using cosine similarity |

**Explanation**

- `PersistentClient` opens a database that lives in the `data/chroma` folder, so it survives after the program ends.
- If the collection already exists from an earlier run, it is deleted first. Rebuilding from scratch avoids stale or duplicated entries.
- `"space": "cosine"` tells the database to measure closeness by cosine similarity, the standard measure for text embeddings. `hnsw` is the name of the indexing method that makes searches fast.

### 5. Store everything, a thousand chunks at a time

```python
for start in range(0, len(ids), BATCH):
    end = start + BATCH
    collection.add(
        ids=ids[start:end],
        documents=texts[start:end],
        embeddings=vectors[start:end].tolist(),
        metadatas=metadatas[start:end],
    )
print(f"Indexed {collection.count()} chunks into {CHROMA_DIR}")
```

**In plain steps**

```
for each starting position 0, 1000, 2000, ... :
    end = start + 1000
    add to the collection, for chunks number start up to end:
        their IDs
        their texts
        their vectors
        their metadata

show how many chunks the collection now holds
```

**Key elements**

| Code | What it means |
|---|---|
| `range(0, len(ids), BATCH)` | The numbers 0, 1000, 2000, ... up to the total count of chunks. `BATCH` is 1000 |
| `ids[start:end]` | A slice: the IDs from position `start` up to, but not including, `end` |
| `collection.add(...)` | Store a batch of items in the collection |
| `documents=` | Chroma's word for the original texts |
| `embeddings=` | Chroma's word for the vectors |
| `.tolist()` | Convert the grid of numbers into ordinary Python lists, the form Chroma accepts |
| `collection.count()` | Ask the collection how many items it holds |
| `print(f"...")` | Show a message, with the count and folder filled into the blanks |

**Explanation**

The chunks are added in batches of 1,000 because the database limits how much it accepts in one go. Each batch hands over the IDs, texts, vectors and metadata together. The final line prints how many chunks ended up stored, as a check that nothing was lost.

### 6. Also build the counting database (step 3)

```python
build_database(reports)  # step 3: the same reports as a SQLite table, for counting
print(f"Built {DB_PATH}")
```

**In plain steps**

```
write the same reports into a database file (data/reports.db)
show where it was saved
```

**Key elements**

| Code | What it means |
|---|---|
| `build_database(reports)` | The `build` function from `sql.py`, given a clearer name where it is imported |

**Explanation**

Search cannot count, so step 3 keeps a second copy of the reports as a database table that can answer "how many" questions. Building it here means one command, `python -m maude_rag.index`, prepares everything. It takes under a second. See [sql.md](sql.md).

## What to keep in mind

- The vectors are supplied to Chroma directly instead of letting Chroma compute them. That keeps the embedding step visible and guarantees the same model is used here and in `ask.py`.
- If you change `EMBEDDING_MODEL`, `CHUNK_WORDS` or `CHUNK_OVERLAP`, run this file again. Vectors from different models cannot be compared with each other.

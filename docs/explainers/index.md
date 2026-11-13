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
                "date_received": report["date_received"],
                "event_type": report["event_type"],
                "brand_name": report["brand_name"],
                "manufacturer": report["manufacturer"],
                "product_code": report["product_code"],
            }
        )
```

The database wants three things for every chunk, supplied as three lists in the same order:

- **an ID**: the report number plus the chunk's position, such as `2032227-2025-146042#0`. Every ID must be unique.
- **the text** of the chunk.
- **metadata**: facts about the report the chunk came from. These are stored next to the vector so that a search result can say which report, brand and date it belongs to.

### 3. Turn every chunk into a vector

```python
model = SentenceTransformer(EMBEDDING_MODEL)
vectors = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=True)
```

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

The chunks are added in batches of 1,000 because the database limits how much it accepts in one go. Each batch hands over the IDs, texts, vectors and metadata together. The final line prints how many chunks ended up stored, as a check that nothing was lost.

## What to keep in mind

- The vectors are supplied to Chroma directly instead of letting Chroma compute them. That keeps the embedding step visible and guarantees the same model is used here and in `ask.py`.
- If you change `EMBEDDING_MODEL`, `CHUNK_WORDS` or `CHUNK_OVERLAP`, run this file again. Vectors from different models cannot be compared with each other.

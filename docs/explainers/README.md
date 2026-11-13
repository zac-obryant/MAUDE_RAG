# Plain-language explainers

One explainer per code file. Read them in this order, which is the order the pipeline runs in.

| # | File | What it does in one line | Explainer |
|---|---|---|---|
| 1 | `maude_rag/config.py` | Holds the settings every other file shares | [config.md](config.md) |
| 2 | `maude_rag/ingest.py` | Downloads the reports from the FDA | [ingest.md](ingest.md) |
| 3 | `maude_rag/index.py` | Turns the reports into searchable vectors | [index.md](index.md) |
| 4 | `maude_rag/ask.py` | Finds relevant reports and answers a question | [ask.md](ask.md) |
| 5 | `tests/test_pipeline.py` | Checks the small building blocks still work | [tests.md](tests.md) |

```
ingest.py            index.py                    ask.py
FDA website ──> data/reports.jsonl ──> data/chroma ──> answer with citations
                        (config.py supplies the settings to all three)
```

## The supporting files

- **`requirements.txt`** lists the outside packages the project needs, so `pip install -r requirements.txt` installs them all at once.
- **`.gitignore`** tells Git which files to leave out of the repository: the downloaded data, the virtual environment, and any file holding secret keys.
- **`maude_rag/__init__.py`** is empty. Its presence tells Python that the `maude_rag` folder is a package, which is what makes `python -m maude_rag.ingest` work.

## Words used throughout

| Word | Meaning |
|---|---|
| **Narrative** | The free-text description of what happened, written by whoever filed the report |
| **Chunk** | A piece of a narrative, short enough for the embedding model to read in full |
| **Embedding** / **vector** | A list of numbers that represents the meaning of a piece of text. Texts with similar meaning get similar numbers |
| **Embedding model** | The program that turns text into a vector |
| **Vector database** | A store that can quickly find the vectors closest to a given vector |
| **LLM** | Large language model: the program that writes the final answer (here, Claude) |
| **RAG** | Retrieval-augmented generation: look up relevant text first, then have the LLM answer from it |

# `maude_rag/config.py`

## Purpose

This file is the project's settings sheet. Every value that more than one file needs, or that you might want to change while experimenting, lives here. The other files import from it, so changing a setting in this one place changes it everywhere.

It contains no logic. Nothing happens when it runs; it only defines names.

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `pathlib.Path` | Built into Python | Describes file and folder locations in a way that works on Windows, Mac and Linux |

## Step by step with code snippets

### 1. Decide where files are stored

```python
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_REPORTS = DATA_DIR / "reports.jsonl"
CHROMA_DIR = DATA_DIR / "chroma"
COLLECTION = "insulin_pump_narratives"
```

- `__file__` is the location of `config.py` itself. Going up two folders (`.parent.parent`) reaches the project root, and `/ "data"` points at a `data` folder inside it. This means the paths are correct no matter which folder you run the code from.
- `RAW_REPORTS` is the file the downloaded reports are saved to.
- `CHROMA_DIR` is the folder the vector database keeps its files in.
- `COLLECTION` is the name of the table inside that database. A vector database calls its tables "collections".

### 2. List which devices count as insulin pumps

```python
PRODUCT_CODES = {
    "LZG": "Pump, Infusion, Insulin",
    "QFG": "Alternate Controller Enabled Insulin Infusion Pump",
    "OZP": "Automated Insulin Dosing Device System, Single Hormonal Control",
    "OZO": "Automated Insulin Dosing, Threshold Suspend",
}
```

The FDA gives every type of device a three-letter product code. There is no single code for "insulin pump": older pumps, modern pumps that take dosing commands from an app, and pumps that adjust insulin automatically each have their own. These four together cover the category. The text on the right is the FDA's official name for each code and is there for the reader's benefit.

### 3. Choose the embedding model and the chunk size

```python
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_WORDS = 150
CHUNK_OVERLAP = 30
```

- `EMBEDDING_MODEL` names the model that turns text into vectors. This one is free, small, and runs on an ordinary laptop.
- That model only reads roughly the first 190 words of any text and silently ignores the rest. So long narratives are cut into chunks of `CHUNK_WORDS` (150) words, comfortably under the limit.
- `CHUNK_OVERLAP` (30) means each chunk repeats the last 30 words of the one before it. Without this, a sentence that falls across a cut would be split in half and lose its meaning in both chunks.

### 4. Choose which part of a report to use

```python
NARRATIVE_TYPE = "Description of Event or Problem"
```

A MAUDE report can contain several blocks of text. This is the label of the block written by the reporter describing what happened. The other common block, the manufacturer's follow-up narrative, is mostly standard wording repeated across thousands of reports, so the baseline leaves it out.

### 5. Choose the answering model and how much evidence to give it

```python
ANSWER_MODEL = "claude-opus-5-5"
TOP_K = 8
```

- `ANSWER_MODEL` is the LLM that writes the final answer.
- `TOP_K` is how many chunks are retrieved and shown to that model for each question. Too few and it may miss relevant reports; too many and irrelevant ones crowd the prompt.

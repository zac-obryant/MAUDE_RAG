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

**In plain steps**

```
find where this file (config.py) sits on the computer
go up two folders, to the project's main folder
DATA_DIR    = the folder called "data" inside the main folder
RAW_REPORTS = the file called "reports.jsonl" inside DATA_DIR
CHROMA_DIR  = the folder called "chroma" inside DATA_DIR
COLLECTION  = the name "insulin_pump_narratives"
```

**Key elements**

| Code | What it means |
|---|---|
| `DATA_DIR = ...` | Store what is on the right under the name `DATA_DIR`. Names in capitals are, by convention, settings that never change while the program runs |
| `Path(...)` | Treat this as a file or folder location, not just text |
| `__file__` | A name Python fills in automatically with the location of the current file |
| `.resolve()` | Work out the full, exact location, starting from the top of the disk |
| `.parent` | The folder that contains this one. Written twice, it goes up two levels |
| `/ "data"` | "Then go into `data`". With locations, `/` joins folder names; it is not division here |
| `"reports.jsonl"` | A piece of text. Quotation marks tell Python to take the words literally |

**Explanation**

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

**In plain steps**

```
PRODUCT_CODES = a lookup table with four rows:
    code "LZG" -> "Pump, Infusion, Insulin"
    code "QFG" -> "Alternate Controller Enabled Insulin Infusion Pump"
    code "OZP" -> "Automated Insulin Dosing Device System, Single Hormonal Control"
    code "OZO" -> "Automated Insulin Dosing, Threshold Suspend"
```

**Key elements**

| Code | What it means |
|---|---|
| `{ ... }` | Curly brackets hold a *dictionary*: a lookup table of paired items |
| `"LZG": "Pump, ..."` | One row of the table. The part before the colon is the label (the *key*); the part after is what it stands for (the *value*) |
| `,` at the end of each row | Separates one row from the next |

**Explanation**

The FDA gives every type of device a three-letter product code. There is no single code for "insulin pump": older pumps, modern pumps that take dosing commands from an app, and pumps that adjust insulin automatically each have their own. These four together cover the category. The text on the right is the FDA's official name for each code and is there for the reader's benefit.

### 3. Choose the embedding model and the chunk size

```python
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_WORDS = 150
CHUNK_OVERLAP = 30
```

**In plain steps**

```
EMBEDDING_MODEL = the model named "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_WORDS     = 150   (how many words go in each chunk)
CHUNK_OVERLAP   = 30    (how many words each chunk repeats from the one before)
```

**Key elements**

| Code | What it means |
|---|---|
| `"sentence-transformers/all-MiniLM-L6-v2"` | The model's public name. The part before the slash is the group that published it; the part after is the model itself |
| `150`, `30` | Plain numbers. No quotation marks, so Python can do arithmetic with them |

**Explanation**

- `EMBEDDING_MODEL` names the model that turns text into vectors. This one is free, small, and runs on an ordinary laptop.
- That model only reads roughly the first 190 words of any text and silently ignores the rest. So long narratives are cut into chunks of `CHUNK_WORDS` (150) words, comfortably under the limit.
- `CHUNK_OVERLAP` (30) means each chunk repeats the last 30 words of the one before it. Without this, a sentence that falls across a cut would be split in half and lose its meaning in both chunks.

### 4. Choose which part of a report to use

```python
NARRATIVE_TYPE = "Description of Event or Problem"
```

**In plain steps**

```
NARRATIVE_TYPE = the label "Description of Event or Problem"
```

**Key elements**

| Code | What it means |
|---|---|
| `"Description of Event or Problem"` | The exact label the FDA puts on the reporter's text block. It has to match letter for letter, including capitals, or no text will be found |

**Explanation**

A MAUDE report can contain several blocks of text. This is the label of the block written by the reporter describing what happened. The other common block, the manufacturer's follow-up narrative, is mostly standard wording repeated across thousands of reports, so the baseline leaves it out.

### 5. Choose the answering model and how much evidence to give it

```python
ANSWER_MODEL = "claude-opus-5-5"
TOP_K = 8
```

**In plain steps**

```
ANSWER_MODEL = the model named "claude-opus-5-5"
TOP_K        = 8   (how many report excerpts to show the model per question)
```

**Key elements**

| Code | What it means |
|---|---|
| `"claude-opus-5-5"` | The identifier the Anthropic service uses for this model |
| `TOP_K` | A common name in search systems for "the top *k* results", where *k* is a number you choose |

**Explanation**

- `ANSWER_MODEL` is the LLM that writes the final answer.
- `TOP_K` is how many chunks are retrieved and shown to that model for each question. Too few and it may miss relevant reports; too many and irrelevant ones crowd the prompt.

# Plain-language explainers

One explainer per code file. Read them in this order, which is the order the pipeline runs in.

| # | File | What it does in one line | Explainer |
|---|---|---|---|
| 1 | `maude_rag/config.py` | Holds the settings every other file shares | [config.md](config.md) |
| 2 | `maude_rag/ingest.py` | Downloads the reports from the FDA | [ingest.md](ingest.md) |
| 3 | `maude_rag/index.py` | Turns the reports into searchable vectors | [index.md](index.md) |
| 4 | `maude_rag/keyword.py` | Keyword search, and merging it with vector search (step 2) | [keyword.md](keyword.md) |
| 5 | `maude_rag/ask.py` | Finds relevant reports and answers a question | [ask.md](ask.md) |
| 6 | `maude_rag/evaluate.py` | Scores the search against a fixed set of test questions | [evaluate.md](evaluate.md) |
| 7 | `tests/test_pipeline.py` | Checks the small building blocks still work | [tests.md](tests.md) |

```
ingest.py            index.py                    ask.py
FDA website ──> data/reports.jsonl ──> data/chroma ──> answer with citations
                        (config.py supplies the settings to all three)
```

## How each step is laid out

Every step in an explainer has the same four parts:

1. **The code snippet**, copied from the file.
2. **In plain steps:** the same logic written as pseudo code, which is ordinary English arranged like code. Indented lines belong to the line above them.
3. **Key elements:** a table translating each piece of Python in the snippet.
4. **Explanation:** why the step exists and what to notice about it.

## How to read the Python

These symbols appear in almost every snippet. Each explainer also defines them where they are used, so this table is a reference, not required reading.

| You see | It means |
|---|---|
| `name = value` | Store the value under that name so it can be used later. A single `=` means "store", not "equals" |
| `a == b` | "Is `a` equal to `b`?" A double `==` asks a question; the answer is yes or no |
| `"some text"` | A piece of text. Programmers call this a *string*. Single quotes `'...'` mean the same thing |
| `f"Hello {name}"` | Text with blanks. Whatever is inside `{ }` is replaced by its value |
| `[a, b, c]` | A *list*: several items kept in order |
| `{"label": value}` | A *dictionary*: a record of labelled values, like a form with named fields |
| `thing["label"]` | Look up the value stored under that label in a dictionary |
| `things[0]` | The first item of a list. Python counts from 0, so `[1]` is the second item |
| `things[2:5]` | A *slice*: items from position 2 up to, but not including, position 5 |
| `thing.action()` | Ask `thing` to do something. The brackets are what makes it happen |
| `action(input)` | Run an action on an input and get a result back |
| `def name(inputs):` | Define a reusable set of steps, called a *function*, with that name |
| `return value` | Finish the function and hand this value back to whoever asked |
| `for x in things:` | Repeat the indented lines once for each item, calling the current item `x` |
| `if condition:` | Only run the indented lines when the condition is true |
| `while condition:` | Keep repeating the indented lines for as long as the condition is true |
| `import name` | Bring in a toolkit someone else wrote so its tools can be used here |
| `# some words` | A comment: a note for human readers that the computer ignores |
| `None` | Python's word for "nothing" |
| `True` / `False` | Yes / no |

Indentation matters in Python. Lines pushed in to the right belong to the `for`, `if`, `while` or `def` line above them.

## The supporting files

- **`requirements.txt`** lists the outside packages the project needs, so `pip install -r requirements.txt` installs them all at once.
- **`.gitignore`** tells Git which files to leave out of the repository: the downloaded data, the virtual environment, and any file holding secret keys.
- **`eval/questions.json`** holds the test questions and which reports count as correct answers. It is described in [evaluate.md](evaluate.md).
- **`eval/results/`** holds a dated record of each evaluation run.
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
| **Keyword search** / **BM25** | Search by exact shared words, giving rare words more weight |
| **Hybrid search** | Running vector and keyword search together and merging the results |
| **Metadata filter** | A condition on report facts (event type, brand, date) applied before ranking |
| **Test set** | A fixed list of questions with known correct reports, used to score the search |
| **Hit rate**, **precision**, **MRR** | The three scores: did search find anything correct, what share was correct, and how high the first correct report ranked |

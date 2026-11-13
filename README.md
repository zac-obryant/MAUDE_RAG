# MAUDE RAG: Hybrid Search Procedure

| Field | Value |
|---|---|
| **Document title** | Building and Running Question Answering over FDA MAUDE Reports |
| **Document type** | Procedure |
| **Revision** | C |
| **Effective date** | 2026-11-13 |
| **Applies to** | Steps 1 and 2 of the project roadmap (see Section 9) |

> This is a learning project built in public. The document borrows the layout of a quality system procedure for clarity; it is not a controlled document and is not part of any certified quality management system.

---

## 1. Purpose

This procedure describes how to set up and run question answering over the FDA's [MAUDE](https://www.fda.gov/medical-devices/mandatory-reporting-requirements-manufacturers-importers-and-device-user-facilities/manufacturer-and-user-facility-device-experience-database-maude) database of medical device adverse event reports, using retrieval-augmented generation (RAG) with hybrid search and metadata filters. The project is built in public, one step at a time.

## 2. Scope

**In scope**

- About 3,000 insulin pump reports received by the FDA in 2025 (250 per month, spread across every day of the month; a few duplicates are dropped).
- The reporter's "Description of Event or Problem" text from each report.
- Downloading the reports, indexing them, and asking questions against them.
- Narrowing a search by event type, brand, manufacturer and date received.
- Scoring retrieval against a fixed test set of 20 questions.

**Out of scope**

- Other device types and other years.
- The manufacturer's follow-up narrative in each report.
- Later roadmap steps (Section 9), including questions that need counting.
- Scoring the quality of the written answers. Only retrieval is scored.

## 3. Definitions

| Term | Definition |
|---|---|
| **MAUDE** | Manufacturer and User Facility Device Experience: the FDA's database of medical device adverse event reports |
| **openFDA** | The FDA's free public data service, used here to download reports |
| **RAG** | Retrieval-augmented generation: look up relevant text first, then have an LLM answer from it |
| **Chunk** | A piece of a report narrative, short enough for the embedding model to read in full |
| **Embedding model** | A program that turns text into a list of numbers representing its meaning |
| **Vector DB** | A database that finds the stored texts closest in meaning to a query |
| **LLM** | Large language model: the program that writes the final answer |
| **BM25** | A keyword-scoring formula: ranks text by shared words, weighting rare words more |
| **Hybrid search** | Vector search and keyword search run together, with results merged by reciprocal rank fusion |
| **Metadata filter** | A condition on report facts, applied before results are ranked |
| **Test set** | A fixed list of questions, each with the reports that count as correct answers (`eval/questions.json`) |
| **Pooling** | Building a test set by reading the combined top results of every search method, so no method is favoured |
| **Hit rate** | The share of questions for which at least one correct report was retrieved |
| **Precision** | The share of retrieved reports that are correct, averaged over questions |
| **MRR** | Mean reciprocal rank: 1 if the first correct report ranks first, 1/2 if second, and so on, averaged over questions |

A fuller glossary is in [docs/explainers](docs/explainers/README.md).

## 4. Responsibilities

| Role | Responsibility |
|---|---|
| **User** | Runs this procedure and supplies their own Anthropic API key for the answering step |
| **Test set reviewer** | Checks each test question and its correct reports, then sets `"reviewed": true` |
| **Reader of an answer** | Interprets the output within the limits stated in Section 7 |

## 5. References

| Reference | Location |
|---|---|
| openFDA device event API | <https://open.fda.gov/apis/device/event/> |
| Chroma vector database | <https://www.trychroma.com/> |
| Plain-language walkthrough of each code file | [docs/explainers](docs/explainers/README.md) |

## 6. System Description

### 6.1 Process flow

```
Reports ─> chunk ─> embedding model ─> vector DB (with metadata)

Question ─┬─> embedding model ─> nearest chunks ─┐
          │                                      ├─> merge (RRF) ─> prompt ─> LLM ─> answer
          └─> BM25 keyword scores ─> top chunks ─┘
          (optional filters narrow both searches first)
```

### 6.2 Components

| Component | Selection | Notes |
|---|---|---|
| **Data** | Insulin pump reports from the openFDA API | 3,000 reports from 2025, 250 per month, about 9 per day |
| **Embedding model** | `all-MiniLM-L6-v2` | Small, open-source, runs locally on a CPU |
| **Vector DB** | Chroma | Stored on disk in `data/chroma`; also applies the metadata filters |
| **Keyword search** | BM25, written in plain Python | No extra package; see `maude_rag/keyword.py` |
| **LLM** | Claude | Called through the Anthropic API |

### 6.3 Prerequisites

| Item | Needed for |
|---|---|
| Python 3 | All steps |
| Internet access | Steps 7.1 and 7.2, and the first run of step 7.3 (model download) |
| Anthropic API key | Step 7.7 only |

## 7. Procedure

### 7.1 Set up the environment

```bash
python -m venv .venv && source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install -r requirements.txt
```

### 7.2 Download the reports

```bash
python -m maude_rag.ingest
```

**Expected result:** reports are saved to `data/reports.jsonl`. This makes one request per day of the year and takes a few minutes.

### 7.3 Build the index

```bash
python -m maude_rag.index
```

**Expected result:** the narratives are embedded and stored in `data/chroma`. This takes about a minute on a CPU.

### 7.4 Run a retrieval-only query

No API key is needed for this step.

```bash
python -m maude_rag.ask --retrieve-only "pump screen went blank"
```

**Expected result:** a list of the best matching report excerpts. Each line shows a similarity score (or `-` when only keyword search found it), which search found it (`vector`, `keyword` or `both`), and the report number.

### 7.5 Narrow the search with filters

Filters are optional and can be combined. Brand and manufacturer accept any part of the name.

```bash
python -m maude_rag.ask --values brand_name          # list brand names and counts
python -m maude_rag.ask --retrieve-only --event-type Death "occlusion"
python -m maude_rag.ask --retrieve-only --manufacturer "beta bionics" "cartridge"
python -m maude_rag.ask --retrieve-only --brand 780g --since 20250101 --until 20250131 "screen blank"
```

| Option | Accepts |
|---|---|
| `--event-type` | `Malfunction`, `Injury` or `Death` |
| `--brand`, `--manufacturer` | Any part of the name, in any case |
| `--since`, `--until` | A date as `YYYYMMDD`, inclusive |

**Expected result:** only reports matching every filter are returned. If none match, a message says so.

### 7.6 Compare search methods

```bash
python -m maude_rag.ask --retrieve-only --mode vector  "occlusion alarm"   # step 1 baseline
python -m maude_rag.ask --retrieve-only --mode keyword "occlusion alarm"
python -m maude_rag.ask --retrieve-only                "occlusion alarm"   # hybrid (default)
```

**Expected result:** three lists for the same question, showing what each method finds.

### 7.7 Run a full question

This step needs an Anthropic API key.

```bash
export ANTHROPIC_API_KEY=...
python -m maude_rag.ask "What problems are reported with infusion sets?"
```

**Expected result:** the retrieved excerpts, followed by a written answer that cites report numbers.

### 7.8 Verify the installation

```bash
python -m pytest
```

**Expected result:** all tests pass.

### 7.9 Evaluate retrieval

No API key is needed for this step.

```bash
python -m maude_rag.evaluate -v
```

**Expected result:** a table scoring each search method (`vector`, `keyword`, `hybrid`) by question type, followed by one table per method with a row per question. The `Unjudged` column should be 0; if it is not, a method retrieved reports that nobody has judged, and those questions need more reading before the scores can be trusted.

To keep a record, save the output with the date and a run number (`N` is 1 for the first run that day, then 2, and so on). Never overwrite an earlier record:

```bash
python -m maude_rag.evaluate -v > eval/results/YYYY-MM-DD-N.md
```

Add the procedure revision, the data download date, and any observations at the top of the file, as in `eval/results/2026-11-13-2.md`. If the test set changed since the last run, say what changed and why.

**Limits:** the test set has 20 questions, so one question is 5 percentage points of hit rate. It was drafted by Claude and has not yet been reviewed by a person; until it is, treat the scores as provisional.

### 7.10 Interpret the answers

Apply these limits to every answer:

1. MAUDE is a passive reporting system. Reports are unverified and may be duplicated.
2. A report does not show that a device caused an event.
3. Report counts are not incidence rates.
4. Nothing produced by this project is medical advice.

## 8. Records

| Record | Location | Created by |
|---|---|---|
| Downloaded reports | `data/reports.jsonl` | Step 7.2 |
| Vector index | `data/chroma` | Step 7.3 |
| Test set | `eval/questions.json` | Written by hand; see [docs/explainers/evaluate.md](docs/explainers/evaluate.md) |
| Evaluation results | `eval/results/YYYY-MM-DD-N.md` | Step 7.9 |

The `data` folder is excluded from version control and is rebuilt by repeating steps 7.2 and 7.3. The `eval` folder is kept in version control, so results can be compared over time.

## 9. Roadmap

| Step | Description | Status |
|---|---|---|
| 1 | Naive RAG baseline, measured on a test set | Covered by this procedure |
| 2 | Metadata filters and keyword search | Covered by this procedure |
| 3 | SQL path for counting questions | Planned |
| 4 | Query router (Adaptive RAG) | Planned |
| 5 | Agentic retrieval | Planned (optional) |

## 10. Revision History

| Revision | Date | Description |
|---|---|---|
| A | 2026-11-13 | Initial release: Naive RAG baseline |
| B | 2026-11-13 | Added metadata filters, BM25 keyword search and hybrid retrieval (roadmap step 2). Changed the download to sample every day of each month; Revision A took only the first day or two of each month. Repeat steps 7.2 and 7.3 after updating |
| C | 2026-11-13 | Added the 20-question test set and the retrieval scorer (step 7.9), completing roadmap step 1's baseline. Results recorded in `eval/results/2026-11-13-1.md` (first draft of the test set) and `eval/results/2026-11-13-2.md` (six weak questions replaced) |

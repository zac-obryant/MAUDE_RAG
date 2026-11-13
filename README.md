# MAUDE RAG: Naive RAG Baseline Procedure

| Field | Value |
|---|---|
| **Document title** | Building and Running the Naive RAG Baseline over FDA MAUDE Reports |
| **Document type** | Procedure |
| **Revision** | A |
| **Effective date** | 2026-11-13 |
| **Applies to** | Step 1 of the project roadmap (see Section 9) |

> This is a learning project built in public. The document borrows the layout of a quality system procedure for clarity; it is not a controlled document and is not part of any certified quality management system.

---

## 1. Purpose

This procedure describes how to set up and run question answering over the FDA's [MAUDE](https://www.fda.gov/medical-devices/mandatory-reporting-requirements-manufacturers-importers-and-device-user-facilities/manufacturer-and-user-facility-device-experience-database-maude) database of medical device adverse event reports, using a Naive RAG (retrieval-augmented generation) baseline. The project is built in public, one step at a time.

## 2. Scope

**In scope**

- 3,000 insulin pump reports received by the FDA in 2025 (250 per month).
- The reporter's "Description of Event or Problem" text from each report.
- Downloading the reports, indexing them, and asking questions against them.

**Out of scope**

- Other device types and other years.
- The manufacturer's follow-up narrative in each report.
- Later roadmap steps (Section 9).

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

A fuller glossary is in [docs/explainers](docs/explainers/README.md).

## 4. Responsibilities

| Role | Responsibility |
|---|---|
| **User** | Runs this procedure and supplies their own Anthropic API key for the answering step |
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
Reports ─> chunk ─> embedding model ─> vector DB
Question ─> embedding model ─> nearest chunks ─> prompt ─> LLM ─> answer
```

### 6.2 Components

| Component | Selection | Notes |
|---|---|---|
| **Data** | Insulin pump reports from the openFDA API | 3,000 reports from 2025, 250 per month |
| **Embedding model** | `all-MiniLM-L6-v2` | Small, open-source, runs locally on a CPU |
| **Vector DB** | Chroma | Stored on disk in `data/chroma` |
| **LLM** | Claude | Called through the Anthropic API |

### 6.3 Prerequisites

| Item | Needed for |
|---|---|
| Python 3 | All steps |
| Internet access | Steps 7.1 and 7.2, and the first run of step 7.3 (model download) |
| Anthropic API key | Step 7.5 only |

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

**Expected result:** reports are saved to `data/reports.jsonl`.

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

**Expected result:** a list of the closest matching report excerpts, each with a similarity score and report number.

### 7.5 Run a full question

This step needs an Anthropic API key.

```bash
export ANTHROPIC_API_KEY=...
python -m maude_rag.ask "What problems are reported with infusion sets?"
```

**Expected result:** the retrieved excerpts, followed by a written answer that cites report numbers.

### 7.6 Verify the installation

```bash
python -m pytest
```

**Expected result:** all tests pass.

### 7.7 Interpret the answers

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

The `data` folder is excluded from version control and is rebuilt by repeating steps 7.2 and 7.3.

## 9. Roadmap

| Step | Description | Status |
|---|---|---|
| 1 | Naive RAG baseline | Covered by this procedure |
| 2 | Metadata filters and keyword search | Planned |
| 3 | SQL path for counting questions | Planned |
| 4 | Query router (Adaptive RAG) | Planned |
| 5 | Agentic retrieval | Planned (optional) |

## 10. Revision History

| Revision | Date | Description |
|---|---|---|
| A | 2026-11-13 | Initial release: Naive RAG baseline |

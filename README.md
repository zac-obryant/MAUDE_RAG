# MAUDE RAG

Question answering over the FDA's [MAUDE](https://www.fda.gov/medical-devices/mandatory-reporting-requirements-manufacturers-importers-and-device-user-facilities/manufacturer-and-user-facility-device-experience-database-maude) database of medical device adverse event reports, built in public one step at a time.

## Step 1: Naive RAG baseline

```
Reports ─> chunk ─> embedding model ─> vector DB
Question ─> embedding model ─> nearest chunks ─> prompt ─> LLM ─> answer
```

- **Data:** 3,000 insulin pump reports from 2025 (250 per month), pulled from the [openFDA API](https://open.fda.gov/apis/device/event/). Only the reporter's "Description of Event or Problem" text is indexed.
- **Embedding model:** `all-MiniLM-L6-v2`, a small open-source model that runs locally on a CPU.
- **Vector DB:** [Chroma](https://www.trychroma.com/), stored on disk in `data/chroma`.
- **LLM:** Claude, via the Anthropic API.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install -r requirements.txt

python -m maude_rag.ingest          # download reports to data/reports.jsonl
python -m maude_rag.index           # embed and store them (about a minute on CPU)

# Retrieval only: no API key needed
python -m maude_rag.ask --retrieve-only "pump screen went blank"

# Full answer: needs an Anthropic API key
export ANTHROPIC_API_KEY=...
python -m maude_rag.ask "What problems are reported with infusion sets?"
```

Tests: `python -m pytest`

## Reading the answers

MAUDE is a passive reporting system. Reports are unverified, may be duplicated, and do not show that a device caused an event. Report counts are not incidence rates. Nothing here is medical advice.

## Roadmap

1. **Naive RAG baseline** (this step)
2. Metadata filters and keyword search
3. SQL path for counting questions
4. Query router (Adaptive RAG)
5. Agentic retrieval (optional)

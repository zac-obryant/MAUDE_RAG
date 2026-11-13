"""Step 1c (updated in step 2): answer a question from the retrieved narratives.

    python -m maude_rag.ask "What problems are reported with infusion sets?"
    python -m maude_rag.ask --retrieve-only "pump screen went blank"
    python -m maude_rag.ask --retrieve-only --event-type Death --since 20250601 "occlusion"
    python -m maude_rag.ask --values brand_name

Retrieval runs two searches and merges them: vector search (meaning) and BM25
keyword search (exact words). Metadata filters narrow both to matching reports
before anything is ranked. The top chunks go into a prompt for the LLM.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from functools import cache

import chromadb
from sentence_transformers import SentenceTransformer

from .config import CHROMA_DIR, COLLECTION, EMBEDDING_MODEL, RAW_REPORTS, TOP_K
from .keyword import bm25, rrf
from .llm import LAST_CALL, Declined, ask_claude

# MAUDE report numbers: 1234567-2025-00012, 1234567890-2025-000123, or MW1234567.
REPORT_NUMBER = re.compile(r"\b(?:\d{7,10}-\d{4}-\d{5,6}|MW\d{7})\b")

SYSTEM = """You answer questions about insulin pump adverse events using excerpts \
from FDA MAUDE reports.

Use only the excerpts provided. Cite the report number in square brackets after \
each claim, like [1234567-2025-00012]. If the excerpts do not answer the question, \
say so rather than drawing on outside knowledge.

MAUDE is a passive reporting system: reports are unverified, can be duplicated, \
and do not establish that the device caused the event. The excerpts are a small \
sample, so describe what the reports say and do not estimate how common a problem is."""


@cache
def _embedder() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL)


@cache
def _collection():
    return chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION)


def matching(field: str, text: str) -> list[str]:
    """Every stored value of a field that contains the text: "780g" finds all 780G brands.

    The database can only match whole values, and MAUDE brand and manufacturer
    names are long and inconsistent, so partial matching is done here.
    """
    return sorted({v for v, _ in values(field, top=None) if text.upper() in v})


def where_clause(
    event_type: str | None = None,
    brands: list[str] | None = None,
    manufacturers: list[str] | None = None,
    since: int | None = None,
    until: int | None = None,
) -> dict | None:
    """Turn the filter options into a Chroma `where` clause (None means no filter)."""
    conditions = []
    if event_type:
        conditions.append({"event_type": event_type.upper()})
    if brands is not None:
        conditions.append({"brand_name": {"$in": brands}})
    if manufacturers is not None:
        conditions.append({"manufacturer": {"$in": manufacturers}})
    if since:
        conditions.append({"date_received": {"$gte": since}})
    if until:
        conditions.append({"date_received": {"$lte": until}})
    if len(conditions) > 1:
        return {"$and": conditions}
    return conditions[0] if conditions else None


def filters_to_where(event_type=None, brand=None, manufacturer=None, since=None, until=None) -> dict | None:
    """Turn the filter options as typed into a `where` clause, expanding partial names."""
    brands = matching("brand_name", brand) if brand else None
    manufacturers = matching("manufacturer", manufacturer) if manufacturer else None
    if brands == [] or manufacturers == []:
        raise LookupError("No brand or manufacturer contains that text. See --values brand_name or --values manufacturer.")
    return where_clause(event_type, brands, manufacturers, since, until)


def retrieve(question: str, k: int = TOP_K, where: dict | None = None, mode: str = "hybrid") -> list[dict]:
    """Return the top k chunks for the question.

    mode "vector" is the step 1 baseline, "keyword" is BM25 only, and "hybrid"
    merges both with reciprocal rank fusion. Each hit says which search found it.
    """
    found: dict[str, dict] = {}
    rankings = []

    if mode in ("vector", "hybrid"):
        vector = _embedder().encode([question], normalize_embeddings=True)
        hits = _collection().query(query_embeddings=vector.tolist(), n_results=k, where=where)
        for id_, text, distance, metadata in zip(
            hits["ids"][0], hits["documents"][0], hits["distances"][0], hits["metadatas"][0]
        ):
            found[id_] = {"text": text, "similarity": 1 - distance, "found_by": "vector", **metadata}
        rankings.append(hits["ids"][0])

    if mode in ("keyword", "hybrid"):
        pool = _collection().get(where=where, include=["documents", "metadatas"])
        scores = bm25(question, pool["documents"])
        top = [i for i in sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:k] if scores[i] > 0]
        for i in top:
            id_ = pool["ids"][i]
            if id_ in found:
                found[id_]["found_by"] = "both"
            else:
                found[id_] = {"text": pool["documents"][i], "similarity": None, "found_by": "keyword",
                              **pool["metadatas"][i]}
        rankings.append([pool["ids"][i] for i in top])

    return [found[id_] for id_ in rrf(*rankings)[:k]]


def values(field: str, top: int | None = 25) -> list[tuple[str, int]]:
    """Most common values of a report field, to see what the filters accept."""
    reports = (json.loads(line) for line in RAW_REPORTS.open())
    return Counter(str(r.get(field, "")).upper() for r in reports).most_common(top)


def build_prompt(question: str, hits: list[dict]) -> str:
    excerpts = "\n\n".join(
        f'<report number="{h["report_number"]}" received="{h["date_received"]}" '
        f'brand="{h["brand_name"]}" event_type="{h["event_type"]}">\n{h["text"]}\n</report>'
        for h in hits
    )
    return f"<reports>\n{excerpts}\n</reports>\n\nQuestion: {question}"


def answer(question: str, hits: list[dict]) -> str:
    try:
        return ask_claude(SYSTEM, build_prompt(question, hits))
    except Declined as e:
        return str(e)


def as_json(question: str, k: int, mode: str) -> dict:
    """One answer in the AIPV harness contract: answer, cited_ids, retrieved_ids, config."""
    hits = retrieve(question, k, None, mode)
    text = answer(question, hits) if hits else ""
    return {
        "answer": text,
        "cited_ids": list(dict.fromkeys(REPORT_NUMBER.findall(text))),
        "retrieved_ids": list(dict.fromkeys(h["report_number"] for h in hits)),
        "config": {
            **LAST_CALL,
            "system_prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest()[:16],
            "embedding_model": EMBEDDING_MODEL,
            "retrieval_mode": mode,
            "top_k": k,
            "index_chunks": _collection().count(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", nargs="?")
    parser.add_argument("-k", type=int, default=TOP_K, help="number of chunks to retrieve")
    parser.add_argument("--retrieve-only", action="store_true", help="skip the LLM step")
    parser.add_argument("--mode", choices=["hybrid", "vector", "keyword"], default="hybrid")
    filters = parser.add_argument_group("filters")
    filters.add_argument("--event-type", help="e.g. Malfunction, Injury, Death")
    filters.add_argument("--brand", help="any part of a brand name, e.g. 780g (see --values brand_name)")
    filters.add_argument("--manufacturer", help="any part of a manufacturer name (see --values manufacturer)")
    filters.add_argument("--since", type=int, metavar="YYYYMMDD", help="received on or after")
    filters.add_argument("--until", type=int, metavar="YYYYMMDD", help="received on or before")
    parser.add_argument("--values", metavar="FIELD", help="list common values of a field and exit")
    parser.add_argument("--json", action="store_true",
                        help="print one JSON answer for the AIPV harness; reads the question from stdin if not given")
    args = parser.parse_args()

    if args.json:
        print(json.dumps(as_json(args.question or sys.stdin.read().strip(), args.k, args.mode)))
        return
    if args.values:
        for value, count in values(args.values):
            print(f"{count:6d}  {value}")
        return
    if not args.question:
        parser.error("a question is required")

    try:
        where = filters_to_where(args.event_type, args.brand, args.manufacturer, args.since, args.until)
    except LookupError as e:
        print(e)
        return
    hits = retrieve(args.question, args.k, where, args.mode)
    if not hits:
        print("No matching reports. Loosen the filters or check spellings with --values.")
        return
    print("Retrieved:")
    for h in hits:
        score = f"{h['similarity']:.2f}" if h["similarity"] is not None else "  - "
        print(f"  {score}  {h['found_by']:<7}  {h['report_number']}  {h['brand_name']}: {h['text'][:80]}...")
    if not args.retrieve_only:
        print("\n" + answer(args.question, hits))


if __name__ == "__main__":
    main()

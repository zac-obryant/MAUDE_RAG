"""Step 1b (updated in steps 2 and 3): embed the narratives and store them in a vector database.

    python -m maude_rag.index

Each narrative is split into overlapping chunks, each chunk is turned into a
vector by the embedding model, and the vectors go into a local Chroma database
alongside the report's metadata. Since step 3 it also writes the reports into a
SQLite database (data/reports.db) for counting questions.
"""

import json

import chromadb
from sentence_transformers import SentenceTransformer

from .config import (
    CHROMA_DIR,
    DB_PATH,
    CHUNK_OVERLAP,
    CHUNK_WORDS,
    COLLECTION,
    EMBEDDING_MODEL,
    RAW_REPORTS,
)
from .sql import build as build_database

BATCH = 1000


def chunk(text: str, size: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into pieces of `size` words, each sharing `overlap` words with the last."""
    words = text.split()
    if len(words) <= size:
        return [" ".join(words)]
    step = size - overlap
    return [" ".join(words[i : i + size]) for i in range(0, len(words) - overlap, step)]


def main() -> None:
    reports = [json.loads(line) for line in RAW_REPORTS.open()]
    ids, texts, metadatas = [], [], []
    for report in reports:
        for n, piece in enumerate(chunk(report["narrative"])):
            ids.append(f"{report['report_number']}#{n}")
            texts.append(piece)
            metadatas.append(
                {
                    "report_number": report["report_number"],
                    # A number (20250314) so date ranges can be filtered with $gte/$lte.
                    "date_received": int(report["date_received"] or 0),
                    # Upper case so filters match however the user types them.
                    "event_type": report["event_type"].upper(),
                    "brand_name": report["brand_name"].upper(),
                    "manufacturer": report["manufacturer"].upper(),
                    "product_code": report["product_code"],
                }
            )
    print(f"{len(reports)} reports -> {len(texts)} chunks")

    model = SentenceTransformer(EMBEDDING_MODEL)
    # Normalised vectors make cosine similarity a simple dot product.
    vectors = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=True)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)  # rebuild from scratch each run
    collection = client.create_collection(COLLECTION, configuration={"hnsw": {"space": "cosine"}})
    for start in range(0, len(ids), BATCH):
        end = start + BATCH
        collection.add(
            ids=ids[start:end],
            documents=texts[start:end],
            embeddings=vectors[start:end].tolist(),
            metadatas=metadatas[start:end],
        )
    print(f"Indexed {collection.count()} chunks into {CHROMA_DIR}")

    build_database(reports)  # step 3: the same reports as a SQLite table, for counting
    print(f"Built {DB_PATH}")


if __name__ == "__main__":
    main()

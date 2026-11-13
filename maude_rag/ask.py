"""Step 1c: answer a question from the retrieved narratives.

    python -m maude_rag.ask "What problems are reported with infusion sets?"
    python -m maude_rag.ask --retrieve-only "pump screen went blank"

Naive RAG: embed the question, find the nearest narrative chunks, paste them
into a prompt, and let the LLM answer from them.
"""

import argparse
from functools import cache

import chromadb
from sentence_transformers import SentenceTransformer

from .config import ANSWER_MODEL, CHROMA_DIR, COLLECTION, EMBEDDING_MODEL, TOP_K

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


def retrieve(question: str, k: int = TOP_K) -> list[dict]:
    """Return the k chunks whose vectors are closest to the question's vector."""
    vector = _embedder().encode([question], normalize_embeddings=True)
    hits = _collection().query(query_embeddings=vector.tolist(), n_results=k)
    return [
        {"text": text, "similarity": 1 - distance, **metadata}
        for text, distance, metadata in zip(
            hits["documents"][0], hits["distances"][0], hits["metadatas"][0]
        )
    ]


def build_prompt(question: str, hits: list[dict]) -> str:
    excerpts = "\n\n".join(
        f'<report number="{h["report_number"]}" received="{h["date_received"]}" '
        f'brand="{h["brand_name"]}" event_type="{h["event_type"]}">\n{h["text"]}\n</report>'
        for h in hits
    )
    return f"<reports>\n{excerpts}\n</reports>\n\nQuestion: {question}"


def answer(question: str, hits: list[dict]) -> str:
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    response = client.beta.messages.create(
        model=ANSWER_MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_prompt(question, hits)}],
        # If the model declines a request, the API retries it on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        return "The model declined to answer this question."
    return "".join(block.text for block in response.content if block.type == "text")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("-k", type=int, default=TOP_K, help="number of chunks to retrieve")
    parser.add_argument("--retrieve-only", action="store_true", help="skip the LLM step")
    args = parser.parse_args()

    hits = retrieve(args.question, args.k)
    print("Retrieved:")
    for h in hits:
        print(f"  {h['similarity']:.2f}  {h['report_number']}  {h['brand_name']}: {h['text'][:90]}...")
    if not args.retrieve_only:
        print("\n" + answer(args.question, hits))


if __name__ == "__main__":
    main()

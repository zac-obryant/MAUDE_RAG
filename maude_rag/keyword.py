"""Step 2b: keyword search (BM25) and the fusion that blends it with vector search.

Vector search finds text that *means* the same thing as the question; it can miss
exact terms such as an error code or a part name. BM25 scores text by the words
it shares with the question, giving rare words more weight than common ones.
Reciprocal rank fusion then merges the two ranked lists into one.
"""

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def bm25(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Score every doc against the query. Higher is better; 0 means no shared words."""
    # ponytail: rebuilds term counts on every query; fine for a few thousand chunks,
    # store an inverted index at index time if the corpus grows past ~100k.
    docs_tokens = [tokens(d) for d in docs]
    if not docs_tokens:
        return []
    n = len(docs_tokens)
    avg_len = sum(map(len, docs_tokens)) / n or 1
    doc_freq = Counter(t for d in docs_tokens for t in set(d))
    query_terms = set(tokens(query))
    scores = []
    for d in docs_tokens:
        tf = Counter(d)
        score = 0.0
        for t in query_terms & tf.keys():
            idf = math.log(1 + (n - doc_freq[t] + 0.5) / (doc_freq[t] + 0.5))
            score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg_len))
        scores.append(score)
    return scores


def rrf(*rankings: list[str], k: int = 60) -> list[str]:
    """Reciprocal rank fusion: an id near the top of any list rises to the top overall."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0) + 1 / (k + rank + 1)
    return sorted(scores, key=scores.__getitem__, reverse=True)

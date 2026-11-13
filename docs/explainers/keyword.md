# `maude_rag/keyword.py`

## Purpose

This file adds a second way of searching. Vector search (step 1) finds chunks that *mean* something similar to the question. Keyword search finds chunks that contain the question's *exact words*. This file also holds the rule that merges the two result lists into one.

It was added in step 2 of the roadmap. `ask.py` calls it; it is never run on its own.

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `math` | Built into Python | Supplies the logarithm used to weigh rare words |
| `re` | Built into Python | Splits text into words using a pattern |
| `collections.Counter` | Built into Python | Counts how often each word appears |

No installed packages are needed.

## Step by step with code snippets

### 1. Split text into words (`tokens`)

```python
_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text):
    return _TOKEN.findall(text.lower())
```

**In plain steps**

```
a word = a run of letters and digits, with nothing else in it

to split text into words:
    make the text lower case
    hand back every run of letters and digits, in order
```

**Key elements**

| Code | What it means |
|---|---|
| `re.compile(r"[a-z0-9]+")` | A *pattern*: "one or more letters a to z or digits 0 to 9 in a row" |
| `.lower()` | Make the text lower case, so `PUMP` and `pump` count as the same word |
| `.findall(...)` | Find every stretch of the text that fits the pattern |

**Explanation**

`"Pump showed ERROR E-03."` becomes `["pump", "showed", "error", "e", "03"]`. Punctuation and spaces are dropped. Note that `E-03` becomes two words, `e` and `03`; a search for `E-03` is split the same way, so it still matches.

### 2. Score each chunk against the question (`bm25`)

```python
def bm25(query, docs, k1=1.5, b=0.75):
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
```

**In plain steps**

```
to score every chunk against a question:
    split every chunk into words
    if there are no chunks: hand back an empty list

    n          = how many chunks there are
    avg_len    = the average chunk length in words
    doc_freq   = for each word, how many chunks contain it
    question words = the question's words, each listed once

    for each chunk:
        score = 0
        for each question word that appears in this chunk:
            rarity = high if few chunks contain the word, low if most do
            add rarity x (how often the word appears here, with diminishing returns,
                          adjusted so long chunks do not win just by being long)
        remember the score

    hand back the list of scores, one per chunk
```

**Key elements**

| Code | What it means |
|---|---|
| `[tokens(d) for d in docs]` | Split each chunk into words, giving a list of word lists |
| `Counter(...)` | Count things. `doc_freq["occlusion"]` is how many chunks contain "occlusion" |
| `set(d)` | The chunk's words with repeats removed, so a chunk is counted once per word |
| `query_terms & tf.keys()` | The words that appear in both the question and this chunk |
| `math.log(...)` | A logarithm. It shrinks big numbers, so a very rare word scores high but not absurdly high |
| `k1=1.5` | How quickly repeats stop adding score. The fifth "alarm" in a chunk adds far less than the first |
| `b=0.75` | How much to penalise long chunks |

**Explanation**

BM25 ("Best Match 25") is the standard keyword-scoring formula used by search engines. Two ideas drive it:

- **Rare words matter more.** "pump" appears in nearly every report, so matching it says little. "occlusion" appears in few, so matching it says a lot.
- **Repetition helps, with limits.** A chunk that says "occlusion" three times is a better match than one that says it once, but not three times better.

A chunk sharing no words with the question scores 0, and `ask.py` drops those.

### 3. Merge two ranked lists (`rrf`)

```python
def rrf(*rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0) + 1 / (k + rank + 1)
    return sorted(scores, key=scores.__getitem__, reverse=True)
```

**In plain steps**

```
to merge several ranked lists:
    for each list:
        for each item, at position 1, 2, 3, ...:
            add 1 / (60 + position) to that item's total

    hand back every item, highest total first
```

**Key elements**

| Code | What it means |
|---|---|
| `*rankings` | Accept any number of lists |
| `enumerate(ranking)` | Walk the list while also counting positions: 0, 1, 2, ... |
| `scores.get(item, 0)` | The item's total so far, or 0 if it has none yet |
| `sorted(..., reverse=True)` | Order from highest total to lowest |

**Explanation**

The vector search and the keyword search score on different scales (a similarity of 0.7 versus a BM25 score of 12), so their scores cannot simply be added. Reciprocal rank fusion ignores the scores and uses only positions. An item near the top of either list does well, and an item found by both lists does best. The 60 is the conventional value; it stops the first position from dominating.

## What to keep in mind

- Keyword search matches spelling, not meaning. "Leak" will not find "leaking"; vector search covers that gap, which is why the two are combined.
- The word counts are rebuilt from the database on every question. That takes well under a second for a few thousand chunks, but would need to be stored in advance for a much larger collection.

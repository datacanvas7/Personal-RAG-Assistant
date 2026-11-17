# Retrieval evaluation

How the retrieval configurations were compared, what the numbers say, and, just as important,
what they cannot say. Everything here is reproducible with one command (see
[Reproduce](#reproduce)).

## What is measured

The question is narrow on purpose: **given a question, is the passage that contains the answer
among the passages we hand to the language model?** If it is not, no model can answer from the
documents, so retrieval quality caps answer quality.

Each of the 44 questions has exactly one answer-bearing fact, written as a short phrase
(`marker`) that occurs in exactly one place of the corpus (a unit test enforces this). A
retrieved chunk is *relevant* when it contains the marker. Labelling facts instead of chunk ids
keeps the labels valid when the chunk size changes, which lets us compare chunking too.

| Metric | Meaning |
|---|---|
| **Recall@k** | Share of questions whose answer is within the first k results (k = 1, 3, 5). |
| **MRR** | Mean reciprocal rank of the first relevant chunk (1.0 = always first). |
| Median search (ms) | Time of `SearchService.search` with the query embedding already cached, so it isolates the database work and fusion. Local PostgreSQL, 19-46 chunks: it says nothing about large collections. |

The default `top_k` of the application is 5, so Recall@5 is "can the model see the answer" and
Recall@1 / MRR are "is it ranked well", which matters when the context budget truncates the
list.

## The dataset

`backend/app/evaluation/dataset.py`, entirely synthetic so it can live in the repository:

* **18 documents**: eight hand-written policy/manual files (IT security, travel, leave, a pump
  manual with page numbers, onboarding, incident response, facilities, data retention) and ten
  near-identical *office guides*, one per city, which repeat the same three sentences with
  different numbers (canteen closing time, parking permit price, visitor notice).
* **44 questions** in four groups:
  * `paraphrase` (10): the question uses different words than the answer ("login secret" for
    "password"). Designed to favour embeddings.
  * `exact` (8): codes and part numbers (`E-4471`, `FC-88`, `AES-256`). Designed to favour
    word matching.
  * `natural` (9): ordinary questions in the document's own vocabulary.
  * `confusable` (17): another passage says something similar. Includes 12 questions that
    only differ from nine neighbours by the city name.

## Configurations

| Name | What it does |
|---|---|
| vector only | Nearest chunks by cosine similarity (pgvector, HNSW). The Phase 5 behaviour. |
| keyword only | PostgreSQL full-text search (`websearch_to_tsquery`, OR semantics, `ts_rank_cd`). |
| hybrid (RRF) | Both rankings, merged with Reciprocal Rank Fusion (k = 60). |
| + rerank | A lexical reranker re-orders a candidate pool of `top_k x 4`: `(1 - w) x cosine + w x term coverage`. |

Embedding model for every run: `BAAI/bge-small-en-v1.5` (384 dimensions), the application's
default. Chunking: 1500 characters with 200 overlap unless stated.

## Results

Environment: PostgreSQL 16, pgvector 0.6.2, 2026-11-18. (CI and Docker use pgvector 0.8; the
ranking logic is the same.)

### Retrieval modes

| Configuration | Chunks | Recall@1 | Recall@3 | Recall@5 | MRR | Median search (ms) |
|---|---:|---:|---:|---:|---:|---:|
| vector only | 19 | 95% | 100% | 100% | 0.973 | 6.4 |
| keyword only | 19 | 93% | 100% | 100% | 0.962 | 6.9 |
| vector + rerank | 19 | 100% | 100% | 100% | 1.000 | 7.8 |
| hybrid (RRF) | 19 | 100% | 100% | 100% | 1.000 | 10.0 |
| hybrid + rerank | 19 | 100% | 100% | 100% | 1.000 | 12.3 |

(Rerank weight 0.25 in this table.) Recall@3 is 100% in every configuration and for every
question type.

### What each single method gets wrong

| Configuration | Answer not ranked first |
|---|---|
| vector only | `E-4471` (rank 2) and `AES-256` (rank 3): an exact code is a poor embedding query. |
| keyword only | 2-3 paraphrases ("login secret", "new mums and dads"; rank 3): the right chunk shares few words with the question. The count varies by run because chunks with equal full-text rank are ordered by their random ids, which is also why this row's Recall@1 moved between 93% and 95% across runs. |
| hybrid (RRF) | none |

That is the textbook argument for hybrid search, and it shows up here: each method loses on the
kind of question it is bad at, and fusion recovers both.

### Reranker weight

A first run used weight 0.5 and was **worse** than not reranking at all:

| Configuration | Recall@1 | MRR |
|---|---:|---:|
| hybrid + rerank, weight 0.1 | 100% | 1.000 |
| hybrid + rerank, weight 0.25 | 100% | 1.000 |
| hybrid + rerank, weight 0.5 | 93% | 0.966 |
| hybrid + rerank, weight 0.75 | 93% | 0.966 |

At 0.5 the reranker pushed the correct passage from rank 1 to rank 2 for three paraphrase
questions ("login secret", "new mums and dads", "long break after many years"): a chunk that
happened to contain one stray query word outranked the right one. A lexical reranker is
blind to meaning, so it should only break near-ties, hence the default of 0.25.

### Chunking (hybrid + rerank, weight 0.25)

| Chunk size / overlap | Chunks | Recall@1 | Recall@5 | MRR |
|---|---:|---:|---:|---:|
| 300 / 50 | 46 | 100% | 100% | 1.000 |
| 600 / 100 | 23 | 100% | 100% | 1.000 |
| 1000 / 150 | 19 | 100% | 100% | 1.000 |
| 1500 / 200 (default) | 19 | 100% | 100% | 1.000 |
| 2500 / 300 | 19 | 100% | 100% | 1.000 |

With the overly strong reranker (weight 0.5), smaller chunks did better (300/50: 98% Recall@1,
MRR 0.989, versus 93% / 0.966 for 1000 and above) because a short chunk contains fewer stray
words. That is an effect of the reranker setting, not evidence about chunk size, which is why
the default chunking is unchanged.

## What the numbers do not show

Read these before quoting any figure:

* **The set is saturated.** Several configurations reach 100%, so it cannot separate them. It
  does show the failure modes of the weaker ones (the two tables above), but it cannot
  show that hybrid beats hybrid + rerank or that one chunk size beats another.
* **Small and synthetic.** 44 questions on 18 short documents (19 chunks at the default size).
  Real libraries have thousands of chunks, longer and messier text, and questions that were
  not written by the same author as the answers. One question is worth 2.3 percentage points.
* **Retrieval only.** Groundedness (does the answer follow from the passages) and citation
  correctness need a language model as judge; they are not measured here and no number for
  them is claimed.
* **One embedding model.** A different model can change the picture, especially for the
  vector-only rows. Vector and hybrid results repeat exactly between runs; only the
  keyword-only row moves slightly (ties, see above).

## Decisions

| Setting | Value | Why |
|---|---|---|
| `RETRIEVAL_MODE` | `hybrid` | The only mode with no misses; the two single methods fail on opposite kinds of question. Cost: about 3 ms more per search here. |
| `RETRIEVAL_RERANK` | `false` | No measured benefit on top of hybrid (both 100%), and a wrong weight actively hurts. Opt-in until it is shown to help on real documents. |
| Reranker weight | 0.25 | Highest value that did not lower Recall@1 in the sweep. |
| Chunking | 1500 / 200 (unchanged) | No configuration beat it, and larger chunks give the model more context per passage. |
| Candidate pool | `top_k x 4` (max 200) | Fusion and reranking need candidates beyond the final K. |

The `Reranker` protocol is the seam for a cross-encoder model. Swapping one in and re-running
this evaluation is the intended next step once a larger or real document set is available.

## Reproduce

Needs a migrated PostgreSQL (the `POSTGRES_*` settings) and the embedding model (downloaded on
first use, about 130 MB).

```bash
cd backend
python -m uv run alembic upgrade head
python -m uv run python -m app.scripts.evaluate                  # everything
python -m uv run python -m app.scripts.evaluate --only modes     # or: reranker, chunking
```

Each run creates a temporary user, inserts the chunked corpus, searches, and deletes the user
again, so it is safe on a development database. The unit tests in
`backend/tests/unit/test_evaluation.py` check the metrics and that every question has exactly
one answer in the corpus; `backend/tests/integration/test_evaluation.py` runs the whole
pipeline on PostgreSQL with a stand-in embedder and checks that nothing is left behind.

# Interview talking points

Notes for explaining this project. Every number below comes from this repository; check it
before quoting it, and say what is **not** proven as readily as what is.

## The 30-second pitch

"A personal RAG assistant. You upload PDFs, Word, text or Markdown; it indexes them in
PostgreSQL with pgvector, and you chat with them. Answers are generated only from retrieved
passages, carry numbered citations with file and page, and the assistant refuses when the
documents do not contain the answer. It is full stack: FastAPI, Celery, Next.js, Docker
Compose, with CI that builds and starts the whole stack."

## What to emphasise

1. **Grounding is enforced by design, not by hoping the prompt works.** A relevance threshold
   short-circuits before the model is called, citations are matched against passages that were
   really supplied (an invented `[7]` is dropped), and the prompt tells the model to say so
   when the passages do not answer.
2. **Per-user isolation is a database property.** Every query carries `WHERE user_id`, and a
   composite foreign key makes a chunk whose owner differs from its document's impossible.
   Tests and the CI smoke test check that a second user gets nothing.
3. **I measured retrieval instead of assuming it.** 44 questions on 18 synthetic documents:
   vector-only and keyword-only each miss a different kind of question (exact codes versus
   paraphrases); hybrid with Reciprocal Rank Fusion misses none. A reranker I expected to help
   made things *worse* at weight 0.5, so it ships off by default at 0.25.
4. **Testability shaped the architecture.** Routers → services → repositories, with pipeline
   stages behind Protocols and in-memory fakes. The unit suite (451 tests at last count) needs
   no database, Redis, network or model.
5. **Operations were treated as part of the feature.** Request ids, structured logs without
   document text, Redis rate limits that fail open, security headers, read-only containers with
   no capabilities, dependency audits, and a compose smoke test in CI.

## Likely questions

**Why not just use a vector database or a framework's vector store?**
Postgres already stores users and documents, so one system gives transactions, ownership
constraints, full-text search and vectors. Writing the retrieval SQL myself let me guarantee the
`user_id` filter and add hybrid search with one extra column. At personal scale pgvector is
plenty; I would revisit it at hundreds of millions of vectors.

**How do you stop hallucinations?**
You can't eliminate them; you can reduce and expose them. Refuse when evidence is weak, instruct
the model to answer only from numbered passages, drop citations that do not map to a supplied
passage, and show the passage so a human can check. I did not build an automatic groundedness
metric, and I say so.

**How did you choose chunking and the threshold?**
Chunking (1500 characters, 200 overlap, page-aware) was compared across five sizes; all reached
100% recall on this small set, so the result does not discriminate and I kept the default. The
0.45 threshold is a starting value and has *not* been tuned on real documents; it is
configurable per user for that reason.

**What happens when ingestion fails or a worker dies?**
The worker claims a document with a conditional status update and replaces chunks in a single
transaction, so retries and duplicate deliveries cannot create partial or duplicate indexes.
Permanent errors (a corrupt file, a scanned PDF needing OCR) mark the document `failed` with a
safe message and can be retried from the UI; transient ones retry with backoff.

**How does streaming work?**
Server-sent events over a POST. The frontend reads the stream with `fetch` because `EventSource`
cannot send a body or an auth header. The exchange is saved only when the answer completes, and
no database transaction stays open while tokens stream.

**How would you scale it?**
State is already outside the API process (Postgres, Redis), so more API replicas work. The
bottlenecks would be the embedding model on CPU (add workers or a GPU, or a hosted embedding
API), local file storage (move to S3), and pgvector at very large sizes. Nothing has been
load-tested, and I would not claim a number.

**What would you do differently?**
Start the real-model demo earlier. Most of the verification used a stand-in LLM and embedder to
stay deterministic and free; that is right for CI, but it means answer wording with a real model
is unverified. I would also build the answer-quality evaluation (LLM-as-judge on a labelled set)
before tuning anything else.

## A bug worth telling

On the first CI run of the hardening work, the migration container crashed: Docker Compose
passes an unset `${ENABLE_API_DOCS:-}` as an empty string, which a typed `bool | None` setting
rejected. My local check had "passed" only because PowerShell deletes a variable you set to an
empty string. Fix: treat blank as unset, with a regression test. The lessons: test the same path
production uses, and make CI emit service logs when the stack fails to start, because
authenticated job logs were not readable but annotations were.

## Things not to claim

* That answers with a real language model were evaluated; they were not.
* That it is load-tested or multi-host ready; it is not.
* That the 100% retrieval numbers generalise; the set is small, synthetic and saturated.
* That the page CSP is strict; it still allows `'unsafe-inline'`.

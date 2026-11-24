# Technical decisions

The numbered table in [architecture.md §4](architecture.md) lists every decision with its
rejected alternative. This page tells the story behind the ones that shaped the project most,
including the ones that were corrected after measuring or after something broke.

## 1. A modular monolith, not services

One FastAPI codebase runs as two processes (API and Celery worker). Splitting ingestion into its
own service would add a network boundary, a second deployment and distributed failure modes for
a domain that fits in one head. Module boundaries are enforced by interfaces instead, so a part
(say, ingestion) could be extracted later without rewriting its callers.

*Cost:* the API and worker must be deployed together and share one image.

## 2. Layers that only point downwards

Routers parse HTTP and call a service; services own business rules and transactions;
repositories own all SQL. Pipeline stages (loader, chunker, embedder, retriever, LLM) sit
behind small `Protocol` interfaces. The payoff is testing: the unit suite runs the whole
application against in-memory fakes with no database, Redis, model download or network, and
still exercises the real services and routers.

*Cost:* more files and some ceremony for small features.

## 3. Our own retrieval SQL instead of a framework's vector store

The central safety property is "a user can never see another user's text". That is a
`WHERE user_id = :uid` in the query itself, backed by a composite foreign key that makes a
chunk with a different owner than its document impossible. A framework vector store owns its own
tables and schema, which makes both guarantees harder to state and to test. The same choice later
made hybrid search a matter of adding a `tsvector` column and a second query.

LangChain is still used, but only inside adapters (text splitting), so a version bump touches a
few files rather than the whole application.

## 4. Hybrid retrieval, and measuring it

Vector search misses exact codes (`E-4471`), keyword search misses paraphrases ("login secret").
Both failures showed up in [the evaluation](evaluation.md); fusing the two rankings with
Reciprocal Rank Fusion removed them, with no extra infrastructure and no score calibration.

Two honest corrections came out of the same experiment:

* **The reranker was off by default for a reason.** At weight 0.5 it made results *worse*
  (a chunk with one stray query word outranked the right one), so the default weight is 0.25 and
  the reranker stays opt-in until it is shown to help on real documents.
* **The evaluation set is saturated.** Several configurations score 100%, so it proves the
  failure modes of single methods but cannot rank the good configurations against each other.
  The document says so.

## 5. Refuse before generating

If no passage passes the relevance threshold, the answer is a fixed "I couldn't find this in your
documents." and the model is never called. That is the cheapest and most reliable defence against
invented answers, and it saves a request. The threshold (0.45) is a starting value that has
**not** been tuned on real documents; it is exposed per user in Settings for that reason.

## 6. Citations the model cannot invent

Passages are numbered blocks in the prompt. After generation, `[n]` markers are matched against
the passages that were actually supplied; a marker with no matching passage is dropped. Each
saved message keeps a snapshot of file name, page and score, so citations still read correctly
after the source document is deleted (the passage text itself is deliberately not kept).

## 7. One LLM adapter for many providers

Gemini, OpenAI, Groq, OpenRouter and Ollama all speak the OpenAI chat protocol, so one small
adapter covers them and switching is configuration. Gemini's free tier is the default because the
project should be runnable without paying. The cost: provider-specific features are out of reach,
and model names change often, which is why `check_llm` exists.

## 8. Streaming with Server-Sent Events over POST

The answer streams as `token` events and ends with `done` (carrying the saved messages) or
`error`. SSE is simpler than WebSockets for one-way output; because `EventSource` cannot send a
POST body or an `Authorization` header, the frontend reads the stream with `fetch`. An exchange
is saved only when the answer is complete, so an interrupted answer leaves no half-written
history, and no database transaction is held open while tokens stream.

## 9. Authentication

A 15-minute access token is held in memory and sent as a bearer token; a rotating refresh token
lives in an `httpOnly` cookie and is stored hashed server-side so logout and theft detection are
real. Passwords use Argon2id. The browser only ever talks to the Next.js origin (which proxies
`/api/v1`), so the cookie is first-party and there is no CORS in the normal path.

## 10. Failing safe in operations

* **Rate limits fail open.** A Redis outage must not lock everyone out of their own documents, so
  the limiter lets requests through (and logs it) instead of rejecting them. The trade-off is
  stated in [operations.md](operations.md).
* **Production refuses unsafe configuration.** Placeholder secrets or `COOKIE_SECURE=false` stop
  the application at startup rather than running quietly insecure.
* **Containers are read-only and capability-free**, with the API published on localhost only.

## What broke, and what it taught

* **Empty environment variables.** Docker Compose passes an unset `${VAR:-}` as an empty string,
  which a typed `bool | None` setting rejected, so the migration container crashed on first CI
  run. The fix maps blank to "unset" and has a regression test. Lesson: config that is only ever
  exercised in the real container needs a smoke test, which is why CI starts the full stack.
* **Diagnosing CI without log access.** Job logs need authentication, but annotations do not, so
  the smoke job now prints each service's log tail as an error annotation when it fails.
* **Unverified claims.** An earlier local check "proved" empty values were fine because
  PowerShell deletes a variable assigned `""`. The real failure was only found in CI. Checks need
  to exercise the same path as production.

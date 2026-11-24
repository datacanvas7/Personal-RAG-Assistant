# Project Progress — Personal RAG Assistant

Updated at the end of every phase. A box is ticked only when the item is implemented
**and verified** (tests or a documented manual check).

Legend: `[x]` done and verified · `[ ]` not started · `[~]` in progress · `[!]` blocked

Current phase: **Phase 11 — complete, CI green on `b5b6261`** (Phase 10 closed green on `4c1297d`); a real Gemini run with your key is still open from Phase 5 (2026-11-20)

---

## Open blockers

- [x] Docker location decided: **GitHub Codespaces** (no local Docker / WSL2 needed)
- [x] Python 3.13 provided by `uv` (no admin needed); host Python 3.10 left untouched
- [x] Repo pushed to GitHub (datacanvas7/Personal-RAG-Assistant)
- [x] LLM for development: **Google Gemini** via its OpenAI-compatible endpoint (free tier; key from https://aistudio.google.com/apikey goes in `.env` as `LLM_API_KEY`)
- [ ] Windows long paths disabled (`git config --global core.longpaths true`)

## Phase 0 — Project Planning

- [x] Inspect development environment
- [x] Confirm available tools and dependencies (registry versions checked 2026-11-13)
- [x] Finalize architecture and key decisions
- [x] Define project structure
- [x] Create implementation roadmap (this file)
- [x] Identify technical risks and security issues
- [x] Document architecture → [architecture.md](architecture.md)
- [x] Approval to start Phase 1 (user chose Codespaces)

## Phase 1 — Project Foundation

- [x] Resolve blockers (Codespaces dev container: `.devcontainer/devcontainer.json`)
- [x] `git init`, `.gitignore`, `.gitattributes` (LF endings), monorepo skeleton
- [x] Next.js 16 (App Router, TypeScript strict, Tailwind 4) scaffold — lint, typecheck and production build pass
- [x] FastAPI scaffold: typed settings, logging, `/api/v1/health`, OpenAPI docs — 10 unit tests, ruff, mypy strict pass
- [x] Frontend proxy to the API; verified locally against an API with no database (503 passes through, no error text leaked)
- [x] Celery app + `system.ping` task (unit-tested as a function)
- [x] `docker-compose.yml`: postgres+pgvector, redis, backend, worker, frontend; health checks, volumes, networks, startup order
- [x] Dockerfiles (multi-stage, non-root), `.env.example`, `requirements.txt` exported from `uv.lock`
- [x] CI workflow: backend, frontend, and Compose smoke test
- [x] Push to GitHub, open a Codespace, `docker compose up --build --wait` — **verified by the user in Codespaces: all services healthy**
- **Exit:** `docker compose up --build` starts all five services healthy; frontend
  shows backend health; worker executes the ping task.

## Phase 2 — Database and Authentication

- [x] SQLAlchemy models for all entities (7 tables; composite FKs enforce per-user ownership in SQL)
- [x] Alembic configured; hand-written `0001` migration incl. `CREATE EXTENSION vector` — renders valid SQL offline (`alembic upgrade head --sql`)
- [x] Register, login, refresh (rotation + reuse detection), logout, `GET /users/me`
- [x] Argon2id hashing; HS256 JWT validation dependency; uniform `{"error": {...}}` responses
- [x] Auth tests against in-memory fakes: 63 unit tests, ruff, mypy strict pass locally
- [x] 19 database integration tests against real PostgreSQL + pgvector (migration up/down,
  migration-vs-models drift, constraints, cascades, vector dimension, auth flow incl. concurrent
  registration and concurrent refresh) — **passing in CI** (run on commit `1d11c90`). They do not
  run locally (no PostgreSQL on the dev machine).
- [x] Compose `migrate` one-shot service and the auth smoke test through the frontend proxy — **passing in CI**
- **Exit:** migrations apply to an empty DB; auth test suite passes — **met (CI green, 2026-11-13)**.

CI also caught two real defects that local tests could not: the `astral-sh/setup-uv@v10` tag
does not exist (fixed by pinning `v10.3.3`; this had broken the Phase 1 CI run too), and the
models' unique-constraint names disagreed with the migration (fixed; the drift test caught it).

Deferred from the architecture's schema, to be added by the phase that needs it:
`users.full_name`; `documents.embedding_model` (Phase 4; `total_pages/total_chunks` and the
`(user_id, content_sha256)` unique index arrived in Phase 3); `document_chunks.token_count/metadata`,
HNSW index (Phase 4); `search_vector` (Phase 9); `user_settings` (Phase 7).
Rate limiting of login is in Phase 10.

## Phase 3 — Document Ingestion

Status: **complete and verified in CI (commit `d1ff2b7`, 2026-11-13).** 172 unit tests, ruff and
mypy strict pass locally; the database integration tests and the Compose smoke test pass in CI.

- [x] Upload endpoint with validation (extension allow-list, magic bytes, empty, size, filename sanitising); `Content-Length` pre-check middleware
- [x] Storage backend (local volume, generated names, atomic write, path-escape guard) behind a `FileStorage` interface
- [x] Loaders: PDF (PyMuPDF), TXT, Markdown, DOCX (python-docx, tables in order), with limits on pages, unpacked size and extracted text
- [x] Scanned-PDF detection ("OCR required"); password-protected and corrupt PDFs fail with a readable message
- [x] Text cleaning (NFC, newlines, control/invisible characters, line-break hyphens, spacing)
- [x] Page-aware chunking (configurable size/overlap; chunks never cross pages)
- [x] Celery ingestion task: claim → process → atomic replace; retries on database errors with backoff; idempotent; late acknowledgement
- [x] Document upload / list / detail / status / retry / delete endpoints (foreign ids return 404)
- [x] Migration `0002`: `total_pages`, `total_chunks`, unique `(user_id, content_sha256)`
- [x] Unit tests: validation, cleaning, chunking, each loader, storage, pipeline success / failure / repeat / deleted-meanwhile, API incl. isolation, duplicates, broker outage
- [x] Integration tests (`tests/integration/test_documents_flow.py`) against real PostgreSQL — **passing in CI**: each file type end to end with page numbers, repeat and redelivery leave no duplicates, a failed write keeps the previous chunks, delete cascades, isolation, broker outage then retry, migration `0002` up/down
- [x] Compose smoke test still healthy with the shared `uploads` volume — **passing in CI**
- **Exit:** uploading each file type yields correct chunks with page numbers; a
  failed or repeated job leaves no partial or duplicate chunks — **met (CI green, 2026-11-13)**.

CI caught one defect the fakes could not: after a status change, `documents.updated_at`
(database-generated) was expired, and the async session cannot lazy-load it when the response
is built (`MissingGreenlet`). Fixed with `eager_defaults` on `Document`.

Deviations from the plan: PyMuPDF is pinned to 1.28 (2.x pulls in onnxruntime and numpy);
chunk size and overlap are measured in characters, not tokens (no tokenizer is needed until
Phase 4); `total_pages` stays NULL for formats without pages. Not covered here: the Next.js
proxy's request-body limit and any edge/proxy body limit (Phase 7 and Phase 10).

## Phase 4 — Embeddings and Vector Database

Status: **complete and verified in CI (commit `ce589b8`, 2026-11-14).** 220 unit tests, ruff and
mypy strict pass; 45 database integration tests pass locally (pgvector 0.6.2) and in CI
(pgvector 0.8.7, including the iterative-scan test); the Compose smoke test builds the image with
the local model and runs upload → embed → search → second user gets nothing end to end. The real BGE
model scores a relevant passage 0.82 against 0.27 / 0.25 for unrelated ones.
The first CI run (`7acb6bd`) failed on a test-isolation bug (unit tests starting the app read rows
left by the integration tests, and the startup guard correctly refused them); fixed in `ce589b8`.

- [x] `EmbeddingProvider` interface (`app/embeddings/base.py`): `model_id`, `dimension`, `embed_documents`, `embed_query`; `EmbeddingUnavailableError` (retried) vs `EmbeddingError` (permanent)
- [x] SentenceTransformers (BGE-small) provider: lazy load, normalised vectors, instruction prefix on queries only; optional extra `local-embeddings`, CPU-only PyTorch on Linux
- [x] OpenAI embeddings provider: batching, `dimensions` for `text-embedding-3-*`, transient vs permanent errors — tested with a mocked client, **not run against the real API**
- [x] Dimension/model startup guard (`app/embeddings/guard.py`): refuses to start on a column-dimension mismatch or ready documents embedded by another model; warns about ready documents without vectors
- [x] Embedding step added to ingestion: embedded before the transaction; vectors and `embedding_model` written by the same atomic `replace_chunks`
- [x] pgvector cosine search with user and optional document filters (`app/retrieval/`); `user_id` only from the token
- [x] HNSW index (`vector_cosine_ops`, m=16, ef_construction=64), migration `0003`
- [x] `POST /search` (`query`, `top_k` 1–50, optional `document_ids`)
- [x] `python -m app.scripts.reindex`: resets ready documents embedded by another model, erases their vectors and re-queues them
- [x] Tests: providers (OpenAI mocked), config, guard, pipeline embedding paths, search API (validation, auth, isolation, 503), real-database search / ranking / index / guard / reindex / migration, real BGE model (skipped unless the extra is installed)
- [x] `hnsw.iterative_scan` keeps filtered search complete when other users dominate the index — its test skips below pgvector 0.8 and runs in CI
- [x] Compose: image builds with the local model, `models` volume, end-to-end step (upload → ready → search → second user gets nothing) — verified in CI
- **Exit:** a query returns the expected chunks for the owning user and nothing for
  another user — met by the isolation tests (unit, real database and the CI end-to-end step).

Deviations from the plan: `VectorStore` is the read side only — vectors are written by the
ingestion transaction so a document is never half-indexed. LangChain is not used for
embeddings (the adapters are small and fully typed). The startup guard runs in the API only; a
worker started with a different model than the API is not detected (both read the same `.env`).
There is no minimum-score cut-off yet (Phase 5 tunes it with real questions). `/search` has no
rate limit until Phase 10.

## Phase 5 — RAG Engine

Status: **implemented and verified in CI (commit `625c9b8`, 2026-11-15): frontend, backend (lint,
types, tests incl. the pgvector 0.8 test) and the Compose smoke test all green.** Locally: 328
passed, 1 skipped. **Not yet run against the real Gemini API** — that needs your key (see below),
so the "cited answer from a real model" half of the exit criterion is still open. CI never calls
a model (no key there), so the Compose smoke test does not exercise `/ask`.

- [x] Retrieval for answering (`RagService`): top-K, minimum-score threshold (`RETRIEVAL_SCORE_THRESHOLD`, 0.45) and document filters on top of `SearchService`; `user_id` only from the token
- [ ] Reranker hook — **deferred to Phase 9** with hybrid search and reranking (nothing to plug in yet)
- [x] Prompt builder (`app/rag/prompt_builder.py`): rules-only system message; retrieved text in the user message inside `<documents><passage number file page>` tags that document text cannot close; untrusted-data and no-reveal rules; exact "not found" sentence
- [x] `LLMProvider` interface (`app/llm/base.py`) and one OpenAI-compatible adapter (Gemini by default; also OpenAI, Groq, OpenRouter, Ollama); temporary failures (`LLMUnavailableError`) vs permanent (`LLMError`)
- [x] Grounded generation with a no-evidence short-circuit: nothing above the threshold → "not found" **without calling the model**
- [x] Citation parsing (`app/rag/citations.py`): `[n]` markers the model invented are stripped, sources are only the passages actually cited, `grounded=false` when nothing is cited or the model says it doesn't know
- [x] History window (`CHAT_HISTORY_MAX_MESSAGES`, user/assistant roles only, old `[n]` markers stripped) and context budget (`MAX_CONTEXT_CHARS`, best passage always kept)
- [x] `POST /api/v1/ask` (stateless: `question`, optional `history`, `document_ids`, `top_k`) → `answer`, `grounded`, `sources[]`; 503 `service_unavailable` (no internals) when the model is missing, busy or rejects the request
- [x] `python -m app.scripts.check_llm`: lists the models your key can use and sends one test request (never prints the key)
- [x] Tests: prompt construction and injection fixture, citations, insufficient evidence, provider error mapping (SDK client mocked), service, API with real `SearchService` and in-memory vectors, and against real pgvector (second user gets "not found", model not called)
- [ ] **Manual run with a real model** — your step: put `LLM_API_KEY` in `.env`, run `python -m app.scripts.check_llm`, then ask a question (README)
- **Exit:** end-to-end pipeline test (fake LLM) passes — met locally; a manual run with a real
  LLM gives a cited answer — **open**.

Deviations from the plan: one OpenAI-compatible adapter instead of separate OpenAI and Ollama
providers, selected by `LLM_BASE_URL` / `LLM_MODEL` (there is no `LLM_PROVIDER`), because every
target speaks the same protocol. `/ask` is stateless; stored conversations and streaming are
Phase 6. There is no question-rewriting step, so a follow-up like "and the second one?" is
searched as written (Phase 9; it would also spend a second free-tier request per question). The
0.45 threshold is a starting point, not tuned on real documents (the Phase 9 evaluation did not address it; see `docs/roadmap.md`). The
default model name `gemini-3.5-flash-lite` came from Google's docs on 2026-11-14 and is not
confirmed to be on the free tier for your key — `check_llm` shows what you can use. The context
budget counts characters, not tokens. Documents are not scanned for injection beyond the
prompt-level defences; those reduce but cannot eliminate the risk.

## Phase 6 — Chat API

Status: **implemented and verified in CI (commit `fa96aa7`, 2026-11-16) and locally: 336 unit + 57 integration tests passed
(1 skipped: the pgvector 0.8 test, which only runs in CI); ruff, format and mypy clean. The first push (`05453d8`) failed CI on one wrong
assertion in a new unit test; after the fix, all CI jobs are green.** Streaming was checked with `curl -N` against the real routers and
SSE code with a deliberately slow scripted model (tokens arrived about 0.5 s apart, then one
`done`). **Streaming from the real Gemini API is not verified** — that needs your key, like the
open Phase 5 step.

- [x] Conversation CRUD: create (title optional), list (`limit`/`offset`, newest activity first, `total`), get, rename, delete (cascades to messages and sources)
- [x] Message persistence with sources: question, answer and one `message_sources` row per cited passage are saved in one transaction; a failed or interrupted answer saves nothing
- [x] Non-streaming chat endpoint `POST /chat/{id}/messages` (history comes from the stored conversation, never from the client)
- [x] SSE streaming endpoint `POST /chat/{id}/stream`: `token` events, one `done` (same body as the non-streaming response), or `error`; failures before the first token are normal HTTP errors; no database connection is held while the model writes
- [x] Analytics overview `GET /analytics/overview` (documents by status, chunks, conversations, messages, cited answers, last 7 days)
- [x] Pagination and consistent error schema (`{"error": {"code", "message"}}` everywhere, including the SSE `error` event)
- [x] Tests: ownership of every chat route (cross-user 404, rows untouched, model not called), streaming protocol and failure modes, provider streaming (SDK mocked), RAG streaming, and against real PostgreSQL: paging, one-transaction save, cascade delete, document deletion unlinks sources, analytics counts per user
- **Exit:** API test suite passes — met locally; streaming verified with `curl` — met against a scripted model (real model: **open**).

Deviations from the plan: the question is saved together with the answer, not before it
(architecture §7.6), so history never holds a question without an answer. Saved sources keep
filename, page and score but not the passage text (deleting a document removes its content), so
a reloaded conversation shows no excerpts. Streaming is not resumable. Titles are the first
question (cut to 200 characters), not model-generated. There is still no rate limit (Phase 10).

## Phase 7 — Frontend Foundation

Status: **implemented and checked locally; not yet committed, so not yet verified in CI.**
Frontend: `tsc`, ESLint and `next build` clean, 38 Vitest tests pass. The UI was driven in a real
browser against the real FastAPI app and PostgreSQL + pgvector (Celery/Redis and the embedding
model were replaced by a thread and the test embedder, so no Docker stack was involved).

- [x] Design tokens (OKLCH), light/dark/system themes with no first-paint flash, app shell (sidebar on desktop, bottom tabs on mobile)
- [x] Landing page
- [x] Login and registration (React Hook Form + Zod; a 409 shows on the email field) — register → auto-login → dashboard checked in the browser
- [x] API client: in-memory access token, single-flight refresh, one 401→refresh→retry, session restore from the refresh cookie after a full reload (checked); TanStack Query
- [x] Dashboard (analytics overview)
- [x] Document library: drag-and-drop/choose, upload progress, status polling (queued → ready without a refresh, checked), search, status filter, retry, delete with confirmation
- [x] Settings page and `user_settings` API (`GET/PATCH /settings`, migration 0004): retrieval values and theme saved to the account, survive a reload, reset to defaults (all checked)
- [x] Responsive layouts: 375 px width has no horizontal overflow; an upload completed there
- [x] Tests: API client (refresh, retry, 204, network errors), validation schemas, document filtering, polling rules
- **Exit:** register → upload → see processing complete, on desktop and mobile widths — met locally.

Bugs the browser run found and fixed: Next truncated proxied request bodies at 10 MB, so uploads
between 10 and 25 MB failed (`experimental.proxyClientMaxBodySize` is now 30 MB, just above the
API's 25 MiB limit); the client-side fallback upload limit said 10 MB (now 25 MB, replaced by the
server's real value once `/settings` loads); the delete dialog lost the file name while fading out.

Not yet done or verified: **logout** was not exercised in the browser (it is covered only by the
code path and the client tests); the full backend suite has not been rerun since `deps.py` changed
(baseline 336 unit + 57 integration); CI later ran green on Phases 7-9, including the Docker Compose smoke test (2026-11-18).

Deviations from the plan: the documents API has no search parameter, so search and the status
filter work on the newest 100 documents already loaded (the page says so when there are more);
server-side search is a later change. Theme is stored in `localStorage` for instant paint and in
the account so it follows the user to other devices. Pages under the signed-in area render on the
client (the token lives only in memory), so they opt out of Next's instant-navigation check
(`instant = false` on the `(app)` layout).

## Phase 8 — Chat Interface

- [x] Chat layout and conversation sidebar (rename, delete, mobile drawer)
- [x] Message components with sanitised Markdown (no raw HTML, safe links)
- [x] Streaming rendering (own SSE parser, 8 unit tests incl. split CRLF/multibyte)
- [x] Source citations (clickable `[n]` chips open and highlight the source entry). The API stores no excerpt, so entries show file, page and relevance.
- [x] Document scope selector
- [x] Copy / retry; loading and error states
- [x] Playwright tests: 12 desktop journey tests + 1 phone-width test, run locally against the real API and Postgres (only the models are stand-ins, `backend/tests/e2e_server.py`)
- [x] CI: `npm test` added to the frontend job; new `e2e` job (not yet run on GitHub)
- **Exit:** full journey passes in Playwright locally (13/13). **Not yet verified on CI.**

Bugs found by running the real stack (fixed):
- `next start` gzip buffered the SSE stream, so answers arrived all at once. The stream now sends `Cache-Control: no-transform`; an e2e test asserts the answer grows in several steps.
- `SET hnsw.iterative_scan` made search return 500 on pgvector older than 0.8; it is now attempted in a savepoint and skipped with a warning.
- The scope selector showed "All documents" with every box unticked; they now show ticked.

Local caveat: `tests/unit/test_real_embedding_model.py` could not be collected here (a file missing from the venv); the other 354 unit tests, ruff, ruff format and mypy pass. Backend integration tests were not re-run after the vector-store change.

## Phase 9 — Advanced RAG

- [x] Hybrid search: PostgreSQL full-text (generated `tsvector` + GIN, migration 0005) and vector search merged with Reciprocal Rank Fusion; `RETRIEVAL_MODE` = vector | keyword | hybrid
- [x] Configurable top-K (per request and per user, as before) and candidate pool (`RETRIEVAL_CANDIDATE_MULTIPLIER`)
- [x] Metadata filters: `document_ids` (document-specific retrieval), `content_types`, `page_from`/`page_to`; one SQL helper (`retrieval/filters.py`) used by both searches, always scoped to the caller
- [x] Reranking: `Reranker` protocol + `LexicalReranker` (cosine + term coverage). **Off by default**: it did not improve on hybrid in the evaluation, and weight 0.5 lowered Recall@1 (see `docs/evaluation.md`)
- [x] Follow-up question condensing (one extra model call, falls back to the user's words on any failure; `QUERY_CONDENSING`)
- [~] Chunking: compared five size/overlap settings on the evaluation set; none beat the current 1500/200, so the chunker is unchanged. No new chunking technique was added
- [x] Evaluation harness (`app/evaluation`, `python -m app.scripts.evaluate`): 18 synthetic documents, 44 labelled questions, Recall@1/3/5 and MRR, per question type
- [x] Comparison of five retrieval configurations, a reranker-weight sweep and five chunk sizes with the real embedding model → `docs/evaluation.md`
- [ ] Groundedness and citation correctness (need an LLM judge; not measured, no number claimed)
- **Exit:** evaluation report with measured numbers for at least three configurations: **met** (`docs/evaluation.md`).

Verified (local PostgreSQL 16 + pgvector 0.6.2, real `bge-small-en-v1.5`):
- 22 keyword/filter integration tests (tsvector, stemming, exact codes, OR semantics, ranking, per-user isolation, hostile query strings, document/page/file-type filters) and the migration-matches-models test
- 7 evaluation integration tests, 13 evaluation unit tests, 8 query-condensing tests, hybrid/fusion/reranker unit tests

Findings worth remembering:
- Vector search ranks `E-4471` and `AES-256` below position 1; keyword search misses 2-3 paraphrases; hybrid missed none. That is the case for hybrid, measured.
- The evaluation set is small and saturated (Recall@3 = 100% everywhere), so it cannot separate hybrid from hybrid + rerank or one chunk size from another. This is stated in the report.
- **Windows long paths:** the `.venv` inside the OneDrive folder exceeds the 260-character path limit, so importing `transformers` fails (`FileNotFoundError` for a file that exists). Workaround used here: `subst X: <backend folder>` and run Python from `X:\`. Not a project bug; a short checkout path or enabling long paths avoids it.

## Phase 10 — Production Readiness

- [x] Security review against the threat table (`docs/architecture.md` §8): each row checked against the code; new rows added for headers, dependencies and containers; gaps listed in `docs/operations.md` §7
- [x] Rate limiting: Redis fixed-window limiter, fails open; login (per IP and per e-mail), register, refresh, upload, ask/chat, search; 429 with `Retry-After` in the standard error shape
- [x] Structured logging: request id on every log line and response header, `LOG_FORMAT=json`, one access-log line per request without query strings or bodies, uniform 500 with a reference id
- [~] Error monitoring: the hook exists (one catch point in `RequestContextMiddleware`) and is documented; **no tracker is installed or enabled**
- [x] Security headers on API responses and web pages (CSP in production builds; HSTS in production). Known gap: page CSP allows `'unsafe-inline'`
- [x] Database: indexes reviewed (no new ones needed), bounded connection pool, connection recycling, 30 s statement timeout on API queries (integration-tested against PostgreSQL)
- [x] Docker hardening: `no-new-privileges`, `cap_drop: ALL`, read-only root filesystem + tmpfs, API port on loopback, `FORWARDED_ALLOW_IPS`, `--no-access-log`. Not runnable locally (no Docker here); verified by the CI Compose smoke test, which starts the hardened stack and runs register/login, a worker task and upload, embedding and search with the real model
- [x] CI/CD: `pip-audit` + `npm audit` workflow (push, pull request, weekly), Dependabot for Python, npm, Actions and Docker. A release/image-publishing workflow was deliberately not added (could not be tested)
- [x] Docs: `docs/operations.md`
- **Exit:** CI green including integration tests and Compose smoke test: **met on `4c1297d`** (CI and Dependency audit workflows both green). The first push (`e5462f3`) failed the Compose smoke test: Compose passes unset optional variables as empty strings and `ENABLE_API_DOCS=""` was not a valid boolean, so the migrate container crashed. Fixed with a validator and a regression test; CI now also prints each service's last log lines as annotations on failure.

Verified locally (Windows, PostgreSQL 16 + pgvector 0.6.2, no Docker):
- 450 unit tests (new: limiter rules/windows/Redis behaviour and fail-open, middleware, request ids, JSON log format, 429 behaviour on real routes, config validation) and 93 integration tests (new: statement timeout and pool bounds)
- ruff, ruff format and mypy clean; 13 Playwright tests pass in Edge against a production build with the new CSP and headers
- `pip-audit` (pinned runtime requirements) and `npm audit --omit=dev`: no known vulnerabilities on 2026-11-18

Findings worth remembering:
- Behind the Next.js proxy every request reaches the API from the frontend container, so per-IP limits would count all users as one client unless uvicorn trusts `X-Forwarded-For`. Compose now sets `FORWARDED_ALLOW_IPS=*` and publishes the API on `127.0.0.1` only; `docs/operations.md` explains when `*` is unsafe.
- Tests default to `RATE_LIMIT_ENABLED=false` (the limiter keeps state, so it would leak between tests); the rate-limit tests opt in with an in-memory limiter and tiny limits.

## Phase 11 — Portfolio Presentation

- [x] README with diagrams and screenshots: rewritten (overview, problem, features, architecture and pipeline diagrams, stack, schema, screenshots, quick start incl. the Windows long-path caveat, configuration, Docker, API, testing, deployment, limitations). Concrete claims were checked against the code. The screenshots predate Phase 11 and come from the stand-in LLM; the README says so.
- [x] Remaining docs complete: `docs/decisions.md`, `docs/deployment.md` (secrets, HTTPS, persistent storage, backups, monitoring), `docs/roadmap.md`. The deployment steps are standard practice for this layout but have **not** been run on a real server (the doc says so).
- [x] Demo dataset and seed script: three fictional Markdown policies and a 3-page fictional PDF in `demo/documents`, `scripts/seed_demo.py` (stdlib only, idempotent), `demo/README.md` with questions and expected answers. Verified locally against the real API on PostgreSQL with the stand-in embedder: account created, four files uploaded and `ready` (1 + 1 + 1 + 3 passages), search finds the expected documents (page 3 for `E-4471`). With that stand-in embedder `/ask` refused every sample question because short questions score below the 0.45 threshold against whole-document passages; that is a property of the stand-in, **not** evidence about the real model. A CI step now replays the README command on the Compose stack with the real embedding model and asserts the top search hit for four questions; its result is recorded below once CI has run.
- [x] Demo video script: `docs/demo-script.md` (about 4 minutes, shot list and narration). The video itself is not recorded.
- [x] Interview talking points: `docs/interview.md`, including what not to claim.
- [~] **Exit:** a new developer can run the project from the README alone. The README commands are replayed by CI (stack start, auth, upload, search, demo seed), but no person has followed it on a clean machine yet.

CI result (`b5b6261`, all four jobs green): the compose smoke test ran the README commands with the real embedding model, including the new demo-dataset step (seed script, a re-run that skips all four files, and the expected file and page as the top search hit for each of the four demo questions). The first Phase 11 run (`2c31a61`) had a red Playwright job with no readable cause; the same job passed on the next commit with no app or test change, so it was most likely a flake (not proven). The browser job now reports failures and server-log tails as annotations so a repeat is diagnosable.

Corrections made while writing: `.env.example` and this file claimed the relevance threshold would be tuned in Phase 11; nothing in the evaluation tuned it, so both now say it is untuned.

---

## Definition of Done (project)

Evidence: unit, integration and browser tests plus the Compose smoke test, all in CI.
`[~]` marks items verified only with a stand-in language model or only by replaying the
commands in CI.

- [x] Register and log in
- [x] Upload supported documents
- [x] Asynchronous processing (real worker in the Compose smoke test)
- [x] Correct text extraction
- [x] Appropriate chunking (five sizes compared; the evaluation set is saturated, so this shows no size is wrong, not that one is best)
- [x] Embeddings generated and stored in pgvector (real model in CI)
- [x] Semantic retrieval works (hybrid; measured in `docs/evaluation.md`)
- [~] Questions answered from documents, grounded in retrieved context (pipeline tested with a stand-in LLM; no real-Gemini run recorded)
- [~] Accurate source citations (marker-to-passage resolution tested; not checked against real model output)
- [~] Streaming works (SSE tested end to end in the browser with the stand-in LLM; not against Gemini)
- [x] Conversations persisted
- [x] User data isolated (tests plus the Compose smoke test)
- [x] Frontend works on desktop and mobile (browser tests, mobile layout screenshot)
- [x] Automated tests pass (CI green on `b5b6261`, Phase 11 included)
- [x] Docker Compose starts the application (CI)
- [x] Documentation complete
- [~] New developer can run it from the README (commands replayed in CI; no human fresh run)

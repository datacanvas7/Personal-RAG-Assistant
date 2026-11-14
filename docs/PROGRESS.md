# Project Progress — Personal RAG Assistant

Updated at the end of every phase. A box is ticked only when the item is implemented
**and verified** (tests or a documented manual check).

Legend: `[x]` done and verified · `[ ]` not started · `[~]` in progress · `[!]` blocked

Current phase: **Phase 4 — complete and verified in CI; awaiting approval to start Phase 5** (2026-11-14)

---

## Open blockers

- [x] Docker location decided: **GitHub Codespaces** (no local Docker / WSL2 needed)
- [x] Python 3.13 provided by `uv` (no admin needed); host Python 3.10 left untouched
- [x] Repo pushed to GitHub (datacanvas7/Personal-RAG-Assistant)
- [ ] Decide LLM for development: OpenAI key or Ollama
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

- [ ] Retrieval service (top-K, threshold, filters, reranker hook)
- [ ] Prompt builder (grounding + injection rules, numbered context)
- [ ] `LLMProvider` interface; OpenAI provider; Ollama provider
- [ ] Grounded generation with no-evidence short-circuit
- [ ] Citation parsing and structured sources
- [ ] Conversation history window and context budget
- [ ] Tests: prompt construction, citations, insufficient evidence, injection fixture
- **Exit:** end-to-end pipeline test (fake LLM) passes; a manual run with a real
  LLM gives a cited answer.

## Phase 6 — Chat API

- [ ] Conversation CRUD
- [ ] Message persistence with sources
- [ ] Non-streaming chat endpoint
- [ ] SSE streaming endpoint
- [ ] Analytics overview endpoint
- [ ] Pagination and consistent error schema
- [ ] Tests: chat APIs, streaming, ownership checks
- **Exit:** API test suite passes; streaming verified with `curl`.

## Phase 7 — Frontend Foundation

- [ ] Design tokens, light/dark themes, app shell
- [ ] Landing page
- [ ] Login and registration (React Hook Form + Zod)
- [ ] API client with token refresh; TanStack Query setup
- [ ] Dashboard
- [ ] Document library (drag-and-drop, progress, status polling, search, delete)
- [ ] Settings page and `user_settings` API
- [ ] Responsive layouts
- **Exit:** register → upload → see processing complete, on desktop and mobile widths.

## Phase 8 — Chat Interface

- [ ] Chat layout and conversation sidebar
- [ ] Message components with sanitised Markdown
- [ ] Streaming rendering
- [ ] Source citations with expandable excerpts
- [ ] Document scope selector
- [ ] Copy / retry; loading and error states
- [ ] Playwright tests: auth, upload, library, chat, citations
- **Exit:** full user journey passes in Playwright.

## Phase 9 — Advanced RAG

- [ ] Hybrid search (full-text + vector, RRF)
- [ ] Reranking
- [ ] Follow-up question condensing
- [ ] Chunking improvements
- [ ] Evaluation dataset; Recall@K, MRR, groundedness, citation correctness
- [ ] Comparison of retrieval configurations → `evaluation.md`
- **Exit:** evaluation report with measured numbers for at least three configurations.

## Phase 10 — Production Readiness

- [ ] Security review against the threat table
- [ ] Rate limiting
- [ ] Structured logging, request IDs, error monitoring hook
- [ ] Database and query optimisation
- [ ] Docker hardening (non-root, multi-stage, image size)
- [ ] Full CI/CD pipeline
- **Exit:** CI green including integration tests and Compose smoke test.

## Phase 11 — Portfolio Presentation

- [ ] README with diagrams and screenshots
- [ ] Remaining docs complete
- [ ] Demo dataset and seed script
- [ ] Demo video script
- [ ] Interview talking points
- **Exit:** a new developer can run the project from the README alone.

---

## Definition of Done (project)

- [ ] Register and log in
- [ ] Upload supported documents
- [ ] Asynchronous processing
- [ ] Correct text extraction
- [ ] Appropriate chunking
- [ ] Embeddings generated and stored in pgvector
- [ ] Semantic retrieval works
- [ ] Questions answered from documents, grounded in retrieved context
- [ ] Accurate source citations
- [ ] Streaming works
- [ ] Conversations persisted
- [ ] User data isolated
- [ ] Frontend works on desktop and mobile
- [ ] Automated tests pass
- [ ] Docker Compose starts the application
- [ ] Documentation complete
- [ ] New developer can run it from the README

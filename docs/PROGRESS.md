# Project Progress — Personal RAG Assistant

Updated at the end of every phase. A box is ticked only when the item is implemented
**and verified** (tests or a documented manual check).

Legend: `[x]` done and verified · `[ ]` not started · `[~]` in progress · `[!]` blocked

Current phase: **Phase 1 — code complete; Docker verification pending** (2026-11-13)

---

## Open blockers

- [x] Docker location decided: **GitHub Codespaces** (no local Docker / WSL2 needed)
- [x] Python 3.13 provided by `uv` (no admin needed); host Python 3.10 left untouched
- [!] Repo is not on GitHub yet — Codespaces and CI need it pushed (see Phase 1)
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
- [ ] **Not yet verified (no Docker on this machine):** `docker compose up --build --wait`, pgvector extension present, worker answers `ping`, CI green
- [ ] Push to GitHub, open a Codespace, run the verification commands in the README
- **Exit:** `docker compose up --build` starts all five services healthy; frontend
  shows backend health; worker executes the ping task.

## Phase 2 — Database and Authentication

- [ ] SQLAlchemy models for all entities
- [ ] Alembic configured; initial migration (incl. `CREATE EXTENSION vector`)
- [ ] Register, login, refresh (rotation), logout, `/auth/me`
- [ ] Argon2id hashing; JWT validation dependency
- [ ] Auth tests (happy paths, bad credentials, expired/revoked tokens)
- **Exit:** migrations apply to an empty DB; auth test suite passes.

## Phase 3 — Document Ingestion

- [ ] Upload endpoint with validation (extension, magic bytes, size, empty)
- [ ] Storage backend (local volume)
- [ ] Loaders: PDF, TXT, Markdown, DOCX
- [ ] Scanned-PDF detection ("OCR required")
- [ ] Text cleaning
- [ ] Page-aware chunking (configurable size/overlap)
- [ ] Celery ingestion task: status transitions, retries, idempotency, atomic write
- [ ] Document list / detail / status / delete endpoints
- [ ] Tests: upload, each loader, cleaning, chunking, failure paths
- **Exit:** uploading each file type yields correct chunks with page numbers; a
  failed or repeated job leaves no partial or duplicate chunks.

## Phase 4 — Embeddings and Vector Database

- [ ] `EmbeddingProvider` interface
- [ ] SentenceTransformers (BGE-small) provider
- [ ] OpenAI embeddings provider
- [ ] Dimension/model startup guard
- [ ] Embedding step added to ingestion
- [ ] pgvector similarity search with user and document filters
- [ ] HNSW index
- [ ] `/search` endpoint
- [ ] Tests: providers (mocked for OpenAI), retrieval, **user isolation**
- **Exit:** a query returns the expected chunks for the owning user and nothing for
  another user.

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

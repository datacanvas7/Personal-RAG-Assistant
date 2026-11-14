# Personal RAG Assistant

Upload your own documents (PDF, TXT, Markdown, DOCX) and ask questions about them. Answers are
generated from retrieved passages of *your* documents only and come with citations.

> **Status: Phase 5 of 11 — question answering.** Accounts, login, document upload and
> processing exist, your documents can be searched semantically, and `POST /ask` answers
> questions with citations (needs a free Gemini key); there is no saved chat or UI yet.
> See [docs/PROGRESS.md](docs/PROGRESS.md) for what works and
> [docs/architecture.md](docs/architecture.md) for the design. This README grows with the project.

## Run it

Requires Docker with Compose v2. In GitHub Codespaces this is already set up
(`.devcontainer/devcontainer.json`).

```bash
cp .env.example .env        # the Codespaces container does this for you
docker compose up --build --wait
```

| What | Where |
|---|---|
| Frontend | http://localhost:3000 — shows the live health of every service |
| API docs (Swagger) | http://localhost:8000/api/v1/docs |
| Health endpoint | http://localhost:8000/api/v1/health (503 when a dependency is down) |

Database migrations run automatically: a one-shot `migrate` container applies
`alembic upgrade head` before the API and worker start. If you had a `.env` from an
earlier phase, add the new variables from `.env.example` (at least `JWT_SECRET_KEY`; Phase 4
adds the optional `EMBEDDING_*` ones, Phase 5 the `LLM_*` and `RETRIEVAL_*` ones).

Try the auth API (Swagger UI at `/api/v1/docs` works too):

```bash
curl -s -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a-long-passphrase"}'
curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a-long-passphrase"}'   # returns access_token
curl -s localhost:8000/api/v1/users/me -H "Authorization: Bearer <access_token>"
```

Upload a document (PDF, DOCX, TXT or Markdown, up to 25 MiB) and watch it being processed:

```bash
curl -s -X POST localhost:8000/api/v1/documents/upload -H "Authorization: Bearer <access_token>" \
  -F "file=@report.pdf"                                   # 202, status "pending"
curl -s localhost:8000/api/v1/documents/<id>/status -H "Authorization: Bearer <access_token>"
```

Once the document is `ready`, search your own documents (POST, so the query stays out of URLs):

```bash
curl -s -X POST localhost:8000/api/v1/search -H "Authorization: Bearer <access_token>" \
  -H 'Content-Type: application/json' -d '{"query": "how often must I change my password?", "top_k": 3}'
```

Ask a question and get an answer built only from your own documents, with sources:

```bash
curl -s -X POST localhost:8000/api/v1/ask -H "Authorization: Bearer <access_token>" \
  -H 'Content-Type: application/json' -d '{"question": "How often must I change my password?"}'
# {"answer": "Every 90 days [1].", "grounded": true,
#  "sources": [{"number": 1, "filename": "policy.pdf", "page_number": 3, "excerpt": "...", ...}]}
```

If your documents don't contain the answer you get "I couldn't find this in your documents."
(`grounded: false`, no sources). To follow up, send the earlier turns as `history`
(`[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]`).

`/ask` needs a language model. The default is Google Gemini, which has a free tier: create a
key at https://aistudio.google.com/apikey, put it in `.env` as `LLM_API_KEY=...` (never commit
it) and restart the stack. Without a key everything else works and `/ask` answers 503. Gemini
renames and retires models often, so check what your key can use right now:

```bash
docker compose run --rm backend python -m app.scripts.check_llm
```

If it warns that the model isn't available, set `LLM_MODEL` in `.env`. Any OpenAI-compatible
service works by changing `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY` (see `.env.example`).
Note that the text of the passages found for a question is sent to that service.

The first document you process downloads the local embedding model (about 130 MB, kept in
the `models` volume). To use OpenAI instead, set `EMBEDDING_PROVIDER=openai` and
`OPENAI_API_KEY` in `.env`. If you change the embedding model later, the API refuses to start
until you run the re-index, then wait for the worker to finish:

```bash
docker compose run --rm backend python -m app.scripts.reindex
```

Check the worker executes tasks:

```bash
docker compose exec backend python -c "from app.workers.tasks import ping; print(ping.delay().get(timeout=20))"
```

Stop with `docker compose down` (add `--volumes` to delete the database and uploads).

## Develop

Backend (Python 3.13, managed by [uv](https://docs.astral.sh/uv/)):

```bash
cd backend
uv sync
uv run pytest            # unit tests need no database or Redis; the database
                         # integration tests run only when POSTGRES_DB ends in _test (CI)
uv run ruff check . && uv run ruff format --check . && uv run mypy app tests alembic
```

Frontend (Node 24):

```bash
cd frontend
npm ci
npm run dev              # hot reload on :3000; proxies /api/v1 to http://localhost:8000
npm run lint && npm run typecheck && npm run build
```

Change the schema: edit the models, then
`uv run alembic revision --autogenerate -m "what changed"` (needs a running database), review the
generated file, and commit it. CI fails if the models and migrations disagree.

When you change backend dependencies, run `uv lock` and then
`uv export --frozen --no-dev --no-hashes --no-emit-project --no-header -o requirements.txt`
(CI fails if `requirements.txt` is out of date).

## Layout

```
backend/    FastAPI API + Celery worker (one codebase, one image, two commands)
frontend/   Next.js (App Router) — proxies /api/v1/* to the backend
docker/     Container configuration (Postgres init)
docs/       Architecture, progress, and per-topic documentation
```

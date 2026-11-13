# Personal RAG Assistant

Upload your own documents (PDF, TXT, Markdown, DOCX) and ask questions about them. Answers are
generated from retrieved passages of *your* documents only and come with citations.

> **Status: Phase 2 of 11 — database and authentication.** Accounts, login and protected
> endpoints exist; there is no UI or document feature yet. See [docs/PROGRESS.md](docs/PROGRESS.md) for what works and
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
earlier phase, add the new variables from `.env.example` (at least `JWT_SECRET_KEY`).

Try the auth API (Swagger UI at `/api/v1/docs` works too):

```bash
curl -s -X POST localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a-long-passphrase"}'
curl -s -X POST localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a-long-passphrase"}'   # returns access_token
curl -s localhost:8000/api/v1/users/me -H "Authorization: Bearer <access_token>"
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

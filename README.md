# Personal RAG Assistant

Upload your own documents (PDF, TXT, Markdown, DOCX) and ask questions about them. Answers are
generated from retrieved passages of *your* documents only and come with citations.

> **Status: Phase 1 of 11 — project foundation.** The services start and report their health;
> no product features exist yet. See [docs/PROGRESS.md](docs/PROGRESS.md) for what works and
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
uv run pytest            # unit tests need no database or Redis
uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
```

Frontend (Node 24):

```bash
cd frontend
npm ci
npm run dev              # hot reload on :3000; proxies /api/v1 to http://localhost:8000
npm run lint && npm run typecheck && npm run build
```

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

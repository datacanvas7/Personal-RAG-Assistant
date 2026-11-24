# Deployment guide

How to run the project on a single Linux server with Docker Compose. It covers secrets, HTTPS,
persistent storage, backups and monitoring. For runtime behaviour (logging, rate limits,
headers, known gaps) see [operations.md](operations.md).

> **What has and has not been verified.** CI builds this Compose stack and runs it end to end
> (health, auth, upload → embed → search with the real model, isolation, the demo dataset). The
> production steps below (TLS proxy, backups, restore) are standard practice written for this
> layout but **have not been exercised on a real server**; try them on a throwaway host first.

## 1. Prepare the host

* Linux with Docker Engine and the Compose v2 plugin, 2 CPU cores and at least 4 GB of RAM (the
  embedding model runs on CPU inside the worker), and 10 GB or more of disk.
* A DNS name pointing at the host (for example `rag.example.com`) and ports 80 and 443 open.
  Keep 3000, 8000, 5432 and 6379 closed to the outside; Compose already publishes the last three
  on `127.0.0.1` only.

## 2. Secrets and configuration

```bash
git clone https://github.com/datacanvas7/Personal-RAG-Assistant.git && cd Personal-RAG-Assistant
cp .env.example .env
chmod 600 .env
```

Edit `.env`. These must be set for production:

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `COOKIE_SECURE` | `true` (the app refuses to start otherwise) |
| `JWT_SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `POSTGRES_PASSWORD` | a long random value; must not start with `change-me` |
| `LLM_API_KEY` | your provider key |
| `LOG_FORMAT` | `json` if a collector reads the logs |

Startup fails loudly if a placeholder secret is still present, so a forgotten value cannot go
live silently. Treat `.env` as the secret store of a single host. On a team setup, inject the
same variables from a secrets manager (Docker/Swarm secrets, your cloud's secret store, or CI
variables) instead of a file on disk, and never commit `.env` (it is git-ignored). If a key is
ever pasted somewhere public, rotate it at the provider and replace it; changing
`JWT_SECRET_KEY` signs every user out.

```bash
docker compose up --build --wait -d
```

## 3. HTTPS

Terminate TLS in a reverse proxy in front of the **frontend** (port 3000); the browser never
needs to reach the API directly because Next.js proxies `/api/v1/*`. With Caddy, which obtains
and renews certificates automatically, the whole configuration is:

```
rag.example.com {
    reverse_proxy 127.0.0.1:3000
}
```

nginx or Traefik work the same way (proxy to `127.0.0.1:3000`, pass `Host` and
`X-Forwarded-*`, and keep response streaming unbuffered for the chat: `proxy_buffering off;` in
nginx). In production the application sends HSTS and the refresh cookie is `Secure`.

Rate limiting identifies clients by address. Behind an extra proxy, read "Client address
behind a proxy" in [operations.md](operations.md) and adjust `FORWARDED_ALLOW_IPS`; this chain
has not been tested here.

## 4. Persistent storage

Three named volumes hold state; keep them on durable disks:

| Volume | Holds | If lost |
|---|---|---|
| `pgdata` | Users, documents' metadata, chunks, vectors, conversations | Everything except the files |
| `uploads` | The original uploaded files | Documents can no longer be re-indexed or retried |
| `models` | Cache of the embedding model (about 130 MB) | Re-downloaded on next ingestion; harmless |

`docker compose down` keeps them; `docker compose down --volumes` deletes them. The local
`uploads` volume ties the deployment to **one host**; for several hosts, implement an
S3-compatible `StorageBackend` (the interface exists, see [roadmap.md](roadmap.md)).

## 5. Backups

The database and the uploaded files belong together: back both up at the same time.

```bash
# Database (custom format, restorable with pg_restore)
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > backup-$(date +%F).dump

# Uploaded files (replace "personal-rag-assistant" with your Compose project name; see `docker volume ls`)
docker run --rm -v personal-rag-assistant_uploads:/data -v "$PWD":/backup alpine \
  tar czf /backup/uploads-$(date +%F).tgz -C /data .
```

Run them from cron, copy the results off the host (object storage, another machine), and keep
several generations. Restore on a fresh stack:

```bash
docker compose up -d postgres
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < backup-2026-01-01.dump
docker run --rm -v personal-rag-assistant_uploads:/data -v "$PWD":/backup alpine \
  tar xzf /backup/uploads-2026-01-01.tgz -C /data
docker compose up -d
```

**A backup you have not restored is a hope, not a backup**: test the restore, including
signing in and asking a question, before relying on it. If you change the embedding model, the
vectors in an old dump no longer match; run `python -m app.scripts.reindex` afterwards.

## 6. Monitoring

* **Liveness and readiness.** Poll `GET /api/v1/health` through the public URL: `200` means
  Postgres, pgvector and Redis are reachable; `503` names which one is not. Point an uptime
  monitor at it.
* **Container health.** `docker compose ps` shows each service's health check; restart policies
  bring failed containers back.
* **Logs.** With `LOG_FORMAT=json`, every request line carries a request id (also returned in the
  `X-Request-ID` header, so a user's error report can be matched to a log line). Ship
  `docker compose logs` to your collector. Documents, questions, answers and tokens are never
  logged.
* **Errors.** Unexpected exceptions are logged with a traceback at `ERROR` and answered with a
  generic 500 in one place (`RequestContextMiddleware`); that is where to attach an error
  tracker. None is installed by default.
* **Worker.** A growing queue or documents stuck in `processing` mean the worker is down or slow:
  `docker compose logs -f worker`.
* **Disk.** Watch the volumes' free space; uploads and the database only grow.

## 7. Updating

```bash
git pull
docker compose up --build --wait -d      # migrations run in the one-shot `migrate` service first
```

Take a backup before upgrading. CI enforces that models and migrations agree, and dependency
audits run weekly and on every pull request (`.github/workflows/security.yml`, Dependabot).

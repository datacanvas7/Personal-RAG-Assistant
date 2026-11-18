# Operations guide

How the application protects itself and how to run it in front of real users. Everything
here is configurable through environment variables listed in `.env.example`.

## 1. Logging and request ids

Every request gets an id. It is taken from an incoming `X-Request-ID` header when that value
is a plain token (8-64 characters of `A-Za-z0-9._-`), otherwise a random one is generated.
The id is returned in the `X-Request-ID` response header and stamped on **every** log line
written while the request runs, so a user can quote it and you can find the whole story.
Unhandled errors show it too: *"Something went wrong on our side. Reference: `<id>`."*

| Setting | Values | Meaning |
|---|---|---|
| `LOG_LEVEL` | `DEBUG`..`ERROR` | Verbosity |
| `LOG_FORMAT` | `text` (default), `json` | `json` writes one object per line for a log collector |

JSON line example (access log):

```json
{"time": "2026-11-18T09:14:03.512+00:00", "level": "INFO", "logger": "app.request",
 "message": "POST /api/v1/search -> 200 (41.3 ms)", "request_id": "5f0c...e1",
 "method": "POST", "path": "/api/v1/search", "status": 200, "duration_ms": 41.3}
```

**What is logged:** method, path (never the query string), status, duration, warnings and
tracebacks for unexpected errors. **What is never logged:** passwords, tokens, document text,
questions and answers, request and response bodies. Uvicorn's own access log is switched off
(`--no-access-log`) because it would duplicate this line.

### Error monitoring

Unexpected exceptions are caught in one place, `RequestContextMiddleware`
(`backend/app/core/middleware.py`), logged with their traceback at `ERROR` and answered with
a generic 500. That is the single hook for an error tracker: initialise the vendor SDK in
`create_app()` (Sentry's ASGI/FastAPI integration, for example) or attach a logging handler
that forwards `ERROR` records. **No tracker is installed or enabled in this project**; only
the hook and the structured logs exist. If you add one, scrub request bodies and
`Authorization`/`Cookie` headers before events leave the server.

## 2. Rate limiting

Fixed-window counters in Redis (`INCR` + `EXPIRE NX`, one round trip). A refused request
gets **429** in the usual error shape, plus a `Retry-After` header; the UI shows the
message as it does any API error.

| Setting | Default | Applies to | Keyed by |
|---|---|---|---|
| `RATE_LIMIT_LOGIN_IP` | `20/1m` | `POST /auth/login` | client address |
| `RATE_LIMIT_LOGIN_EMAIL` | `10/15m` | `POST /auth/login` | e-mail address (case/space-insensitive) |
| `RATE_LIMIT_REGISTER_IP` | `10/1h` | `POST /auth/register` | client address |
| `RATE_LIMIT_REFRESH_IP` | `60/1m` | `POST /auth/refresh` | client address |
| `RATE_LIMIT_UPLOAD_USER` | `60/1h` | `POST /documents/upload` | signed-in user |
| `RATE_LIMIT_ASK_USER` | `30/1m` | `POST /ask`, chat messages | signed-in user |
| `RATE_LIMIT_SEARCH_USER` | `120/1m` | `POST /search` | signed-in user |

Format: `<count>/<window>` with window units `s`, `m`, `h` (`10/1m`, `5/15m`). A malformed
value stops the API at startup. `RATE_LIMIT_ENABLED=false` turns everything off (load tests only).

Design choices and their limits:

* **Fails open.** If Redis is unreachable or slow (>0.5 s) the request is allowed and a
  warning is logged. A cache outage should not take the application down; `/health` reports it.
* **Fixed window.** A client can use a full budget at the end of one window and again at the
  start of the next. That is acceptable for abuse protection; it is not a billing meter.
* **Per-user limits run after authentication**, so unauthenticated floods are rejected with
  401 before they touch the counters (and cannot fill Redis).
* **No account lockout.** Throttling per e-mail slows guessing; a locked account would let an
  attacker lock out the owner on purpose.

### Client address behind a proxy

Per-IP limits use the address uvicorn reports. In Docker Compose every browser request
reaches the API through the Next.js proxy, so the compose file sets
`FORWARDED_ALLOW_IPS=*` for the API (uvicorn then believes `X-Forwarded-For`, which the proxy
sets to the browser's address) **and** publishes the API port on `127.0.0.1` only, so nobody
can reach the API directly and spoof the header. If you put another reverse proxy in front,
list *its* address in `FORWARDED_ALLOW_IPS` instead of `*`, and make sure the API port is not
reachable from outside. Get this wrong in either direction and per-IP limits either count all
users as one client or can be dodged by forging a header.

## 3. Security headers

API responses (`RequestContextMiddleware`): `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`,
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (not on the Swagger UI
page, which loads its own assets), and `Strict-Transport-Security` when
`ENVIRONMENT=production`. The interactive docs (`/api/v1/docs`) are **off in production**
unless `ENABLE_API_DOCS=true`.

Web pages (`frontend/next.config.ts`): `nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`, a `Permissions-Policy` that disables camera,
microphone, geolocation and payment, and, in production builds, a
`Content-Security-Policy` limiting scripts, styles, images and connections to the site itself.

Known gap: the page CSP allows `'unsafe-inline'` for scripts and styles, because Next.js
emits inline bootstrap scripts. A nonce-based policy is stricter but forces every page to be
rendered per request (see the Next.js CSP guide). The mitigations that remain: no raw HTML is
ever rendered from model output or documents, links are sanitised, and tokens are not kept in
`localStorage`.

HSTS for the web pages belongs on whatever terminates TLS in front of the stack. Serve the
application over HTTPS only, with `COOKIE_SECURE=true`.

## 4. Database

* Indexes cover every query path: `(user_id, created_at)` on documents, `(user_id, updated_at)` on
  conversations, `(conversation_id, created_at)` on messages, HNSW on embeddings, GIN on the
  full-text vector, and a unique `(user_id, content_sha256)` that also makes duplicate
  uploads cheap to detect. Every retrieval query filters by `user_id` first.
* The API's connection pool is bounded: `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` connections per
  process (default 10 + 10), a request waits at most `DB_POOL_TIMEOUT_SECONDS`, and
  connections older than `DB_POOL_RECYCLE_SECONDS` are replaced. With several API processes
  keep `processes x (size + overflow)` plus the worker below Postgres' `max_connections`
  (100 by default).
* `DB_STATEMENT_TIMEOUT_MS` (default 30 s) cancels any API statement that runs longer, so a
  runaway query cannot hold a connection forever. The worker has no such limit: indexing and
  bulk inserts may legitimately take longer.
* Back up the `postgres_data` volume (`pg_dump`) and the `uploads` volume together; the
  database stores extracted text and vectors, the volume stores the original files.

## 5. Containers

The Compose file applies the same hardening to the API, worker, migration job and frontend:
non-root user (set in the Dockerfiles), `no-new-privileges`, all Linux capabilities
dropped, a read-only root filesystem, and a small in-memory `/tmp` (plus Next.js'
`.next/cache` for the frontend). Writable state lives only in named volumes. Only the
frontend is published to the network; the API, Postgres and Redis are bound to `127.0.0.1`.
Images are multi-stage so build tools do not ship.

## 6. Dependencies and CI

* `.github/workflows/ci.yml`: lint, types, unit + database integration tests, frontend
  build, Playwright browser tests, Docker Compose smoke test (including upload, embedding and
  search with the real embedding model).
* `.github/workflows/security.yml`: `pip-audit` on the pinned runtime requirements and
  `npm audit` (production dependencies, high severity and above), on every push and weekly,
  in its own workflow so a newly published advisory does not block unrelated pull requests.
* `.github/dependabot.yml`: weekly update pull requests for Python, npm, GitHub Actions and
  Docker images; each runs the full CI before it can be merged.

## 7. Known gaps (deliberately not built)

Stated here so nobody assumes otherwise:

* No e-mail verification or password reset (no mail server in scope).
* No malware scanning of uploads (type, size and magic-byte checks only).
* No per-user storage quota (upload count is rate-limited, total size is not capped).
* No multi-factor authentication.
* No error-tracking service, metrics endpoint or tracing; logs and `/health` are the
  observability surface.
* Single API instance assumed in the shipped Compose file; the rate limiter and sessions
  already work across instances (state is in Redis/PostgreSQL), but nothing here has been
  load-tested.

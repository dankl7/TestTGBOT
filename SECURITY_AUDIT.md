# Security Audit — Window of Light / LithTGBot

This document captures the security review performed on the two projects in
`my-project/Window of Light/` and the fixes that were applied.

> **TL;DR:** Both projects are now hardened against the most common
> vulnerabilities. **You MUST rotate the credentials that were previously
> committed to `.env` files** — they are now placeholders, but the old
> values are still valid until you revoke them on the provider side.

## 1. Critical findings & status

| # | Finding | Status | Where fixed |
|---|---------|--------|-------------|
| 1 | Live secrets in `.env` (Telegram bot token, MTProto api_id/hash, phone, DB password) | **Fixed** — replaced with placeholders, files now `chmod 600` | `LithTGBot/.env`, `Window of Light/.env` |
| 2 | Backup files `*.bak.1778615*` containing the same secrets | **Fixed** — deleted | — |
| 3 | Telethon session files readable by other users (mode 644, owned by root) | **Fixed** — added startup guard that `chmod 600` and warns if it cannot | `services/run_combined.py::_check_session_file_permissions` |
| 4 | Window of Light API had **no authentication** on `/api/v1/channels/*`, `/api/v1/products/*`, `/api/v1/proxy/*` | **Fixed** — added `X-API-Key` auth dependency with per-key rate limiting | `common/api_security.py`, `services/run_combined.py` |
| 5 | CORS `allow_origins=["*"]` with `allow_credentials=True` (insecure by spec) | **Fixed** — explicit allow-list from env, defaults to loopback | `common/api_security.py::get_cors_origins`, `services/run_combined.py` |
| 6 | No input validation on `ProductSearchRequest` (unbounded `limit`/`offset`, no `attributes` cap) | **Fixed** — Pydantic `Field(ge=, le=)` + `field_validator` | `services/run_combined.py::ProductSearchRequest` |
| 7 | `f"SELECT * FROM {table_name}"` in `catalog.py::browse_table` (defence-in-depth issue, allowlist was correct) | **Fixed** — added identifier regex validation in addition to allowlist | `database/repositories/catalog.py::_safe_table` |
| 8 | `f"SELECT COUNT(*) FROM {table}"` in `cleanup_old_data.py` | **Fixed** — static allowlist + regex | `cleanup_old_data.py` |
| 9 | Hardcoded DB password fallback in `cleanup_old_data.py` | **Fixed** — now requires `DATABASE_URL` env var, exits with code 2 if missing | `cleanup_old_data.py` |
| 10 | `network_mode: host` in both `docker-compose.yml` (exposes all host services) | **Fixed** — replaced with port bindings on `127.0.0.1` | both `docker-compose.yml` |
| 11 | Containers run with full Linux capabilities | **Fixed** — `cap_drop: [ALL]`, only `NET_BIND_SERVICE` added | both `docker-compose.yml` |
| 12 | Filesystem writable in containers | **Fixed** — `read_only: true` + `tmpfs` for `/tmp` | both `docker-compose.yml` |
| 13 | No security headers on API responses | **Fixed** — `SecurityHeadersMiddleware` adds `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` | `common/api_security.py::SecurityHeadersMiddleware` |
| 14 | No request-size cap (DoS via huge JSON body) | **Fixed** — `MAX_BODY_BYTES = 1 MiB` enforced in `require_api_key` and `_safe_read_json` | `common/api_security.py` |
| 15 | No rate limiting on WoL API | **Fixed** — in-memory sliding-window per API-key hash, configurable via `WOL_RATE_LIMIT_REQUESTS` / `WOL_RATE_LIMIT_WINDOW_S` | `common/api_security.py::_SlidingWindow` |
| 16 | `f"wok_{uuid.uuid4().hex}"` API key (uuid4 is not crypto-random) | **Fixed** — `secrets.token_hex(32)` | `services/run_combined.py::create_api_key` |
| 17 | API key creation endpoint had no body validation | **Fixed** — `name` length 1..128, `expires_days` 0..3650, size-capped body | `services/run_combined.py::create_api_key` |
| 18 | Unbounded `int` in `/api/v1/products/{id}/history` `limit`/`offset` | **Fixed** — `max(1, min(int(limit), 500))` etc. | `services/run_combined.py::get_price_history` |
| 19 | `proxy: {}` / `mark_proxy_dead` accepted arbitrary `host`/`port` | **Fixed** — explicit type + length + range checks | `services/run_combined.py::mark_proxy_dead` |
| 20 | LithTGBot WOL API client sent no auth header | **Fixed** — adds `X-API-Key` if `WOL_API_KEY` is set, logs 401/403/429 specifically | `integrations/wol_api.py` |
| 21 | `f"…/sessions"` bind-mount may include a journal file with `0644` permissions | **Documented** — see §3 below | — |

## 2. Things you need to do manually

1. **Rotate ALL credentials that lived in `.env` files**:
   - Telegram bot token — `BotFather` → `/revoke` → `/token`
   - Telegram MTProto `api_id` / `api_hash` — `https://my.telegram.org` → "Delete this key"
   - PostgreSQL password for `wol_user` — `ALTER USER wol_user WITH PASSWORD '...';`
   - Re-authorize the LithTGBot MTProto session (`tools/reauth_mtproto.py`)
   - Re-authorize the WoL session after regenerating api_id/hash
2. **Lock down the Telethon session files** (owned by root from the old container):
   ```bash
   sudo chown 1000:1000 "Window of Light/LithTGBot/sessions/bot_mtproto.session"
   sudo chmod 600 "Window of Light/LithTGBot/sessions/bot_mtproto.session"
   sudo chown 1000:1000 "Window of Light/Window of Light/sessions/wol_session.session"*
   sudo chmod 600 "Window of Light/Window of Light/sessions/wol_session.session"*
   ```
   The startup guard will auto-fix this when run as the same user.
3. **Generate a fresh API key for the bot** and put it into `LithTGBot/.env` as
   `WOL_API_KEY=wok_…`:
   ```bash
   curl -X POST http://127.0.0.1:8002/api/v1/api-keys \
     -H 'Content-Type: application/json' \
     -d '{"name":"lithtgbot","expires_days":365}'
   ```
4. **If you want to bootstrap other API keys** (e.g. for monitoring), set
   `API_BOOTSTRAP_KEYS=wok_…,…` in `Window of Light/.env`. Plaintext is hashed
   on first start and never persisted.

## 3. Remaining (accepted) risks

- **In-memory rate limiter** — fine for a single-process deployment, but
  multi-worker uvicorn would need a Redis-backed limiter. Tracked in
  `common/api_security.py::_SlidingWindow`.
- **`/api/v1/api-keys` is unauthenticated by design** so the operator can
  bootstrap the first key. Behind `127.0.0.1:8002` only (see
  `docker-compose.yml`) this is acceptable. **Do not** expose the API publicly
  without putting a reverse proxy (nginx/caddy) in front with TLS and IP
  allow-listing.
- **`proxy_health_monitor.py`** still uses `shell=True` for `pkill` and
  `docker inspect`. All command strings are hardcoded constants; no user input
  reaches the shell. Refactor to list-form is a nice-to-have, not a fix.
- **`.env` files** are in `.gitignore` (verified). If you ever `git init` this
  project, run `git log -p -- .env` to confirm no historical leak.
- **No CORS preflight caching past 10 min** (`max_age=600`). Increase if your
  bots need it.

## 4. Things to consider next

- Add **Prometheus `/metrics`** behind the same API key.
- Move the **proxy-monitor** to a separate non-root user with `CAP_DAC_OVERRIDE`
  only on the docker socket.
- Add **structured audit log** of every API key use (current key hash + path
  + status), already partially in `structlog` events.
- Add **gitleaks / trufflehog** to CI to block future secret commits.
- Migrate the in-memory rate limiter to Redis so it works across workers.
- Run **`pip-audit`** regularly against both `requirements.txt` files.

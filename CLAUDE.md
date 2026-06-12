# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Instagram follower/following analyzer with two interfaces:
- **CLI** (`main.py`) — interactive terminal script
- **Web app** (`backend/` FastAPI + `frontend/` Vue 3 SPA)

Written in Spanish (variable names, prompts, comments, docs). There are no tests.

## Setup & Running

### CLI
```bash
python -m venv env
source env/bin/activate              # Linux/Mac
env\Scripts\activate                 # Windows
pip install -r requirements.txt
python main.py                       # prompts for username/password
```

### Web app — fully containerized (recommended, one command)
```bash
cp .env.example .env                 # compose reads it for ${VAR} substitution
docker compose up --build            # db + backend + frontend + pgadmin
```
Brings up **four containers**, frontend served by nginx on **http://localhost:5173**:

| Service    | Port        | Role |
|------------|-------------|------|
| `frontend` | 5173 → 80   | Vue build served by nginx; proxies `/api/*` → `backend:8000` (SSE-aware: `proxy_buffering off`, long read timeout) |
| `backend`  | 8000        | FastAPI; entrypoint runs `alembic upgrade head` then uvicorn |
| `db`       | 5432        | Postgres 16 (cache + history); backend waits on its `healthcheck` |
| `pgadmin`  | 8080        | DB inspection UI (pgAdmin 4; conexión pre-cargada vía `pgadmin/servers.json`) |

The frontend always uses **same-origin** relative paths (`fetch('/api/...')`) — no API base-URL constant. In Docker nginx does the `/api` proxy; in local dev Vite's `server.proxy` (`vite.config.js`) does. **Persistence via bind-mounts** (visible on the host): `./backend/downloads` (galleries/stories), `./backend/sessions` (`session_<user>.json`), plus the `pgdata` named volume for Postgres. Paths inside the container come from env: `DOWNLOADS_DIR=/data/downloads`, `SESSIONS_DIR=/data/sessions`.

### Web app — local dev without Docker (hot reload)
```bash
docker compose up -d db              # just Postgres (+ pgadmin if you want the UI)
cd backend
pip install -r requirements.txt      # uses the venv; NOT needed in the Docker path
alembic upgrade head                 # create/upgrade tables (re-run after model changes)
uvicorn main:app --reload            # reads DATABASE_URL from .env (localhost host)

cd frontend && npm install && npm run dev   # Vite dev server on :5173, proxies /api → :8000
```
Postgres is **optional at runtime**: if it's unreachable, the stream endpoint degrades to no-cache/no-history instead of failing. The CLI (`main.py`) does not use the DB at all.

> **Warning**: `uvicorn --reload` restarts the server on every file save, which **wipes all in-memory sessions** — you must re-login after each backend file edit.

### Note: backend can also serve the SPA itself (single-origin, non-Docker)
`backend/main.py` still mounts `frontend/dist` at `/` via `StaticFiles` **only if that directory exists** (conditional mount). So `cd frontend && npm run build` then `uvicorn main:app` serves everything on `:8000` without nginx. The Docker setup does **not** use this path — nginx serves the build instead — but the mount is harmless when `dist` isn't present.

### Monitoring bulk download jobs from the terminal
`backend/jobs_cli.py` is a stdlib-only CLI that queries the backend over HTTP:
```bash
cd backend
python jobs_cli.py                   # list jobs once
python jobs_cli.py --watch           # refresh every 2s (Ctrl-C to stop)
python jobs_cli.py --cancel <job_id> # cancel a running job
```

## Architecture

### CLI (`main.py`)
Four functions chained in `main()`:
1. `autenticar_instagram()` — loads `session.json` if present, else fresh login with `TwoFactorRequired` (prompts for code) / `ChallengeRequired` handling. Always re-dumps the session afterward.
2. `obtener_seguidores_con_mas_seguidores()` — fetches **who you follow** via `cl.user_following()` (not your followers), then `cl.user_info()` per user, keeping those with `follower_count >= min_seguidores` (default 1000).
3. `mostrar_resultados()` — sorts descending by follower count and prints a table.
4. Optional export to `seguidores_mas_1000_<username>.txt`.

### Web app — backend (`backend/`)
- `instagram.py` — Instagram logic decoupled from the CLI. Key function `obtener_usuarios(cl, modo, on_progress, target_user_id, session=None, run=None, ttl_days=7)` fetches **all** users for `modo` (`"following"` or `"followers"`) of the authenticated user or of `target_user_id`, with **no server-side filtering** — it returns everyone, sorted by follower count. Filtering happens in the frontend. Same anti-rate-limit delays as the CLI (see Key Constraints). Auth (`autenticar_instagram` / `_do_login`) maps instagrapi's `ChallengeUnknownStep`/`ChallengeError` to `ChallengeRequired`.
  - **Cache**: when a `session` (SQLAlchemy) is passed, each user is checked against `instagram_users` first. A hit newer than `ttl_days` is served from Postgres and **skips both the `user_info()` API call and the sleep** — this is the main rate-limit win. Misses are fetched, upserted, then delayed as usual. The `usuario` SSE event carries a `cached: bool`; `done` carries `from_cache: int`.
- `downloader.py` — gallery + stories download to `<DOWNLOADS_DIR>/<username>/{gallery,stories}/` (`BASE_DIR = Path(settings.DOWNLOADS_DIR)`, default `backend/downloads`), with `metadata.json` (per user, dedup by media `pk`) and `index.json` (global, `downloaded_at` per user). **Key gotcha: media binaries are fetched with bare `requests.get(url)`, NOT `cl.private`/`cl.session`** — Instagram CDN URLs are pre-signed and anonymous; sending the private-API headers/cookies breaks them. (`cl.session` doesn't even exist on the `Client` — using it silently `AttributeError`'d every download.)
  - `download_user(cl, username, user_id=None, on_progress=None, should_cancel=None)` — pass `user_id` (pk) to skip the username→id resolve. Emits `phase`/`total`/`download`/`error`/`done`.
  - `download_many(cl, users, on_progress, ttl_hours=24, should_cancel=None)` — bulk: skips users `fresh` (downloaded < `ttl_hours`, via `download_state`/`last_downloaded_at`), **adaptive pacing** by batch size (`pacing_for`: bigger batch → longer inter-user delay + periodic long rest), interruptible sleeps. Emits `bulk_start`/`user_start`/`user_skipped`/`user_done`/`user_error`/`resting`/`bulk_done` (+ inner `download_user` events tagged `scope:"item"`). `should_cancel` is checked between users and between items.

### Data layer (`backend/`, SQLAlchemy 2.0 **sync** + psycopg3 + Alembic)
Sync (not async) on purpose: the instagrapi fetch is blocking and runs in a `ThreadPoolExecutor`, so a sync `Session` fits without thread↔event-loop bridging; FastAPI runs `def` endpoints in its own threadpool.
- `config.py` — `settings` from env/`.env` (`DATABASE_URL`, `CACHE_TTL_DAYS`, `GALLERY_TTL_HOURS`, `ECHO_SQL`, `DOWNLOADS_DIR`, `SESSIONS_DIR`). On import it `mkdir`s `DOWNLOADS_DIR`/`SESSIONS_DIR` so they exist before use.
- `database.py` — `engine`, `SessionLocal`, `session_scope()` context manager, `get_session()` dependency.
- `models.py` — `InstagramUser` (profile cache), `AnalysisRun` (one snapshot/run), `RunMember` (which users were in a run, with follower counts **frozen at run time** for history diffs).
- `repository.py` — all SQL lives here: `get_cached_user` / `upsert_user` / `user_to_dict`, and `create_run` / `add_member` / `finalize_run` / `list_runs` / `get_run` / `diff_runs`.
- `alembic/` — migrations. `alembic/env.py` pulls `Base.metadata` and `settings.DATABASE_URL` (the `.ini` URL is overridden in code). After editing `models.py`: `alembic revision --autogenerate -m "..."` then `alembic upgrade head`.
- `main.py` — FastAPI app with all API endpoints. Key groups: auth (`/api/login`, `/api/logout`, `/api/session`), analysis stream (`/api/seguidores/stream`), posts/media proxy (`/api/posts`, `/api/download`, `/api/proxy-image`), single-user download SSE (`/api/download-user/stream`), bulk download jobs (`/api/download-all`, `/api/download-all/stream`, `/api/download-all/cancel`), downloads browser (`/api/downloads`), history (`/api/history/runs`, `/api/history/diff`).

**Session management**: `Client` objects live in memory in `sessions: dict[str, Client]`, keyed by a UUID `session_id` from login. Lost on server restart. Each Instagram user also gets a persistent `<SESSIONS_DIR>/session_<username>.json` (default `backend/`; `/data/sessions` in Docker, bind-mounted to `./backend/sessions`).

**Bulk jobs**: `bulk_jobs: dict[job_id, {state, cancel, subscribers}]` is in-memory — survives tab close, lost on server restart. `POST /api/download-all` returns immediately with `{job_id, total}`; `GET /api/download-all/stream?job_id=` streams events with a `snapshot` first (enabling reconnects). Multiple SSE subscribers per job are OK. Jobs pruned to last 10 finished.

**Progress streaming**: the blocking instagrapi fetch runs in a `ThreadPoolExecutor` (max 4 workers); progress events cross back to the async loop via `loop.call_soon_threadsafe(queue.put_nowait, event)`. Actual emitted event types from `obtener_usuarios` are `total`, `usuario`, `error`, `done`, plus `fatal_error` from `main.py` on an unhandled exception. (Note: the `seguidores_stream` docstring lists `progress`/`match`, but the code emits `usuario` — trust the code.)

### Web app — frontend (`frontend/`)
Vue 3 SPA built with Vite, styled with **Tailwind CSS v4** (via `@tailwindcss/vite`). The **active** code is in `src/`:
- `src/main.js` → mounts `App.vue` and imports `styles.css`.
- `src/styles.css` — the **only** stylesheet: `@import "tailwindcss"` + an `@theme` block mapping the OKLCH design tokens (so utilities like `bg-surface`/`text-faint`/`border-edge-soft`/`font-mono` exist) + custom max-width breakpoints (`xs`=480px, `xxs`=360px; used as `max-xs:`/`max-xxs:`) + a minimal `@layer base` (body layout, `h1` mark, inputs/buttons, focus, reduced-motion) + a `@layer components` of design-system atoms (`.card`/`.card-wide`/`.results-card`, `.btn-primary`/`.btn-secondary`/`.btn-sm`/`.btn-analizar`/`.btn-posts`/`.btn-icon`, `.field-label`, `.toggle`, `.chip`, `.filter-input`, table `th`/`td`/`.num`, `.badge`/`.user-link`/`.empty`, `.tab`, `.diff-*`). Layout/one-offs use utilities directly in the templates; components have **no `<style>` blocks**. **Mobile-first**: base styles target the smallest screen and scale up with min-width variants (`xxs:`≥360, `xs:`≥480, `sm:`≥640). Responsive table column hiding is per-cell (`hidden xs:table-cell` / `hidden sm:table-cell`), not `:nth-child`. Inputs are ≥16px on mobile (`text-base`) to avoid iOS focus-zoom.
- `src/api.js` — all fetch wrappers + SSE/download URL builders, incl. the bulk-download helpers (`startDownloadAllJob`, `subscribeBulkStream`, `fetchBulkJobs`, `fetchBulkStatus`, `cancelDownloadAll`, `checkSessionAPI`).
- `src/components/` — `LoginCard`, `SearchCard`, `ResultsCard`, `HistoryCard`, `DownloadsCard`.
- `src/composables/` — `useAuth`, `useSearch`, `useTable`, and `useBulkDownload` (state + logic).
- `App.vue` has a `view` ref toggling three tabs: `downloads` (`DownloadsCard`), `search` (SearchCard + ResultsCard) and `history` (`HistoryCard`). `HistoryCard` reads `/api/history/*`: lists runs, lets you select two to `diff` (gained/lost usernames), and expands a run's members. Numeric columns use the shared `.num` component class (Fira Code, tabular-nums).
- **Bulk download is app-level state**: `useBulkDownload` is instantiated in `App.vue` and `provide`d (so it survives view switches); `ResultsCard` injects it via `inject('bulkDl')`. The active `job_id` is kept in `localStorage`; `App.vue`'s `onMounted` calls `bulkDl.resume()` to re-subscribe to an in-flight job after a reload. Consumes the stream with `fetch`+reader (not `EventSource`) for manual reconnect control.

**Dead code — do not edit**:
- `frontend/app/` — earlier vanilla-JS modular version that predates the Vue rewrite. Not referenced by `index.html` or any build.
- `frontend/styles.css` — root-level stylesheet superseded by `frontend/src/styles.css`.

Frontend features: choose following vs followers, analyze your own or another `target_username`, live progress bar, client-side filters (public/private/verified/min-followers/keyword over bio+name+username), sortable table, CSV export, and a posts gallery modal.

## Design System & UI Principles

From `PRODUCT.md` — these guide all UI/frontend work:

**Brand personality**: afilada, densa, sin ceremonia. Linear/Raycast aesthetic: information density and read speed over decoration. No onboarding, no filler copy, no unnecessary confirmations.

**Design principles** (in priority order):
1. **Densidad sobre aire** — compact, readable tables before spacious layouts
2. **Velocidad percibida** — UI never blocks; filters/sort are instant client-side; progress is always live
3. **Honestidad sobre el costo** — rate-limit delays are real; show them clearly with progress/counts, never fake spinners
4. **Sin ceremonia** — zero onboarding; the user knows the tool
5. **El dato es el héroe** — color signals state (verified, private, error), not decoration

**Anti-references**: Instagram's purple/pink gradients, SaaS hero sections, heavy animations, glassmorphism, excess shadow.

## Subagents

`backend/.claude/agents/responsive-scalable-builder.md` — an agent specialized in responsive Vue 3 UI + scalable code architecture for this project. Invoke it when making significant frontend layout or multi-layer refactoring changes.

## Key Constraints

- `session*.json` and `*.txt`/CSV result files are gitignored — never commit them.
- `instagrapi` uses Instagram's **private** API. To avoid rate limiting, the client sets `cl.delay_range = [2, 5]` (built-in per-request delay) and `obtener_usuarios` / `obtener_seguidores_con_mas_seguidores` additionally sleep `random.uniform(4, 8)`s per user, `40–70`s every 30 users, and `15–30`s after an error. Don't remove these when editing fetch loops. `autenticar_instagram` reuses a saved session (validated via `get_timeline_feed()`) instead of re-calling `login()`, and reuses the same device `uuids` on re-login — both reduce challenges/rate limits.
- `ChallengeRequired` (Instagram email/SMS/device challenge) must be approved manually from the Instagram app before retrying.
- **Downloading media binaries**: always use bare `requests.get(url)` (Instagram CDN URLs are pre-signed/anonymous). Never use `cl.private`/`cl.session` for the CDN — the private-API headers break the fetch, and `cl.session` doesn't exist (it `AttributeError`s). Don't swallow download errors silently; emit them.
- **Bulk download pacing**: `config.GALLERY_TTL_HOURS` (default 24) is the per-user cooldown; `downloader.pacing_for()` scales delays by batch size. Keep these conservative — bulk-downloading hundreds of users is the highest rate-limit risk in the app. The frontend's `estimateBulk`/`pacingFor` must mirror `pacing_for` for the ETA to be right.

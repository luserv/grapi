# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Instagram follower/following analyzer with two interfaces:
- **CLI** (`main.py`) — interactive terminal script
- **Web app** (`backend/` FastAPI + shared `core/grapi_core/` + `docker/web/frontend/` Next.js SPA)

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
docker compose up --build            # backend + frontend
```
Brings up **two containers**, frontend served by Next.js on **http://localhost:14**:

| Service    | Host port | Role |
|------------|-----------|------|
| `frontend` | 14 → 3000 | Next.js 15 dev server (Turbopack); proxies `/api/*` → `backend:8000` via `next.config.mjs` rewrites |
| `backend`  | 12 → 8000 | FastAPI (SQLite by default; tables created by `init_db()` on startup). Image built from the repo root (`docker/api/Dockerfile`): `PYTHONPATH=/app/core`, source bind-mounted for `--reload` |

**There is no `db` or `pgadmin` service.** Inspect the DB with `docker compose exec backend python -c "import sqlite3; ..."` on `/data/db/app.db`. `DATABASE_URL` pointing at an external Postgres still works (`psycopg` is in `backend/requirements.txt`).

The frontend always uses **same-origin** relative paths (`fetch('/api/...')`) — no API base-URL constant. The Next.js rewrite proxies to `process.env.BACKEND_URL ?? 'http://localhost:8000'`.

> **`BACKEND_URL` must be set at runtime, in `docker-compose.yml` (frontend `environment:`), NOT baked into the image.** The frontend `Dockerfile` deliberately has no `ARG`/`ENV` for it (a build-stage value never reaches the runtime stage) — if it is unset at runtime the rewrite silently falls back to `localhost:8000` (nothing there) and the whole `/api` proxy breaks. Compose sets it explicitly, which is why it works. If you change the backend address, change compose and `docker compose up -d --force-recreate frontend`; no rebuild needed.

**Persistence via bind-mounts** (visible on the host): `./data` → `/data` (gitignored): `data/db/app.db` (SQLite), `data/downloads` (galleries/stories), `data/sessions` (`session_<user>.json`). Paths inside the container come from env: `DOWNLOADS_DIR=/data/downloads`, `SESSIONS_DIR=/data/sessions`.

> **`.env` is NOT mounted into the containers.** Its values are injected by compose interpolation at *container-create* time, and `config.py` reads them once at import. So editing `.env` has **zero effect** until you recreate: `docker compose up -d --force-recreate <service>`. A plain `docker restart` is not enough.

### Web app — local dev without Docker (hot reload)
```bash
pip install -r backend/requirements.txt   # uses the venv; NOT needed in the Docker path
export PYTHONPATH=$PWD/core DATABASE_URL=sqlite:///$PWD/data/app.db   # fish: set -x
cd backend && uvicorn main:app --reload   # tables are created on startup

cd docker/web/frontend && npm install && npm run dev   # Next.js dev server on :5174 with Turbopack
```
The DB is **optional at runtime** (config.py's default `DATABASE_URL` is still Postgres on localhost:11, so set it to sqlite as above): if it's unreachable, the stream endpoint degrades to no-cache/no-history instead of failing. The CLI (`main.py`) does not use the DB at all. Outside Docker, `npm run dev` uses the port in `package.json` (5174) and the rewrite falls back to `http://localhost:8000`, so it needs a `BACKEND_URL` export only if your backend is not on 8000.

> **Warning**: `uvicorn --reload` restarts the server on every file save, which **wipes all in-memory sessions** — you must re-login after each backend file edit.

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
- `instagram.py` — Instagram logic decoupled from the CLI. Key function `obtener_usuarios(cl, modo, on_progress, target_user_id, target_username, session=None, metrics_ttl_days=180)` fetches **all** users for `modo` (`"following"` or `"followers"`) of the authenticated user or of `target_user_id`, with **no server-side filtering** — it returns everyone, sorted by follower count. Filtering happens in the frontend. Same anti-rate-limit delays as the CLI (see Key Constraints). Auth (`autenticar_instagram` / `_do_login`) maps instagrapi's `ChallengeUnknownStep`/`ChallengeError` to `ChallengeRequired`.
  - **Two sources, two costs.** The list call (`user_following` / `user_followers_v1`) returns a `UserShort` per user carrying `username`, `full_name`, `is_verified`, `is_private` and both profile pics — for the **whole list in one request**. It does **not** carry follower/following/media counts. So identity is free and always re-read per analysis, while the counters cost one `user_info_v1` per user. `_identity_from_short()` applies the list's identity on **every** path, including the total cache hit, because the list is already in memory — a hit must not report a stale name just to save a dict lookup.
  - **Cache**: `get_cached_user()` has **no TTL** — the row is eternal. `metrics_are_fresh(user, metrics_ttl_days)` is the only expiry and it governs just the counters. A total hit costs **zero** requests. When the counters are stale the loop pays one `user_info_v1` plus the delay; if that refresh throws but a cached row exists, the user is served with the **stale counters plus fresh identity** and counted in `done.stale`, instead of vanishing from the table. `upsert_user` takes `data["metrics_fresh"]` so an identity-only update can't lie to the TTL.
  - The `usuario` SSE event carries `cached: bool`; `done` carries `from_cache` / `refreshed` / `stale`, all rendered by `doneMessage` in `lib/hooks.ts`.
  - `?refresh=1` on the stream endpoint forces `metrics_ttl_days=0` — the escape hatch for "fresh numbers now" without editing `.env` and recreating the container. Costs one request per user.
  - **History write**: if a `session` is passed *and* `cl.username` is set, it opens one `AnalysisRun` via `create_run` (owner = `cl.username`, `target_username` comes in as its own arg — the stream endpoint resolves the id but must also pass the name, otherwise every run looks like "(mi cuenta)" and `sameGroup` in `HistoryCard` mis-groups them), adds a `RunMember` per user inside the existing per-user commit, and `finalize_run`s at the end. No session or no username → no run, no error.
- `downloader.py` — gallery + stories download to `<DOWNLOADS_DIR>/<username>/{gallery,stories}/` (`BASE_DIR = Path(settings.DOWNLOADS_DIR)`, default `backend/downloads`), with `metadata.json` (per user, dedup by media `pk`) and `index.json` (global, `downloaded_at` per user). **Key gotcha: media binaries are fetched with bare `requests.get(url)`, NOT `cl.private`/`cl.session`** — Instagram CDN URLs are pre-signed and anonymous; sending the private-API headers/cookies breaks them. (`cl.session` doesn't even exist on the `Client` — using it silently `AttributeError`'d every download.)
  - `download_user(cl, username, user_id=None, on_progress=None, should_cancel=None)` — pass `user_id` (pk) to skip the username→id resolve. Emits `phase`/`total`/`download`/`error`/`done`.
  - `download_many(cl, users, on_progress, ttl_hours=24, should_cancel=None)` — bulk: skips users `fresh` (downloaded < `ttl_hours`, via `download_state`/`last_downloaded_at`), **adaptive pacing** by batch size (`pacing_for`: bigger batch → longer inter-user delay + periodic long rest), interruptible sleeps. Emits `bulk_start`/`user_start`/`user_skipped`/`user_done`/`user_error`/`resting`/`bulk_done` (+ inner `download_user` events tagged `scope:"item"`). `should_cancel` is checked between users and between items.

### Data layer (`backend/`, SQLAlchemy 2.0 **sync** + psycopg3 + Alembic)
Sync (not async) on purpose: the instagrapi fetch is blocking and runs in a `ThreadPoolExecutor`, so a sync `Session` fits without thread↔event-loop bridging; FastAPI runs `def` endpoints in its own threadpool.
- `config.py` — `settings` from env/`.env` (`DATABASE_URL`, `METRICS_TTL_DAYS`, `GALLERY_TTL_HOURS`, `ECHO_SQL`, `DOWNLOADS_DIR`, `SESSIONS_DIR`). On import it `mkdir`s `DOWNLOADS_DIR`/`SESSIONS_DIR` so they exist before use. **`METRICS_TTL_DAYS` defaults to 180** and governs *only the counters* — there is no TTL on the cached row itself.
- `database.py` — `engine`, `SessionLocal`, `session_scope()` context manager, and `init_db()` (`create_all`, called on app startup; replaces Alembic). For `sqlite:` URLs it creates the parent dir and sets `check_same_thread=False`. That is the only way to get a session; there is no `Depends`-based dependency helper.
- `models.py` — `InstagramUser` (profile cache), `AnalysisRun` (one snapshot/run), `RunMember` (a **self-contained snapshot** of a profile as it was at analysis time).
  - `RunMember` has **no FK to `instagram_users`** — `user_pk` is a plain indexed `BigInteger` used only to correlate with the cache. It carries `username`/`full_name`/`is_verified`/`is_private` plus the frozen counters, so nothing about a past run depends on the cache. This was deliberate: the old FK was `ON DELETE CASCADE` (purging the cache silently erased history) and reading `username` through the relationship returned *today's* value for a run from months ago — the same lie as reading the counters live. `RunMember.run_id` still has a real CASCADE FK to `analysis_runs`. There is no `InstagramUser.memberships` relationship anymore; `search_users` joins `run_members` with an explicit `ON user_pk = instagram_users.pk` instead.
- `repository.py` — all SQL lives here: `get_cached_user` / `upsert_user` / `user_to_dict` / `search_users`, and the history half (`create_run` / `add_member` / `finalize_run` / `list_runs` / `get_run` / `run_owner` / `run_to_dict` / `member_to_dict` / `diff_runs`).
  - **`create_run` always creates — it must never reuse a run.** `diff_runs` requires both runs to share `modo` + `target_username`, so if a second analysis of the same target reused the first run there would never be a comparable pair and the diff would be permanently empty. That reuse logic, its `_find_existing_run` helper, and `reset_run_members` (which existed only to clear a reused run) were all removed — and that reuse is provably what corrupted run 24: it kept `total=125` with only 12 `run_members`, because the reuse wiped the members of the *previous* run and only a few were re-added. Runs 1-8 and 28 also have `total=0` with members present, from before `finalize_run` was being called. Both are legacy fossils; new runs are consistent.
  - `add_member` copies identity + badges + counters off the `InstagramUser` row into the snapshot; `member_to_dict` and `_run_usernames` read **only** from `RunMember`. If you add a field to the history UI, snapshot it — do not join back to the profile.
  - `search_users` has no time filter, and `/api/downloads/pending` calls it with `limit=10_000` — that endpoint crosses the whole table against the download directory on every request. Measured at ~70ms with 1287 cached profiles, and the SQL part is only 0.35ms: the cost is the ~3 filesystem calls per user (`exists()` + `iterdir()`), not the query. It scales linearly with the cache, so it is fine now and would need pagination or a cached listing somewhere around 10k+ profiles.
- **No migrations anymore** (`alembic/` was removed in the `core/` restructure; `backend/alembic.ini` is a leftover). `create_all` only creates missing tables — it never alters existing ones, so a model change needs a manual migration or deleting `data/db/app.db`.
- **Known gap**: `core/grapi_core/repository.py` still calls `pg_insert` (never imported after the restructure) and uses `on_conflict_do_update(constraint=...)`, which is Postgres-only — `upsert_user`/`add_member` fail until ported to a dialect-neutral upsert.
- `main.py` — FastAPI app with all API endpoints. Key groups: auth (`/api/login`, `/api/logout`, `/api/sessions`, `/api/session`), analysis stream (`/api/seguidores/stream`), posts/media proxy (`/api/posts`, `/api/download`, `/api/proxy-image`), single-user download SSE (`/api/download-user`, `/api/download-user/stream`), bulk download jobs (`/api/download-all`, `/api/download-all/stream`, `/api/download-all/status`, `/api/download-all/cancel`, `/api/download-jobs`), downloads browser (`/api/downloads`, `/api/downloads/pending`, `/api/downloads/<username>`, `/api/downloads/<username>/files/<filename:path>`), history (`/api/history/runs`, `/api/history/runs/<id>`, `/api/history/diff`, `/api/history/users`).
  - **History endpoints take `session_id`, not a username.** `_history_owner()` resolves it to `sessions[session_id].username` and 401s if the session is gone; `_assert_run_owner()` 404s when a run belongs to another account, so runs never leak across accounts. `HistoryCard` already spoke this exact contract — the endpoints were simply missing, and the card had been 404ing.

**Session management**: `Client` objects live in memory in `sessions: dict[str, Client]`, keyed by a UUID `session_id` from login. Lost on server restart. Each Instagram user also gets a persistent `<SESSIONS_DIR>/session_<username>.json` (default `backend/`; `/data/sessions` in Docker, bind-mounted to `./backend/sessions`).

**Bulk jobs**: `bulk_jobs: dict[job_id, {state, cancel, subscribers}]` is in-memory — survives tab close, lost on server restart. `POST /api/download-all` returns immediately with `{job_id, total}`; `GET /api/download-all/stream?job_id=` streams events with a `snapshot` first (enabling reconnects). Multiple SSE subscribers per job are OK. Jobs pruned to last 10 finished.

**Progress streaming**: the blocking instagrapi fetch runs in a `ThreadPoolExecutor` (max 4 workers); progress events cross back to the async loop via `loop.call_soon_threadsafe(queue.put_nowait, event)`. Actual emitted event types from `obtener_usuarios` are `total`, `usuario`, `error`, `done`, plus `connected` (from `main.py` before the fetch) and `fatal_error` on an unhandled exception.

### Web app — frontend (`docker/web/frontend/`)
Next.js 15 SPA (App Router, Turbopack, `"use client"`), TypeScript, styled with **Tailwind CSS v4** (via `@tailwindcss/postcss`). The active code:
- `app/layout.tsx` — root layout (`<html lang="es">`, imports `globals.css`).
- `app/page.tsx` — main SPA page (`"use client"`), a single component with `view` state toggling three screens: `downloads`, `search`, `history`. Owns per-user download stream logic, login/logout, CSV export, tab navigation, and session switcher.
- `app/globals.css` — the **only** stylesheet: `@import "tailwindcss"` + an `@theme` block mapping the OKLCH design tokens (so utilities like `bg-surface`/`text-faint`/`border-edge-soft`/`font-mono` exist) + custom max-width breakpoints (`xs`=480px, `xxs`=360px; used as `max-xs:`/`max-xxs:`) + a minimal `@layer base` (body layout, `h1` mark, inputs/buttons, focus, reduced-motion) + a `@layer components` of design-system atoms (`.card`/`.card-wide`/`.results-card`, `.btn-primary`/`.btn-secondary`/`.btn-sm`/`.btn-analizar`/`.btn-posts`/`.btn-icon`, `.field-label`, `.toggle`, `.chip`, `.filter-input`, table `th`/`td`/`.num`, `.badge`/`.user-link`/`.empty`, `.tab`, `.diff-*`). Layout/one-offs use utilities directly in the templates; components have **no `<style>` blocks**. **Mobile-first**: base styles target the smallest screen and scale up with min-width variants (`xxs:`≥360, `xs:`≥480, `sm:`≥640). Responsive table column hiding is per-cell (`hidden xs:table-cell` / `hidden sm:table-cell`), not `:nth-child`. Inputs are ≥16px on mobile (`text-base`) to avoid iOS focus-zoom.
- `lib/api.ts` — all fetch wrappers + SSE/download URL builders, typed with exported interfaces (`User`, `DownloadEntry`, `MediaItem`, `Run`, `SessionEntry`). Includes bulk-download helpers (`startDownloadAllJob`, `subscribeBulkStream`, `fetchBulkStatus`, `cancelDownloadAll`, `checkSessionAPI`).
- `lib/downloadSummary.ts` — pure formatters for bulk-download completion (`formatDownloadSummary`, `sectionLabel`, `DownloadDoneEvent`). No React.
- `lib/hooks.ts` — four custom hooks (analogous to Vue composables):
  - `useAuth` — session list management, login/logout/switchTo, 2FA handling
  - `useSearch` — SSE stream consumption, results accumulation, stack-based navigation for drilling into target users, cached results loading
  - `useTable` — client-side filtering (public/private/verified/min-followers/keyword), sorting by column
  - `useBulkDownload` — download job lifecycle (start/subscribe/resume/cancel), localStorage persistence for reconnection
- `components/` — `LoginCard`, `SearchCard`, `ResultsCard`, `HistoryCard`, `DownloadsCard`. Pure presentational; all state lives in `page.tsx` or `hooks.ts`.

Frontend features: choose following vs followers, analyze your own or another `target_username`, live progress bar, client-side filters, sortable table, CSV export, session switcher (multi-account), and per-user gallery/stories download with progress. Bulk download is app-level state via `useBulkDownload` (the active `job_id` is kept in `localStorage`; `resume()` re-subscribes to an in-flight job after reload). Consumes the stream with `fetch`+reader (not `EventSource`) for manual reconnect control.

- `docker/web/frontend/src/` — **dead code, do not edit**: leftover `src/` directory from the Vue era. (`lib/` is live; don't confuse the two.)

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

`backend/.claude/agents/responsive-scalable-builder.md` — an agent specialized in responsive React/Next.js UI + scalable code architecture for this project. Invoke it when making significant frontend layout or multi-layer refactoring changes.

## Key Constraints

- `session*.json` and `*.txt`/CSV result files are gitignored — never commit them.
- `instagrapi` uses Instagram's **private** API. To avoid rate limiting, the client sets `cl.delay_range = [2, 5]` (built-in per-request delay) and `obtener_usuarios` / `obtener_seguidores_con_mas_seguidores` additionally sleep `random.uniform(4, 8)`s per user, `40–70`s every 30 users, and `15–30`s after an error. Don't remove these when editing fetch loops. `autenticar_instagram` reuses a saved session (validated via `get_timeline_feed()`) instead of re-calling `login()`, and reuses the same device `uuids` on re-login — both reduce challenges/rate limits.
- **Cache TTL**: `config.METRICS_TTL_DAYS` (default 180) is the *only* expiry, and it applies solely to the counters — `instagram_users.metrics_fetched_at`. The cached row itself never expires, and identity is never cache-dependent: it is re-read from the following/followers list on every analysis, which is a single call that also returns badges and profile pics. If a bug ever leaves the cache looking empty, check `from_cache` / `refreshed` / `stale` in the `done` event first — the frontend surfaces all three.
- `ChallengeRequired` (Instagram email/SMS/device challenge) must be approved manually from the Instagram app before retrying.
- **Downloading media binaries**: always use bare `requests.get(url)` (Instagram CDN URLs are pre-signed/anonymous). Never use `cl.private`/`cl.session` for the CDN — the private-API headers break the fetch, and `cl.session` doesn't exist (it `AttributeError`s). Don't swallow download errors silently; emit them.
- **Bulk download pacing**: `config.GALLERY_TTL_HOURS` (default 24) is the per-user cooldown; `downloader.pacing_for()` scales delays by batch size. Keep these conservative — bulk-downloading hundreds of users is the highest rate-limit risk in the app. The frontend's `estimateBulk`/`pacingFor` must mirror `pacing_for` for the ETA to be right.

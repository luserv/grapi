# docker-fix

Goal: `docker compose up --build` brings up backend (:12) and frontend (:14) end to end after commit 75a01c3.

## Root causes
- compose still pointed at `./frontend`; Dockerfile/nginx/pnpm files were deleted in 75a01c3.
- `docker/api` had no Dockerfile; its `main.py` was a broken stale copy (`import sync`, `app` used before defined, CORS `*`); removed. Single source is `backend/main.py`.
- Backend image could not see `core/grapi_core` (build context was the api dir).
- No Alembic migrations anymore and nothing created tables; no db service; orphan `pgdata` volume.
- `*.txt` in .gitignore ignored `requirements.txt` (never tracked) -> clean checkouts could not build. Added `!requirements.txt`.
- `backend/requirements.txt` lacked `psycopg`; added (Postgres still works via DATABASE_URL). Dropped `alembic`.

## Decisions
- Build context = repo root, `docker/api/Dockerfile`, root `.dockerignore` whitelist. Image layout `/app/backend`, `/app/core/grapi_core`, `PYTHONPATH=/app/core`.
- `core/grapi_core/database.py`: sqlite branch (mkdir parent, `check_same_thread=False`), `init_db()`; `backend/main.py` calls it on startup, guarded (DB stays optional; also safe for the desktop sidecar).
- Data: `./data:/data` bind (gitignored): `db/app.db`, `downloads`, `sessions`. Source bind-mounted for `--reload`.
- Frontend: Dockerfile recreated without `ARG BACKEND_URL`; compose keeps runtime `BACKEND_URL`, dev server (`target: build`).

## Evidence (docker compose up -d --build)
- :12/api/health 200; :14/ 200; :14/api/health 200 (proxy); :12 and :14 /api/downloads/pending 200; `/data/db/app.db` created with tables instagram_users, analysis_runs, run_members.

## Open problems (outside allowed surfaces)
- `repository.py`: `pg_insert` NameError (confirmed in container: `upsert_user`), and Postgres-only `on_conflict_do_update(constraint=...)`; with SQLite, tz-aware comparisons in `metrics_are_fresh` also unverified. Analysis/history writes are broken until fixed.
- `core/pyproject.toml` is invalid for packaging (not used by Docker).
- A pre-existing `instagrapi-db-1` container is orphaned (left untouched).

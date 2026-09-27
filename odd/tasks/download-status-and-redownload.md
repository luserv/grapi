# Feature: download status visibility + incremental re-download

## Objective
Make it visible whether stories (and highlights) were actually downloaded, and let the
user re-download a single user at any time, fetching only media not already on disk.

## Problem
- `DownloadsCard` shows only a bare "Descargado" on `done`; no per-section counts.
- `page.tsx` done label shows `+gallery, +stories` but not highlights nor how many
  stories were active; a failed `user_stories_v1` call is overwritten by the next
  status event, so "0 stories" is indistinguishable from "stories fetch failed".
- Single-user download button is disabled for 24h after a download (`isFresh`),
  even though the backend already dedups against disk (`_existing_pks`).

## Scope / decisions
- Single-user manual download: remove the 24h UI lock; backend stays incremental.
- Bulk download (`download_many`): keep `GALLERY_TTL_HOURS` cooldown (rate-limit risk).
- Backend `done` event gains per-section found counts and section errors.
- Out of scope: mobile-first pass (separate feature).

## Constraints
- Keep anti-rate-limit sleeps. CDN fetch stays bare `requests.get`.
- UI icons via `lucide-react`, no unicode glyph icons in touched UI.
- Mobile-first styles (min-width variants).

## TDD
Strict TDD configured globally, but the project has no test runner or tests
(CLAUDE.md: "There are no tests"). No runner invented; functional checks instead.

## Tasks
- [x] T1 Backend: `done` event reports found/new per section + section errors (route: delegated writer, trigger: 2+ non-trivial files)
- [x] T2 Frontend: show persistent per-section summary and section errors (DownloadsCard, page.tsx)
- [x] T3 Frontend: remove 24h lock for single-user download; keep "last downloaded" hint

## Acceptance criteria
- After a single-user download, UI shows e.g. `+3 galería · 2/2 historias · +0 destacadas`;
  a stories fetch error is shown as such, distinct from "0 activas".
- Single-user download button is enabled regardless of last download time; a second
  run downloads only missing media.

## Checks
- `python -m py_compile backend/downloader.py backend/main.py`
- `npx tsc --noEmit` in `frontend/`
- Stack up via docker compose; frontend 200 on :14, backend 200 on :12.

## Progress
- Created 2026-09-27. Commits pending: working tree has pre-existing uncommitted
  user changes in the same files on `main`.
- 2026-09-27: T1-T3 done by delegated writer. Checks: py_compile OK; `npx tsc --noEmit` no errors;
  backend :12 200, frontend :14 200 (writer + parent spot check). Not verified end to end
  against Instagram (needs a logged-in session).
- Found + fixed: story/highlight pk dedup never matched (`str` from instagrapi vs `int` in
  metadata). All pks now normalized to `str`. Existing metadata holds 11 duplicate
  story/highlight entries from that bug (cleanup pending user decision).
- ResultsCard: no freshness gate on per-user download; unchanged.
- Commits still pending (pre-existing uncommitted user changes on main).
- 2026-09-27: committed as f5cc72d on `feat/download-status-redownload` (user chose one combined
  commit incl. prior WIP; tsbuildinfo and .atl/ excluded). RDD: medium, granted, reviewed
  (reliability lens), approved + acknowledged (lineage review-a3cba402640c493c).
  Advisory follow-ups (non-blocking): highlight partial fetch failure not surfaced in
  section_errors (downloader.py:368-370); fatal-error 3s timer can clear a retry's label
  (page.tsx:75-81); privileged host ports; no tests for formatDownloadSummary.
- 2026-09-27 follow-ups (route: inline, 2 small targeted edits):
  - [x] T4 highlights partial fetch failure now sets `section_errors.highlights` (downloader.py)
  - [x] T5 fatal/connection error clear timer skips if a new download started (page.tsx `clearErrorLater`)
  - [x] T6 deduped story/highlight metadata entries (data only, not in git): 11 removed, 0 left;
        index.json counts recomputed. Backup: scratchpad meta-backup/downloads-meta.tgz.
  Checks: py_compile OK, `npx tsc --noEmit` no errors.

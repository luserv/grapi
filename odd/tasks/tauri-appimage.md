# tauri-appimage

Objective: produce a working Linux AppImage of grapi (Tauri 2 shell + Next static export + PyInstaller sidecar).

## Findings (2026-10-14)
- `cargo tauri build` "succeeded" but built nothing: src-tauri has only lib.rs, no main.rs/build.rs/bundle config.
- Sidecar binary is broken: PyInstaller entry is core/grapi_core/instagram.py (no server), fails on `import instagrapi`; build-sidecar.sh mixes --onedir and -F.
- app/ is a Next project with no layout/next.config; api.ts hardcodes :8000; lib.rs assumes :8765.

## Decisions
- Frontend: Next `output: 'export'`, API base from NEXT_PUBLIC_API_BASE (default http://127.0.0.1:8765).
- Sidecar: single-file PyInstaller running uvicorn on 127.0.0.1:8765; data dirs under app data dir.
- Route: delegated direct (multi-file writer). No work-unit commits: working tree holds the user's unrelated staged restructuring.

## Tasks
- [x] T1 sidecar entrypoint + PyInstaller build
- [x] T2 frontend static export + API base
- [x] T3 Tauri shell (Cargo, build.rs, main/lib, tauri.conf.json, capabilities)
- [x] T4 `cargo tauri build --bundles appimage` yields an AppImage that launches and answers /api/health
- [x] T5 choose the downloads folder from the UI (persisted settings.json, GET/PUT /api/settings, tauri-plugin-dialog picker, text-input fallback in browser); window rendering and native picker not verified

## Evidence
- T1: build-sidecar.sh -> onefile binary; curl /api/health returned {"status":"ok"} with tauri://localhost CORS header.
- T2: `npm run build` in app/ produced app/out (static export).
- T3/T4: `NO_STRIP=true cargo tauri build --bundles appimage` produced src-tauri/target/release/bundle/appimage/grapi_0.1.0_amd64.AppImage (148 MiB); launched with APPIMAGE_EXTRACT_AND_RUN=1 on the live display, sidecar answered /api/health on 8765, app data dirs created, port closed and processes gone after SIGTERM. Window rendering not visually inspected.
- T5: invisible-path root cause: no code defect (sidecar /api/health returned downloads_dir, CSP allows 127.0.0.1:8765, bundle contains the line). The line lived only in the Descargas tab (default view is Buscar) and was tiny faint text. Now a prominent path row with "Cambiar carpeta" in that tab. tsc and `npm run build` clean; AppImage rebuilt (src-tauri/target/release/bundle/appimage/grapi_0.1.0_amd64.AppImage, 12:21). Rebuilt sidecar over HTTP: GET /api/settings ok, PUT temp dir ok, GET returns it, relative path -> 400, unwritable path -> 400, settings.json (next to sessions dir) persisted across restart. Not verified: window rendering, native folder picker, 409 while a bulk job runs.

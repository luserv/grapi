# grapi

Analizador de seguidores/seguidos de Instagram con descarga de galerías e historias.

**Landing**: https://luserv.github.io/grapi/ (carpeta `web/`). Se despliega con `.github/workflows/pages.yml`; para que funcione hay que activar Pages en los ajustes del repo con *Source = GitHub Actions* (paso manual).

**Stack**: FastAPI + SQLite (Postgres opcional) · Next.js 15 · instagrapi · Tauri 2 (app de escritorio)

## Estructura del repo

| Ruta | Contenido |
|---|---|
| `core/grapi_core/` | Lógica compartida: config, base de datos, repositorio, Instagram, descargas |
| `backend/` | App FastAPI (`main.py`) y `serve.py`, el entrypoint del sidecar de escritorio |
| `app/` | Frontend de la app de escritorio (Next.js, export estático) |
| `src-tauri/` | Shell de Tauri (Rust) que empaqueta el AppImage |
| `docker/api/`, `docker/web/frontend/` | Dockerfile del backend (contexto: raíz del repo) y frontend web para Docker |
| `main.py` | Script CLI |

---

## Levantar el proyecto

### Opción A — Docker

```bash
cp .env.example .env          # opcional; los defaults funcionan
docker compose up --build
```

| Servicio   | URL                        | Rol |
|------------|----------------------------|-----|
| Frontend   | http://localhost:14        | Next.js (dev server con hot-reload) |
| Backend    | http://localhost:12        | FastAPI; crea las tablas SQLite al arrancar |

Son **dos** servicios. No hay Postgres, ni Alembic, ni pgAdmin: la caché y el historial viven en un archivo SQLite (`data/db/app.db`).

El frontend habla con el backend por paths relativos (`/api/...`) a través de un rewrite de Next.js que lee `BACKEND_URL` en **runtime** (compose lo setea a `http://backend:8000`), así que no hay que configurar ninguna URL de API en el cliente.

Los datos persisten en `./data/` (ignorado por git, creado por Docker como root): `db/app.db`, `sessions/` y `downloads/`.

> **El `.env` no está montado en los containers.** Compose lo lee al *crear* cada contenedor. Si cambiás una variable, recreá el servicio: `docker compose up -d --force-recreate backend`. Con un `docker restart` no alcanza.

El código de `backend/`, `core/` y `docker/web/frontend/{app,components,lib}` está montado en los contenedores: los cambios se recargan solos, sin rebuild. Si cambiás `backend/requirements.txt` o `package.json`, reconstruí con `docker compose up --build`.

### Opción B — local sin Docker

**Requisitos:** Python 3.11+, Node 20+

```bash
# 1. Backend (desde la raíz del repo)
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
export PYTHONPATH=$PWD/core                         # para que resuelva `grapi_core`
export DATABASE_URL=sqlite:///$PWD/data/app.db      # sin esto el default es Postgres en localhost:11
cd backend
uvicorn main:app --reload                           # http://localhost:8000

# 2. Frontend (en otra terminal)
cd docker/web/frontend
npm install
npm run dev                                         # http://localhost:5174
```

(En fish: `set -x PYTHONPATH $PWD/core`, `set -x DATABASE_URL sqlite:///$PWD/data/app.db` y `source .venv/bin/activate.fish`.)

Las tablas se crean solas al arrancar. La base es **opcional**: si no está disponible, el backend degrada a sin caché/sin historial en vez de fallar. Sesiones y descargas van por defecto a `core/grapi_core/` (`SESSIONS_DIR` / `DOWNLOADS_DIR` lo cambian).

> ⚠️ `uvicorn --reload` reinicia el proceso en cada guardado del backend, lo que **borra las sesiones en memoria**. Tenés que volver a iniciar sesión después de cada cambio.

### Opción C — App de escritorio (AppImage en Linux, NSIS en Windows)

Un solo ejecutable: ventana de Tauri + backend FastAPI empaquetado con PyInstaller (sidecar) + frontend estático.

**Requisitos:** Rust y `cargo-tauri` v2, Node 20+, un venv `env/` con `backend/requirements.txt` y `backend/requirements-build.txt` (PyInstaller). `scripts/build_sidecar.py` usa ese venv automáticamente si existe.

```bash
NO_STRIP=true cargo tauri build --bundles appimage
```

`NO_STRIP=true` hace falta en Arch (el `strip` de linuxdeploy falla). El build reconstruye el sidecar (`scripts/build_sidecar.py`, ~50 s) y el frontend (`app/`) cada vez. Resultado:

```
src-tauri/target/release/bundle/appimage/grapi_0.1.0_amd64.AppImage
```

```bash
APPIMAGE_EXTRACT_AND_RUN=1 ./src-tauri/target/release/bundle/appimage/grapi_0.1.0_amd64.AppImage
```

- El sidecar escucha en `127.0.0.1:8765` (`GRAPI_PORT` lo cambia). La ventana se muestra cuando `/api/health` responde.
- Si la base no está disponible, el backend degrada a sin caché/sin historial.
- **Datos** en `~/.local/share/dev.grapi.desktop/`: `sessions/`, `downloads/` y `settings.json`.
- **Carpeta de descargas configurable**: en la pestaña *Descargas* se ve la ruta actual y el botón **Cambiar carpeta** abre un selector nativo. Se guarda en `settings.json` y rige para las descargas nuevas; **lo ya descargado no se mueve**. No se puede cambiar mientras corre una descarga masiva.
- Para desarrollar el frontend de escritorio: `cd app && npm install && npm run build` (genera `app/out`). La URL de la API sale de `NEXT_PUBLIC_API_BASE` (default `http://127.0.0.1:8765`).

### Releases (GitHub Actions)

`.github/workflows/release.yml` compila la app de escritorio en `ubuntu-22.04` (AppImage) y `windows-latest` (instalador NSIS `.exe`, por usuario, sin admin) y deja los binarios como artefactos del run (`grapi-linux-appimage`, `grapi-windows-nsis`). Se dispara con tags `v*` o a mano (*Run workflow*).

Para publicar una versión:

1. Subí `version` en `src-tauri/tauri.conf.json` (fuente de verdad; mantené `src-tauri/Cargo.toml` igual) y commiteá.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`. El workflow falla si el tag no coincide con la versión del `tauri.conf.json`.
3. Cuando terminen los dos builds, aparece un **release en borrador** en *Releases* con ambos instaladores adjuntos. Revisalo y publicalo.

Un run manual (`workflow_dispatch`) solo sube los artefactos al run; no crea release.

> ⚠️ El build de Windows y el workflow en los runners de GitHub **no se pudieron verificar en local** (solo se probó el AppImage en Linux). Esperá que el primer run necesite ajustes. Los instaladores no están firmados: Windows SmartScreen va a advertir.

---

## Variables de entorno

Copiá `.env.example` a `.env`. Los valores por defecto levantan todo sin cambios.

| Variable | Default | Descripción |
|---|---|---|
| `DATABASE_URL` | Docker: `sqlite:////data/db/app.db` | URL de SQLAlchemy. Para Postgres: `postgresql+psycopg://user:pass@host:puerto/db` (tu propio servidor; no hay servicio `db`) |
| `METRICS_TTL_DAYS` | `180` | Días que los contadores de un perfil se consideran frescos (semestral) |
| `GALLERY_TTL_HOURS` | `24` | Cooldown entre descargas del mismo usuario |
| `ECHO_SQL` | `0` | Loguear SQL (debug) |

### Sobre la caché y `METRICS_TTL_DAYS`

La caché guarda perfiles, pero no todo en un perfil se comporta igual:

- **Identidad** (usuario, nombre, verificado, privado, foto) se relee del listado de seguidos/seguidores en **cada** análisis. Es una sola llamada para toda la lista, así que sale gratis y nunca queda vieja.
- **Contadores** (seguidores, siguiendo, posts) no vienen en ese listado. Pedirlos cuesta **un request por usuario**: ese es el trabajo caro, y el único que puede chocar contra el rate-limit.

Por eso la fila cacheada **no vence nunca** y el TTL solo gobierna los contadores. Un hit total no hace ningún request a Instagram.

Subí `METRICS_TTL_DAYS` = menos requests, números más viejos. Bajalo = números al día a costa de un request por usuario. Si necesitás números frescos en el momento y no querés esperar al TTL, el endpoint de análisis acepta `?refresh=1`, que ignora el TTL y refresca todos los contadores.

---

## Funcionalidades

- **Multi-cuenta**: el servidor auto-carga las sesiones guardadas al arrancar; podés tener varias cuentas activas y cambiar entre ellas desde el nav.
- **Análisis**: seguidos o seguidores, propios o de otro usuario.
- **Caché por cuenta**: al iniciar sesión se muestran automáticamente los usuarios de análisis previos de esa cuenta, sin tocar la API de Instagram.
- **Historial con diff**: cada análisis queda guardado y podés comparar dos corridas del mismo tipo y objetivo para ver quién te dejó de seguir o empezó a seguirte. Cada corrida guarda una foto de los perfiles tal como estaban en ese momento, así que el diff no se rescribe cuando los datos cambian después.
- **Filtros en vivo**: públicos / privados / verificados / mínimo de seguidores / palabra clave en bio, nombre o usuario.
- **Descarga de galerías e historias**: por usuario individual o masiva para todos los resultados.
- **Perfiles JSON**: guardá solo los datos de perfil (sin imágenes) de usuarios no descargados.
- Tabla ordenable, export CSV, barra de progreso en tiempo real (SSE).

---

## Descarga masiva

El botón **"Descargar galerías"** baja la galería + historias de todos los usuarios del listado actual.

- **Cooldown de 24h por usuario**: saltea a quien ya se descargó recientemente.
- **Ritmo adaptativo**: pausa más larga a mayor tamaño del lote para no gatillar el rate-limit.
- **Corre en segundo plano**: podés cerrar la pestaña; el trabajo sigue en el servidor.
- **Cancelable** en cualquier momento, conserva lo ya bajado.

### Monitorear desde la terminal

```bash
cd backend
python jobs_cli.py             # lista los trabajos una vez
python jobs_cli.py --watch     # refresca cada 2s (Ctrl-C para salir)
python jobs_cli.py --cancel <job_id>
```

---

## Autenticación

- Al iniciar sesión se guarda `session_<usuario>.json` en `SESSIONS_DIR` (Docker: `data/sessions/`) y se reutiliza en el próximo arranque del servidor sin pedir contraseña.
- Si tenés **2FA**, se solicita el código al loguear.
- Si Instagram pide verificación adicional (**Challenge**), aprobala desde la app móvil y reintentá.
- Si aparece *"Your version of Instagram is out of date"*: `instagrapi` se está identificando con una versión vieja de la app. Actualizalo (`pip install -U instagrapi`; con 3.0.25 funciona la versión `449.x`) y **reconstruí** el AppImage o la imagen de Docker, porque cada uno trae su propia copia. Si una cuenta guardada sigue fallando, borrá su `session_<usuario>.json` para forzar un login limpio.

---

## Rate-limit

La app usa la API **privada** de Instagram vía `instagrapi`. Delays aplicados automáticamente:

- `2–5s` por request (delay base del cliente)
- `4–8s` por usuario en análisis, `40–70s` cada 30 usuarios
- Pausa adaptativa entre usuarios en descarga masiva

Estos delays se aplican **solo cuando hay que consultar a Instagram**. Un perfil que ya está en la caché con contadores frescos se sirve sin request y sin espera, así que un análisis repetido es prácticamente instantáneo.

Si Instagram devuelve *"Please wait a few minutes"*: **pará y esperá**. Reintentar lo empeora. Si un refresco falla pero el perfil ya estaba cacheado, la app lo muestra igual con los contadores viejos en vez de sacarlo de la tabla.

---

## Script CLI

Alternativa sin web ni base de datos:

```bash
pip install -r requirements.txt
python main.py
```

Pide usuario y contraseña, lista los seguidos con más de 1000 seguidores y exporta a `.txt`.

---

## Archivos generados (no commiteados)

| Ruta | Contenido |
|---|---|
| `data/sessions/session_*.json` (Docker) | Sesiones de Instagram (credenciales — nunca commitear) |
| `data/downloads/` (Docker) | Galerías, historias, `metadata.json`, `index.json` |
| `~/.local/share/dev.grapi.desktop/` | Datos de la app de escritorio: sesiones, descargas, `settings.json` |
| `src-tauri/target/`, `src-tauri/binaries/`, `app/out/`, `build/`, `dist/` | Artefactos de build (ignorados) |
| `data/db/app.db` | Base SQLite de la caché y el historial (Docker) |
| `.env` | Variables de entorno |

# grapi

Analizador de seguidores/seguidos de Instagram con descarga de galerías e historias.

**Stack**: FastAPI + PostgreSQL · Next.js 15 · instagrapi

---

## Levantar el proyecto

### Opción A — Docker (recomendada, un solo comando)

```bash
cp .env.example .env          # ajustá credenciales si querés; los defaults funcionan
docker compose up --build
```

| Servicio   | URL                        | Rol |
|------------|----------------------------|-----|
| Frontend   | http://localhost:5174       | Next.js (dev server con hot-reload) |
| Backend    | http://localhost:8000       | FastAPI; corre `alembic upgrade head` al arrancar |
| Postgres   | localhost:5432              | Caché de perfiles e historial de corridas |

Con `docker compose watch` (Docker Desktop o CLI ≥ 2.22) los cambios en `frontend/` y `backend/` se sincronizan sin rebuild.

### Opción B — local sin Docker

**Requisitos:** Python 3.11+, Node 20+, PostgreSQL 15+ (o solo el contenedor de DB)

```bash
# 1. Solo la DB en Docker (opcional pero conveniente)
docker compose up -d db

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example ../.env                          # ajustar DATABASE_URL si no usás Docker
alembic upgrade head                                # crea/migra las tablas
uvicorn main:app --reload                           # http://localhost:8000

# 3. Frontend (en otra terminal)
cd frontend
npm install
npm run dev                                         # http://localhost:3000
```

> ⚠️ `uvicorn --reload` reinicia el proceso en cada guardado del backend, lo que **borra las sesiones en memoria**. Tenés que volver a iniciar sesión después de cada cambio.

Postgres es **opcional**: si no está disponible, el backend degrada a sin caché/sin historial en vez de fallar.

---

## Variables de entorno

Copiá `.env.example` a `.env`. Los valores por defecto levantan todo sin cambios.

| Variable | Default | Descripción |
|---|---|---|
| `POSTGRES_USER` | `iguser` | Usuario de Postgres |
| `POSTGRES_PASSWORD` | `igpass` | Contraseña de Postgres |
| `POSTGRES_DB` | `igdb` | Nombre de la base |
| `CACHE_TTL_DAYS` | `7` | Días que vale un perfil cacheado |
| `GALLERY_TTL_HOURS` | `24` | Cooldown entre descargas del mismo usuario |
| `ECHO_SQL` | `0` | Loguear SQL (debug) |

---

## Funcionalidades

- **Multi-cuenta**: el servidor auto-carga las sesiones guardadas al arrancar; podés tener varias cuentas activas y cambiar entre ellas desde el nav.
- **Análisis**: seguidos o seguidores, propios o de otro usuario.
- **Caché por cuenta**: al iniciar sesión se muestran automáticamente los usuarios de análisis previos de esa cuenta, sin tocar la API de Instagram.
- **Historial con diff**: cada análisis queda guardado; podés comparar dos corridas para ver quién te dejó de seguir o empezó a seguirte.
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

- Al iniciar sesión se guarda `backend/sessions/session_<usuario>.json` y se reutiliza en el próximo arranque del servidor sin pedir contraseña.
- Si tenés **2FA**, se solicita el código al loguear.
- Si Instagram pide verificación adicional (**Challenge**), aprobala desde la app móvil y reintentá.

---

## Rate-limit

La app usa la API **privada** de Instagram vía `instagrapi`. Delays aplicados automáticamente:

- `2–5s` por request (delay base del cliente)
- `4–8s` por usuario en análisis, `40–70s` cada 30 usuarios
- Pausa adaptativa entre usuarios en descarga masiva

Si Instagram devuelve *"Please wait a few minutes"*: **pará y esperá**. Reintentar lo empeora.

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
| `backend/sessions/session_*.json` | Sesiones de Instagram (credenciales — nunca commitear) |
| `backend/downloads/` | Galerías, historias, `metadata.json`, `index.json` |
| `.env` | Variables de entorno con credenciales de DB |

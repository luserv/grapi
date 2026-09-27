"""
API REST con FastAPI para el analizador de seguidores de Instagram.
"""
import asyncio
import json
import threading
import uuid
import requests as req_lib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import repository
from config import settings
from database import SessionLocal, session_scope
from instagram import autenticar_instagram, obtener_usuarios
from instagrapi.exceptions import ChallengeRequired, LoginRequired, TwoFactorRequired
import downloader

app = FastAPI(title="Instagram Followers Analyzer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sesiones activas: session_id -> Client
sessions: dict[str, object] = {}


@app.on_event("startup")
async def load_saved_sessions():
    """Al arrancar, carga todas las sesiones guardadas en SESSIONS_DIR sin
    hacer requests a Instagram (solo lee el JSON del disco). La validación
    ocurre la primera vez que se usa cada sesión."""
    from instagrapi import Client
    sessions_dir = Path(settings.SESSIONS_DIR)
    if not sessions_dir.exists():
        return
    for session_file in sorted(sessions_dir.glob("session_*.json")):
        username = session_file.stem.replace("session_", "", 1)
        session_id = f"auto_{username}"
        if session_id in sessions:
            continue
        try:
            cl = Client()
            cl.delay_range = [2, 5]
            cl.load_settings(str(session_file))
            cl.username = username
            sessions[session_id] = cl
        except Exception:
            pass

# Un hilo por consulta larga de seguidores
executor = ThreadPoolExecutor(max_workers=4)

# Descargas masivas (background). job_id -> registro con estado + maquinaria.
# Viven en memoria: sobreviven a que cierres la pestaña, NO a reiniciar el server.
bulk_jobs: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str
    verification_code: str = ""


class DownloadAllUser(BaseModel):
    username: str
    pk: int | None = None


class DownloadAllRequest(BaseModel):
    session_id: str
    users: list[DownloadAllUser]
    ttl_hours: int | None = None
    mode: str = "full"  # "full" | "profiles"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/login")
def login(req: LoginRequest):
    """
    Autentica al usuario en Instagram y devuelve un session_id.
    Si la cuenta tiene 2FA activo y no se envió verification_code,
    responde con 401 y detail="2FA_REQUIRED".
    """
    try:
        session_file = str(Path(settings.SESSIONS_DIR) / f"session_{req.username}.json")
        cl = autenticar_instagram(
            req.username,
            req.password,
            verification_code=req.verification_code or None,
            session_file=session_file,
        )
        session_id = str(uuid.uuid4())
        sessions[session_id] = cl
        return {"session_id": session_id, "username": cl.username}

    except TwoFactorRequired:
        raise HTTPException(status_code=401, detail="2FA_REQUIRED")
    except ChallengeRequired:
        raise HTTPException(status_code=401, detail="CHALLENGE_REQUIRED")
    except LoginRequired:
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/seguidores/stream")
async def seguidores_stream(
    session_id: str = Query(...),
    modo: str = Query("following"),
    target_username: str = Query(None),
):
    """
    Server-Sent Events: emite eventos de progreso y resultados mientras
    recorre los seguidores del usuario autenticado o de target_username.

    Eventos JSON:
        {"type": "total",    "total": int}
        {"type": "progress", "idx": int, "total": int, "found": int}
        {"type": "match",    "idx": int, "total": int, "usuario": {...}}
        {"type": "error",    "idx": int, "msg": str}
        {"type": "done",     "total_found": int}
    """
    cl = sessions.get(session_id)
    if not cl:
        raise HTTPException(status_code=401, detail="Sesión no válida o expirada")

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def on_progress(event: dict):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def run_fetch():
        # Intentar abrir DB (caché). Si Postgres no está disponible,
        # degradar a modo sin caché en vez de romper el análisis.
        db = None
        try:
            db = SessionLocal()
            db.connection()  # fuerza la conexión ahora para detectar caídas
        except Exception:
            if db is not None:
                db.close()
            db = None

        try:
            target_uid = None
            if target_username:
                target_uid = str(cl.user_id_from_username(target_username))

            obtener_usuarios(
                cl, modo, on_progress,
                target_user_id=target_uid,
                session=db, ttl_days=settings.CACHE_TTL_DAYS,
            )
        except Exception as e:
            if db is not None:
                db.rollback()
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "fatal_error", "msg": str(e)}
            )
        finally:
            if db is not None:
                db.close()

    loop.run_in_executor(executor, run_fetch)

    async def event_stream():
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in ("done", "fatal_error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )



@app.get("/api/proxy-image")
def proxy_image(url: str = Query(...)):
    """Proxy transparente para imágenes de perfil. Sin auth (CDN pública)."""
    try:
        resp = req_lib.get(
            url, timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
                "Accept": "image/webp,image/png,image/*,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.instagram.com/",
            },
            stream=True,
        )
        resp.raise_for_status()
        return Response(
            content=resp.content,
            media_type=resp.headers.get("content-type", "image/jpeg"),
            headers={"Cache-Control": "private, max-age=86400"},
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al obtener imagen: {e}")


@app.get("/api/posts")
def get_posts(
    session_id: str = Query(...),
    username: str = Query(...),
    cantidad: int = Query(24),
):
    """Devuelve los posts de un usuario con URLs de alta resolución."""
    cl = sessions.get(session_id)
    if not cl:
        raise HTTPException(status_code=401, detail="Sesión no válida o expirada")
    try:
        user_id = str(cl.user_id_from_username(username))
        medias = cl.user_medias(user_id, cantidad)
        posts = []
        for m in medias:
            post = {
                "id": str(m.pk),
                "media_type": m.media_type,  # 1=foto, 2=video, 8=álbum
                "thumbnail_url": str(m.thumbnail_url) if m.thumbnail_url else None,
                "video_url": str(m.video_url) if m.video_url else None,
                "caption": (m.caption_text or "")[:200],
                "taken_at": m.taken_at.isoformat() if m.taken_at else None,
                "resources": [],
            }
            if m.media_type == 8 and m.resources:
                for r in m.resources:
                    post["resources"].append({
                        "media_type": r.media_type,
                        "thumbnail_url": str(r.thumbnail_url) if r.thumbnail_url else None,
                        "video_url": str(r.video_url) if r.video_url else None,
                    })
            posts.append(post)
        return {"posts": posts, "username": username}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download")
def download_media(
    session_id: str = Query(...),
    url: str = Query(...),
    filename: str = Query("media.jpg"),
):
    """Descarga un archivo de Instagram y lo sirve al cliente."""
    if not sessions.get(session_id):
        raise HTTPException(status_code=401, detail="Sesión no válida o expirada")
    try:
        resp = req_lib.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/jpeg")
        return Response(
            content=resp.content,
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/logout")
def logout(session_id: str):
    sessions.pop(session_id, None)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Descargas locales (galería + historias)
# ---------------------------------------------------------------------------

@app.post("/api/download-user")
def api_download_user(
    session_id: str = Query(...),
    username: str = Query(...),
    user_id: str = Query(None),
):
    cl = sessions.get(session_id)
    if not cl:
        raise HTTPException(status_code=401, detail="Sesión no válida o expirada")
    try:
        metadata, new_items = downloader.download_user(cl, username, user_id=user_id)
        return {
            "username": username,
            "gallery": len(metadata["gallery"]),
            "stories": len(metadata["stories"]),
            "new_gallery": new_items["gallery"],
            "new_stories": new_items["stories"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download-user/stream")
async def api_download_user_stream(
    session_id: str = Query(...),
    username: str = Query(...),
    user_id: str = Query(None),
    sections: str = Query("gallery,stories,highlights"),
):
    """SSE: descarga galería + historias de un usuario con progreso en tiempo real.
    sections: coma-separado, ej. \"gallery,stories\" o solo \"stories\"."""
    cl = sessions.get(session_id)
    if not cl:
        raise HTTPException(status_code=401, detail="Sesión no válida o expirada")

    sections_list = [s.strip() for s in sections.split(",")]

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def on_progress(event: dict):
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def run_download():
        try:
            downloader.download_user(cl, username, user_id=user_id, on_progress=on_progress, sections=sections_list)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "msg": str(e)})

    loop.run_in_executor(executor, run_download)

    async def event_stream():
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in ("done", "fatal_error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _apply_event_to_state(st: dict, ev: dict):
    """Actualiza el snapshot del job con un evento de progreso. Esto permite
    que un cliente que se reconecta (o el CLI) vea el estado actual sin haber
    seguido el stream desde el principio."""
    t = ev.get("type")
    if t == "bulk_start":
        st["total"] = ev.get("total", st["total"])
        st["pacing"] = ev.get("pacing")
    elif t in ("user_start", "user_skipped"):
        st["idx"] = ev.get("idx", st["idx"])
        st["current"] = ev.get("username", "")
        if t == "user_skipped":
            st["detail"] = f"salteado (hace {ev.get('age_hours')}h)"
        else:
            st["detail"] = "iniciando…"
    elif t == "user_done":
        st["detail"] = f"✓ +{ev.get('new_gallery', 0)} galería, +{ev.get('new_stories', 0)} historias, +{ev.get('new_highlights', 0)} destacadas"
    elif t == "user_error":
        st["detail"] = f"✗ {ev.get('msg', '')}"
    elif t == "resting":
        st["detail"] = f"descanso anti rate-limit ({ev.get('seconds')}s)…"
    elif ev.get("scope") == "item":
        sec_map = {"gallery": "Galería", "stories": "Historias", "highlights": "Destacadas"}
        sec = sec_map.get(ev.get("section"), "Medios")
        if t == "phase":
            st["detail"] = ev.get("label", "")
        elif t == "total":
            st["detail"] = f"{sec}: 0/{ev.get('total')}"
        elif t == "download":
            st["detail"] = f"{sec}: {ev.get('current')}/{ev.get('total')}"
    elif t == "bulk_done":
        st["downloaded"] = ev.get("downloaded", 0)
        st["skipped"] = ev.get("skipped", 0)
        st["failed"] = ev.get("failed", 0)
        st["status"] = "cancelled" if ev.get("cancelled") else "done"
        st["finished_at"] = _now_iso()
        st["current"] = ""
        st["detail"] = ""
    elif t == "fatal_error":
        st["status"] = "error"
        st["error"] = ev.get("msg")
        st["finished_at"] = _now_iso()


def _now_iso():
    import time as _t
    return _t.strftime("%Y-%m-%dT%H:%M:%S")


def _prune_jobs(keep_finished: int = 10):
    """Limpia jobs terminados viejos para no acumular en memoria; deja siempre
    los que están corriendo."""
    finished = [(jid, j) for jid, j in bulk_jobs.items()
                if j["state"]["status"] != "running"]
    finished.sort(key=lambda kv: kv[1]["state"].get("finished_at") or "")
    for jid, _ in finished[:-keep_finished] if len(finished) > keep_finished else []:
        bulk_jobs.pop(jid, None)


@app.post("/api/download-all")
async def api_download_all(req: DownloadAllRequest):
    """Arranca una descarga masiva EN BACKGROUND y devuelve su job_id.

    No streamea: el trabajo corre detached en el threadpool y actualiza un
    snapshot en memoria. El cliente se suscribe aparte (GET .../stream) o
    consulta el estado (.../status, /api/download-jobs). Así la descarga
    sobrevive a que cierres la pestaña o cambies de vista."""
    cl = sessions.get(req.session_id)
    if not cl:
        raise HTTPException(status_code=401, detail="Sesión no válida o expirada")

    users = [{"username": u.username, "pk": u.pk} for u in req.users]
    ttl_hours = req.ttl_hours if req.ttl_hours is not None else settings.GALLERY_TTL_HOURS

    _prune_jobs()
    job_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    cancel_event = threading.Event()
    job = {
        "id": job_id,
        "state": {
            "id": job_id,
            "status": "running",
            "total": len(users),
            "idx": 0,
            "current": "",
            "detail": "",
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "started_at": _now_iso(),
            "finished_at": None,
            "error": None,
        },
        "cancel": cancel_event,
        "subscribers": [],
    }
    bulk_jobs[job_id] = job

    def fanout(event: dict):
        # Corre en el hilo del event loop (vía call_soon_threadsafe): seguro
        # para tocar el snapshot y la lista de suscriptores.
        _apply_event_to_state(job["state"], event)
        for q in list(job["subscribers"]):
            q.put_nowait(event)

    def on_progress(event: dict):
        loop.call_soon_threadsafe(fanout, event)

    def run_bulk():
        try:
            if req.mode == "profiles":
                downloader.save_profiles_batch(
                    cl, users, on_progress=on_progress,
                    should_cancel=cancel_event.is_set,
                )
            else:
                downloader.download_many(
                    cl, users, on_progress=on_progress, ttl_hours=ttl_hours,
                    should_cancel=cancel_event.is_set,
                )
        except Exception as e:
            loop.call_soon_threadsafe(fanout, {"type": "fatal_error", "msg": str(e)})

    loop.run_in_executor(executor, run_bulk)
    return {"job_id": job_id, "total": len(users)}


@app.get("/api/download-all/stream")
async def api_download_all_stream(job_id: str = Query(...)):
    """Stream SSE de un job en curso. Emite primero un 'snapshot' con el estado
    actual (para reconexiones) y luego los eventos en vivo. Si el job ya
    terminó, manda el snapshot y cierra."""
    job = bulk_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    q: asyncio.Queue = asyncio.Queue()
    job["subscribers"].append(q)

    async def event_stream():
        try:
            yield f"data: {json.dumps({'type': 'snapshot', **job['state']})}\n\n"
            if job["state"]["status"] != "running":
                return
            while True:
                event = await q.get()
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("bulk_done", "fatal_error"):
                    break
        finally:
            if q in job["subscribers"]:
                job["subscribers"].remove(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/download-jobs")
def api_download_jobs():
    """Lista los jobs de descarga masiva (en curso + terminados recientes)."""
    return {"jobs": [j["state"] for j in bulk_jobs.values()]}


@app.get("/api/download-all/status")
def api_download_all_status(job_id: str = Query(...)):
    job = bulk_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return job["state"]


@app.post("/api/download-all/cancel")
def api_download_all_cancel(job_id: str = Query(...)):
    """Cancela una descarga masiva en curso. El hilo corta de forma ordenada
    entre items/usuarios (guarda lo ya bajado) y emite bulk_done cancelled."""
    job = bulk_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado o ya terminó")
    job["cancel"].set()
    return {"ok": True}


@app.get("/api/sessions")
def api_list_sessions():
    """Lista todas las sesiones activas en memoria (incluyendo las auto-cargadas al arrancar)."""
    return {"sessions": [
        {"session_id": sid, "username": getattr(cl, "username", sid)}
        for sid, cl in sessions.items()
    ]}


@app.get("/api/session")
def api_check_session(session_id: str = Query(...)):
    """Valida que la sesión en memoria siga viva. El frontend lo usa para
    distinguir 'sesión expirada' (p. ej. tras reiniciar el backend) de un
    error de red, ya que un EventSource no puede leer el status 401."""
    if session_id not in sessions:
        raise HTTPException(status_code=401, detail="Sesión no válida o expirada")
    return {"ok": True, "username": getattr(sessions[session_id], "username", None)}


@app.get("/api/history/users")
def api_history_users(q: str = Query(""), limit: int = Query(20), owner: str = Query(None)):
    """Busca usuarios cacheados en la BD local por username o full_name.
    Si se pasa owner, filtra por usuarios que aparecen en corridas de esa cuenta."""
    with session_scope() as db:
        users = repository.search_users(db, q=q, limit=limit, owner_username=owner or None)
        return {"users": [repository.user_to_dict(u) for u in users]}


@app.get("/api/downloads")
def api_list_downloads():
    return {"users": downloader.list_downloads()}


@app.get("/api/downloads/pending")
def downloads_pending():
    """Cruza instagram_users (caché local) contra el directorio de descargas.
    Devuelve quién tiene contenido, quién no, y el conteo de archivos.
    No hace ningún request a Instagram."""
    downloads_base = Path(settings.DOWNLOADS_DIR)

    with session_scope() as db:
        users = repository.search_users(db, q="", limit=10_000)

    pending = []
    downloaded = []

    for user in users:
        user_dir = downloads_base / user.username
        gallery_dir = user_dir / "gallery"
        has_metadata = (user_dir / "metadata.json").exists()
        file_count = 0
        if gallery_dir.exists():
            file_count = sum(
                1 for f in gallery_dir.iterdir()
                if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".mp4", ".webp")
            )
        entry = {
            "username": user.username,
            "full_name": user.full_name,
            "follower_count": user.follower_count,
            "is_verified": user.is_verified,
            "profile_pic_url": user.profile_pic_url,
            "file_count": file_count,
        }
        if has_metadata and file_count > 0:
            downloaded.append(entry)
        else:
            pending.append(entry)

    pending.sort(key=lambda u: u["follower_count"], reverse=True)
    downloaded.sort(key=lambda u: u["file_count"], reverse=True)

    return {
        "total_cached": len(users),
        "pending_count": len(pending),
        "downloaded_count": len(downloaded),
        "pending": pending,
        "downloaded": downloaded,
    }


@app.get("/api/downloads/{username}")
def api_user_downloads(username: str):
    data = downloader.get_user_media(username)
    if data is None:
        raise HTTPException(status_code=404, detail="Usuario no descargado")
    return data


@app.get("/api/downloads/{username}/files/{filename:path}")
def api_serve_download(username: str, filename: str):
    filepath = downloader.BASE_DIR / username / filename
    if not filepath.exists():
        filepath = downloader.BASE_DIR / username / "gallery" / filename
    if not filepath.exists():
        filepath = downloader.BASE_DIR / username / "stories" / filename
    if not filepath.exists():
        filepath = downloader.BASE_DIR / username / "highlights" / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    from fastapi.responses import FileResponse
    return FileResponse(str(filepath))


# ---------------------------------------------------------------------------
# Servir el frontend (debe ir al final para no pisar las rutas /api)
# ---------------------------------------------------------------------------

# En desarrollo usa `npm run dev` en frontend/ (puerto 5173 con proxy a /api).
# En producción ejecuta `npm run build` y FastAPI sirve el build generado.
frontend_path = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")

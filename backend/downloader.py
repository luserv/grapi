import json
import os
import random
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable

import requests
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ClientError, RateLimitError

from config import settings

BASE_DIR = Path(settings.DOWNLOADS_DIR)


def _user_dir(username):
    return BASE_DIR / username


def _media_dir(username, media_type):
    d = _user_dir(username) / media_type
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename(taken_at, pk, ext):
    ts = taken_at.strftime("%Y-%m-%d_%H%M%S")
    return f"{ts}_{pk}.{ext}"


def _ext_from_media(m):
    url = getattr(m, "video_url", None) or getattr(m, "thumbnail_url", "") or ""
    if ".mp4" in str(url) or m.media_type == 2:
        return "mp4"
    return "jpg"


def _load_metadata(username):
    path = _user_dir(username) / "metadata.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"username": username, "gallery": [], "stories": []}


def _save_metadata(username, metadata):
    path = _user_dir(username) / "metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2, default=str))


def _update_index(username):
    meta = _load_metadata(username)
    index_path = BASE_DIR / "index.json"
    if index_path.exists():
        idx = json.loads(index_path.read_text())
    else:
        idx = {}
    idx[username] = {
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gallery": sum(1 for e in meta["gallery"] if e.get("filename")),
        "stories": sum(1 for e in meta["stories"] if e.get("filename")),
        "user_pk": meta.get("user_pk"),
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(idx, indent=2))


def _download_file(cl, url, filepath, retries=3):
    if os.path.exists(filepath):
        return filepath
    # El CDN de Instagram (scontent.*.fbcdn.net) sirve URLs pre-firmadas de forma
    # anónima. Hay que pedirlas con un requests "pelado" —igual que instagrapi en
    # photo_download_by_url—; mandarle los headers/cookies de la API privada las
    # rechaza. (El Client NO tiene .session; usar cl.session lanzaba AttributeError.)
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=headers, stream=True, timeout=120)
            r.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
            return filepath
        except Exception:
            if os.path.exists(filepath):
                os.remove(filepath)  # no dejar archivos a medio escribir
            if attempt == retries:
                raise
            time.sleep(random.uniform(3, 6))


def _existing_pks(metadata, username):
    """PKs cuyo archivo está efectivamente en disco.
    Excluye descargas fallidas (filename=None) y archivos borrados manualmente."""
    gallery_dir = _user_dir(username) / "gallery"
    stories_dir = _user_dir(username) / "stories"
    pks = set()
    for item in metadata.get("gallery", []):
        fname = item.get("filename")
        if fname and (gallery_dir / fname).exists():
            pks.add(item["pk"])
    for item in metadata.get("stories", []):
        fname = item.get("filename")
        if fname and (stories_dir / fname).exists():
            pks.add(item["pk"])
    return pks


def _emit(callback, event):
    if callback:
        callback(event)


def _cancelled(should_cancel) -> bool:
    return bool(should_cancel and should_cancel())


def _interruptible_sleep(seconds, should_cancel=None):
    """Duerme `seconds`, pero corta apenas should_cancel() sea True para que
    la cancelación no tenga que esperar la pausa entera."""
    if not should_cancel:
        time.sleep(seconds)
        return
    end = time.time() + seconds
    while time.time() < end:
        if should_cancel():
            return
        time.sleep(min(0.5, max(0.0, end - time.time())))


def _fetch_medias(cl, user_id, on_progress):
    """Obtiene medias via API privada v1 (evita la GraphQL pública que Instagram
    bloquea frecuentemente devolviendo HTML en lugar de JSON)."""
    try:
        return cl.user_medias_v1(user_id, amount=0)
    except RateLimitError as e:
        _emit(on_progress, {"type": "error", "msg": f"Rate limit de Instagram al obtener posts: {e}"})
    except ClientError as e:
        _emit(on_progress, {"type": "error", "msg": f"Error de API al obtener posts: {e}"})
    except Exception as e:
        _emit(on_progress, {"type": "error", "msg": f"No se pudieron obtener los posts: {e}"})
    return []


def download_user(cl, username, user_id=None, on_progress: Callable = None, should_cancel=None, sections=None):
    if sections is None:
        sections = ["gallery", "stories"]
    metadata = _load_metadata(username)

    if user_id is None:
        user_id = metadata.get("user_pk")
    if user_id is not None:
        user_id = str(user_id)
    else:
        _emit(on_progress, {"type": "phase", "label": "Resolviendo usuario (espera 30s para evitar rate-limit)..."})
        time.sleep(random.uniform(25, 35))
        for attempt in range(3):
            try:
                user_id = str(cl.user_info_by_username_v1(username).pk)
                break
            except Exception as e:
                if attempt == 2:
                    _emit(on_progress, {"type": "fatal_error", "msg": f"No se pudo resolver @{username} tras 3 intentos (rate-limit de Instagram). Esperá unos minutos y probá de nuevo."})
                    return None, None
                _emit(on_progress, {"type": "error", "msg": f"Intento {attempt+1}/3 falló al resolver @{username}. Reintentando en 30-45s..."})
                time.sleep(random.uniform(30, 45))

    metadata["user_pk"] = user_id
    seen = _existing_pks(metadata, username)
    new_items = {"gallery": 0, "stories": 0}

    # ── Galería ──
    total = 0
    if "gallery" in sections:
        _emit(on_progress, {"type": "phase", "label": "Obteniendo lista de posts..."})
        time.sleep(random.uniform(2, 5))
        medias = _fetch_medias(cl, user_id, on_progress)

        gallery_dir = _media_dir(username, "gallery")
        total = len(medias)
        _emit(on_progress, {"type": "total", "total": total, "section": "gallery"})

        for idx, m in enumerate(medias, 1):
            if _cancelled(should_cancel):
                break
            _emit(on_progress, {"type": "download", "current": idx, "total": total, "section": "gallery"})
            if m.pk in seen:
                continue

            # Limpiar entradas fallidas/borradas de este PK antes de re-bajar
            metadata["gallery"] = [
                e for e in metadata["gallery"]
                if not (e["pk"] == m.pk and (
                    not e.get("filename") or not (gallery_dir / e["filename"]).exists()
                ))
            ]

            items_to_dl = []

            if m.media_type == 8 and m.resources:
                for i, r in enumerate(m.resources):
                    url = str(r.video_url or r.thumbnail_url or "")
                    if not url:
                        continue
                    ext_r = "mp4" if r.media_type == 2 or ".mp4" in url else "jpg"
                    filename = _safe_filename(m.taken_at, f"{m.pk}_{i}", ext_r)
                    items_to_dl.append((url, filename, r.media_type))
            else:
                url = str(m.video_url or m.thumbnail_url or "")
                if not url:
                    continue
                filename = _safe_filename(m.taken_at, m.pk, _ext_from_media(m))
                items_to_dl.append((url, filename, m.media_type))

            for url, filename, media_type in items_to_dl:
                downloaded = False
                try:
                    _download_file(cl, url, gallery_dir / filename)
                    downloaded = True
                    new_items["gallery"] += 1
                except Exception as e:
                    _emit(on_progress, {"type": "error", "msg": f"No se pudo bajar {filename}: {e}"})
                metadata["gallery"].append({
                    "pk": m.pk,
                    "filename": filename if downloaded else None,
                    "taken_at": m.taken_at.isoformat(),
                    "media_type": media_type,
                    "thumbnail_url": url,
                })

            time.sleep(random.uniform(0.5, 1.5))

    # ── Historias ──
    total_stories = 0
    if "stories" not in sections:
        _save_metadata(username, metadata)
        _update_index(username)
        _emit(on_progress, {"type": "done",
                            "gallery": len(metadata["gallery"]),
                            "stories": len(metadata["stories"]),
                            "new_gallery": new_items["gallery"],
                            "new_stories": new_items["stories"]})
        return metadata, new_items

    if _cancelled(should_cancel):
        _save_metadata(username, metadata)
        _update_index(username)
        return metadata, new_items

    _emit(on_progress, {"type": "phase", "label": "Descargando historias..."})
    stories_dir = _media_dir(username, "stories")
    # story_sources: (pk, taken_at, url, filename, media_type, highlight_title)
    story_sources = []

    # user_stories_v1 usa solo la API privada móvil. No usamos user_stories() porque
    # su fallback a la GraphQL pública dispara el "scraping_warning" de Instagram.
    try:
        stories = cl.user_stories_v1(user_id)
        for s in stories:
            if s.pk in seen:
                continue
            url = str(s.video_url or s.thumbnail_url or "")
            if not url:
                continue
            ext = "mp4" if s.media_type == 2 or ".mp4" in url else "jpg"
            filename = _safe_filename(s.taken_at, s.pk, ext)
            story_sources.append((int(s.pk), s.taken_at, url, filename, s.media_type, None))
    except Exception as e:
        _emit(on_progress, {"type": "error", "msg": f"Error al obtener stories activas: {e}"})

    # highlight_info_v1 usa feed/reels_media/ (API privada). No llamamos a
    # highlight_stories() porque no existe en esta versión de instagrapi.
    try:
        highlights = cl.user_highlights_v1(user_id)
        for h in highlights:
            try:
                h_full = cl.highlight_info_v1(h.pk)
            except Exception as e:
                _emit(on_progress, {"type": "error", "msg": f"Error al obtener highlight '{h.title}': {e}"})
                continue
            for s in h_full.items:
                if s.pk in seen:
                    continue
                url = str(s.video_url or s.thumbnail_url or "")
                if not url:
                    continue
                ext = "mp4" if s.media_type == 2 or ".mp4" in url else "jpg"
                filename = _safe_filename(s.taken_at, s.pk, ext)
                story_sources.append((int(s.pk), s.taken_at, url, filename, s.media_type, h.title))
    except Exception as e:
        _emit(on_progress, {"type": "error", "msg": f"Error al obtener highlights: {e}"})

    total_stories = len(story_sources)
    _emit(on_progress, {"type": "total", "total": total_stories, "section": "stories"})

    for idx, (story_pk, taken_at, url, filename, media_type, highlight_title) in enumerate(story_sources, 1):
        if _cancelled(should_cancel):
            break
        _emit(on_progress, {"type": "download", "current": idx, "total": total_stories, "filename": filename, "section": "stories"})

        # Limpiar entradas fallidas/borradas de este PK antes de re-bajar
        metadata["stories"] = [
            e for e in metadata["stories"]
            if not (e["pk"] == story_pk and (
                not e.get("filename") or not (stories_dir / e["filename"]).exists()
            ))
        ]

        downloaded = False
        try:
            _download_file(cl, url, stories_dir / filename)
            downloaded = True
            new_items["stories"] += 1
        except Exception as e:
            _emit(on_progress, {"type": "error", "msg": f"No se pudo bajar {filename}: {e}"})
        entry = {
            "pk": story_pk,
            "filename": filename if downloaded else None,
            "taken_at": taken_at.isoformat() if hasattr(taken_at, "isoformat") else str(taken_at),
            "media_type": media_type,
            "thumbnail_url": url,
        }
        if highlight_title:
            entry["highlight"] = highlight_title
        metadata["stories"].append(entry)
        time.sleep(random.uniform(0.5, 1.5))

    _save_metadata(username, metadata)
    _update_index(username)

    total_new = new_items["gallery"] + new_items["stories"]
    if total_new == 0 and total == 0 and total_stories == 0:
        _emit(on_progress, {"type": "error", "msg": "No se encontraron posts ni historias nuevas para descargar."})

    _emit(on_progress, {
        "type": "done",
        "gallery": len(metadata["gallery"]),
        "stories": len(metadata["stories"]),
        "new_gallery": new_items["gallery"],
        "new_stories": new_items["stories"],
    })

    return metadata, new_items


def list_downloads():
    index_path = BASE_DIR / "index.json"
    if index_path.exists():
        return json.loads(index_path.read_text())
    return {}


# ── Descarga masiva con estado por usuario ───────────────────────────

def last_downloaded_at(username) -> datetime | None:
    """Última vez que se descargó este usuario (del index.json), o None."""
    idx = list_downloads()
    entry = idx.get(username) if isinstance(idx, dict) else None
    if not entry:
        return None
    ts = entry.get("downloaded_at")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def download_state(username, ttl_hours: int = 24) -> dict:
    """Estado de descarga de un usuario: si ya se bajó, hace cuánto, y si
    sigue 'fresco' (dentro del cooldown) o conviene re-bajarlo."""
    last = last_downloaded_at(username)
    if last is None:
        return {"downloaded": False, "last": None, "age_hours": None, "fresh": False}
    age_hours = (datetime.now() - last).total_seconds() / 3600
    return {
        "downloaded": True,
        "last": last.isoformat(),
        "age_hours": round(age_hours, 1),
        "fresh": age_hours < ttl_hours,
    }


def pacing_for(total: int) -> dict:
    """Ritmo anti rate-limit según el tamaño del lote. A más usuarios, más
    pausa entre cada uno + un descanso largo periódico, para no acumular
    demasiadas llamadas a la API privada en poco tiempo.

    Devuelve los segundos de pausa entre usuarios y la cadencia de descanso.
    El frontend usa esta misma tabla para estimar la duración.
    """
    if total <= 20:
        return {"delay": (8, 15),  "rest_every": 0,  "rest": (0, 0)}
    if total <= 80:
        return {"delay": (15, 30), "rest_every": 30, "rest": (45, 90)}
    return {"delay": (25, 45), "rest_every": 25, "rest": (90, 180)}


def download_many(cl, users, on_progress: Callable = None, ttl_hours: int = 24,
                  should_cancel=None):
    """Descarga la galería + historias de varios usuarios, en serie.

    `users`: lista de dicts {"username": str, "pk": int|None}. Pasar el pk
    evita resolver username→id (un request menos por usuario).

    Saltea a quien se haya bajado hace menos de `ttl_hours` (cooldown: las
    historias caducan a diario, así que re-bajar antes de 24h casi no aporta).
    Entre usuarios espera 15–30s para no gatillar el rate-limit de Instagram.

    `should_cancel`: callable opcional; si devuelve True, corta de forma
    ordenada (entre usuarios y entre items) y termina con cancelled=True.
    """
    total = len(users)
    pace = pacing_for(total)
    _emit(on_progress, {"type": "bulk_start", "total": total, "pacing": pace})
    downloaded = skipped = failed = 0
    cancelled = False
    processed = 0  # usuarios realmente bajados (no salteados): rige el descanso largo

    for idx, u in enumerate(users, 1):
        if _cancelled(should_cancel):
            cancelled = True
            break

        if isinstance(u, dict):
            username, pk = u.get("username"), u.get("pk")
        else:
            username, pk = u, None

        state = download_state(username, ttl_hours)
        if state["fresh"]:
            skipped += 1
            _emit(on_progress, {"type": "user_skipped", "idx": idx, "total": total,
                                "username": username, "last": state["last"],
                                "age_hours": state["age_hours"]})
            continue

        _emit(on_progress, {"type": "user_start", "idx": idx, "total": total,
                            "username": username})

        # Reenvía los eventos finos de download_user etiquetados con el usuario
        # y scope="item", para mostrar el sub-progreso del usuario en curso.
        def inner(ev, _u=username):
            ev = dict(ev)
            ev["username"] = _u
            ev["scope"] = "item"
            _emit(on_progress, ev)

        try:
            metadata, new_items = download_user(cl, username, user_id=pk,
                                                on_progress=inner, should_cancel=should_cancel)
            if metadata is None:
                failed += 1
                _emit(on_progress, {"type": "user_error", "idx": idx, "total": total,
                                    "username": username, "msg": "no se pudo obtener la galería"})
            else:
                downloaded += 1
                _emit(on_progress, {"type": "user_done", "idx": idx, "total": total,
                                    "username": username,
                                    "new_gallery": new_items["gallery"],
                                    "new_stories": new_items["stories"]})
        except Exception as e:
            failed += 1
            _emit(on_progress, {"type": "user_error", "idx": idx, "total": total,
                                "username": username, "msg": str(e)})

        processed += 1

        if _cancelled(should_cancel):
            cancelled = True
            break

        if idx < total:
            # Descanso largo cada N usuarios BAJADOS (los salteados no tocan la API).
            if pace["rest_every"] and processed % pace["rest_every"] == 0:
                rest = random.uniform(*pace["rest"])
                _emit(on_progress, {"type": "resting", "idx": idx, "total": total,
                                    "seconds": round(rest)})
                _interruptible_sleep(rest, should_cancel)
            else:
                _interruptible_sleep(random.uniform(*pace["delay"]), should_cancel)

    _emit(on_progress, {"type": "bulk_done", "total": total,
                        "downloaded": downloaded, "skipped": skipped,
                        "failed": failed, "cancelled": cancelled})


def _profiles_index_path():
    return BASE_DIR / "profiles_index.json"


def _load_profiles_index():
    path = _profiles_index_path()
    return json.loads(path.read_text()) if path.exists() else {}


def _update_profiles_index(username, profile):
    idx = _load_profiles_index()
    idx[username] = {"saved_at": profile["saved_at"], "user_pk": str(profile.get("pk", ""))}
    _profiles_index_path().write_text(json.dumps(idx, indent=2))


def save_profiles_batch(cl, users, on_progress: Callable = None, should_cancel=None):
    """Guarda profile.json para usuarios que no tienen ninguna descarga previa.

    Saltea a quienes ya están en index.json (galería/historias descargadas) o en
    profiles_index.json (perfil ya guardado). Solo hace llamadas user_info — no
    descarga binarios, por eso es mucho más rápido que download_many.
    """
    full_index = list_downloads()
    profiles_index = _load_profiles_index()

    pending = []
    initial_skipped = 0
    for u in users:
        username = u.get("username") if isinstance(u, dict) else u
        if username in full_index or username in profiles_index:
            initial_skipped += 1
        else:
            pending.append(u)

    total = len(pending)
    _emit(on_progress, {"type": "bulk_start", "total": total,
                        "pacing": {"delay": (4, 8), "rest_every": 0, "rest": (0, 0)}})

    done = failed = 0

    for idx, u in enumerate(pending, 1):
        if _cancelled(should_cancel):
            _emit(on_progress, {"type": "bulk_done", "total": total,
                                "downloaded": done, "skipped": initial_skipped,
                                "failed": failed, "cancelled": True})
            return

        username = u.get("username") if isinstance(u, dict) else u
        pk = u.get("pk") if isinstance(u, dict) else None

        _emit(on_progress, {"type": "user_start", "idx": idx, "total": total,
                            "username": username})
        try:
            user_info = cl.user_info_v1(str(pk)) if pk else cl.user_info_by_username_v1(username)
            profile = {
                "pk": int(user_info.pk),
                "username": user_info.username,
                "full_name": user_info.full_name,
                "biography": user_info.biography or "",
                "follower_count": user_info.follower_count,
                "following_count": user_info.following_count,
                "media_count": user_info.media_count,
                "is_verified": user_info.is_verified,
                "is_private": user_info.is_private,
                "profile_pic_url": str(user_info.profile_pic_url) if user_info.profile_pic_url else None,
                "profile_pic_url_hd": str(user_info.profile_pic_url_hd) if user_info.profile_pic_url_hd else None,
                "external_url": str(user_info.external_url) if getattr(user_info, "external_url", None) else None,
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            user_dir = _user_dir(username)
            user_dir.mkdir(parents=True, exist_ok=True)
            (user_dir / "profile.json").write_text(json.dumps(profile, indent=2, default=str))
            _update_profiles_index(username, profile)
            done += 1
            _emit(on_progress, {"type": "user_done", "idx": idx, "total": total,
                                "username": username, "new_gallery": 0, "new_stories": 0})
        except Exception as e:
            failed += 1
            _emit(on_progress, {"type": "user_error", "idx": idx, "total": total,
                                "username": username, "msg": str(e)})

        if idx < total and not _cancelled(should_cancel):
            _interruptible_sleep(random.uniform(4, 8), should_cancel)

    _emit(on_progress, {"type": "bulk_done", "total": total,
                        "downloaded": done, "skipped": initial_skipped,
                        "failed": failed, "cancelled": False})


def get_user_media(username):
    metadata = _load_metadata(username)
    if not metadata.get("gallery") and not metadata.get("stories"):
        return None

    gallery_by_date = defaultdict(list)
    for m in metadata.get("gallery", []):
        gallery_by_date[m["taken_at"][:10]].append(m)

    stories_by_date = defaultdict(list)
    for m in metadata.get("stories", []):
        stories_by_date[m["taken_at"][:10]].append(m)

    return {
        "username": username,
        "gallery": dict(sorted(gallery_by_date.items(), reverse=True)),
        "stories": dict(sorted(stories_by_date.items(), reverse=True)),
    }

"""
Lógica de Instagram desacoplada para uso desde la API web.
"""
import os
import time
import random
from typing import Callable
from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired,
    ChallengeRequired,
    ChallengeUnknownStep,
    ChallengeError,
    TwoFactorRequired,
)


def autenticar_instagram(
    username: str,
    password: str,
    verification_code: str = None,
    session_file: str = None,
) -> Client:
    """
    Autentica en Instagram y devuelve el Client listo para usar.

    Args:
        username: Nombre de usuario de Instagram
        password: Contraseña de Instagram
        verification_code: Código 2FA (opcional)
        session_file: Ruta al archivo de sesión (opcional)

    Raises:
        TwoFactorRequired: Si la cuenta requiere 2FA y no se proporcionó código
        ChallengeRequired: Si Instagram exige verificación adicional
        LoginRequired: Si las credenciales son inválidas
    """
    cl = Client()
    # Delay aleatorio incorporado entre requests (comportamiento más humano)
    cl.delay_range = [2, 5]

    session = None
    if session_file and os.path.exists(session_file):
        try:
            session = cl.load_settings(session_file)
        except Exception:
            session = None

    sesion_reutilizada = False
    if session:
        try:
            cl.set_settings(session)
            # Validar la sesión con una llamada ligera, sin forzar re-login
            cl.get_timeline_feed()
            sesion_reutilizada = True
        except LoginRequired:
            # Sesión vencida: reusar el mismo device/uuids para no parecer nuevo
            old_uuids = cl.get_settings().get("uuids", {})
            cl.set_settings({})
            if old_uuids:
                cl.set_uuids(old_uuids)
            cl.delay_range = [2, 5]
        except Exception:
            sesion_reutilizada = False

    if not sesion_reutilizada:
        _do_login(cl, username, password, verification_code)

    # En el camino de reuso de sesión se saltea login(), que es quien setea
    # cl.username; lo garantizamos acá para que owner_username nunca sea None.
    if not getattr(cl, "username", None):
        cl.username = username

    if session_file:
        cl.dump_settings(session_file)

    return cl


def _do_login(cl: Client, username: str, password: str, verification_code: str = None):
    try:
        if verification_code:
            cl.login(username, password, verification_code=verification_code)
        else:
            cl.login(username, password)
    except (ChallengeUnknownStep, ChallengeError) as e:
        raise ChallengeRequired(str(e))


def obtener_usuarios(
    cl: Client,
    modo: str = "following",
    on_progress: Callable[[dict], None] = None,
    target_user_id: str = None,
    session=None,
    ttl_days: int = 7,
) -> list[dict]:
    """
    Obtiene todos los usuarios (following o followers) sin filtrar.
    El filtrado se hace en el cliente.

    Llama a on_progress con eventos del tipo:
        {"type": "total",   "total": int}
        {"type": "usuario", "idx": int, "total": int, "usuario": dict, "cached": bool}
        {"type": "error",   "idx": int, "msg": str}
        {"type": "done",    "total": int, "from_cache": int}
    """
    # Import local para que el CLI / usos sin DB no dependan de SQLAlchemy.
    repository = None
    if session is not None:
        import repository as repository

    user_id = target_user_id if target_user_id else cl.user_id
    if modo == "followers":
        usuarios = {u.pk: u for u in cl.user_followers_v1(user_id)}
    else:
        usuarios = cl.user_following(user_id)
    total = len(usuarios)

    _emit(on_progress, {"type": "total", "total": total})

    resultado = []
    from_cache = 0
    seen_pks = set()

    for idx, (uid, _) in enumerate(usuarios.items(), 1):
        pk = int(uid)
        if pk in seen_pks:
            continue
        seen_pks.add(pk)
        try:
            db_user = None
            cached = repository.get_cached_user(session, int(uid), ttl_days) if repository else None

            if cached is not None:
                usuario = repository.user_to_dict(cached)
                # Cache sin foto (registro anterior a la migración): actualizar
                if not usuario.get("profile_pic_url_hd"):
                    try:
                        fresh = cl.user_info_v1(uid)
                        if fresh.profile_pic_url_hd:
                            usuario["profile_pic_url_hd"] = str(fresh.profile_pic_url_hd)
                            usuario["profile_pic_url"] = str(fresh.profile_pic_url)
                            if repository:
                                repository.upsert_user(session, usuario)
                    except Exception:
                        pass
                db_user = cached
                from_cache += 1
                resultado.append(usuario)
                _emit(on_progress, {"type": "usuario", "idx": idx, "total": total,
                                    "usuario": usuario, "cached": True})
            else:
                user_info = cl.user_info_v1(uid)
                usuario = {
                    "pk": int(user_info.pk),
                    "username": user_info.username,
                    "full_name": user_info.full_name,
                    "biography": user_info.biography or "",
                    "follower_count": user_info.follower_count,
                    "following_count": user_info.following_count,
                    "media_count": user_info.media_count,
                    "is_verified": user_info.is_verified,
                    "is_private": user_info.is_private,
                    "profile_pic_url": str(user_info.profile_pic_url),
                    "profile_pic_url_hd": str(user_info.profile_pic_url_hd) if user_info.profile_pic_url_hd else None,
                }
                resultado.append(usuario)
                if repository:
                    db_user = repository.upsert_user(session, usuario)
                _emit(on_progress, {"type": "usuario", "idx": idx, "total": total,
                                    "usuario": usuario, "cached": False})

                # Delays SOLO en miss real (el cache hit no toca la API).
                time.sleep(random.uniform(4, 8))
                if idx % 30 == 0:
                    time.sleep(random.uniform(40, 70))

            if repository:
                session.commit()

        except Exception as e:
            if session is not None:
                session.rollback()
            _emit(on_progress, {"type": "error", "idx": idx, "msg": str(e)})
            time.sleep(random.uniform(15, 30))

    if repository:
        session.commit()

    _emit(on_progress, {"type": "done", "total": len(resultado), "from_cache": from_cache})

    return sorted(resultado, key=lambda x: x["follower_count"], reverse=True)


def _emit(callback: Callable | None, event: dict):
    if callback:
        callback(event)

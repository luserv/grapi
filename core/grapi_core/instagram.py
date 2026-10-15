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
    target_username: str = None,
    session=None,
    metrics_ttl_days: int = 180,
    repository=None,
) -> list[dict]:
    """
    Obtiene todos los usuarios (following o followers) sin filtrar.
    El filtrado se hace en el cliente.

    Dos fuentes, dos costos:
      - El LISTADO (user_following / user_followers_v1) devuelve un `UserShort`
        por usuario con username, full_name, badges y fotos. Es UNA llamada
        total y trae la identidad al día: se usa siempre, gratis.
      - Los CONTADORES (follower/following/media) no vienen en el listado.
        Requerirían un `user_info_v1` por usuario, que es lo caro. Por eso
        viven cacheados con TTL propio (`metrics_ttl_days`) y son lo único que
        puede estar viejo.

    Llama a on_progress con eventos del tipo:
        {"type": "total",   "total": int}
        {"type": "usuario", "idx": int, "total": int, "usuario": dict, "cached": bool}
        {"type": "error",   "idx": int, "msg": str}
        {"type": "done",    "total": int, "from_cache": int, "refreshed": int, "stale": int}
    """
    # Use passed repository, or import from grapi_core if available for testability.
    # Si no se pasa repository explícito y hay sesión, intentamos importarlo.
    if repository is None and session is not None:
        import grapi_core.repository as repository

    user_id = target_user_id if target_user_id else cl.user_id
    if modo == "followers":
        usuarios = {u.pk: u for u in cl.user_followers_v1(user_id)}
    else:
        usuarios = cl.user_following(user_id)
    total = len(usuarios)

    _emit(on_progress, {"type": "total", "total": total})

    # Una corrida por análisis para el historial. Sin owner no se puede atribuir
    # la corrida a ninguna cuenta, así que se omite en vez de escribir basura.
    run_id = None
    if repository is not None and cl.username:
        run = repository.create_run(
            session,
            owner_username=cl.username,
            modo=modo,
            target_username=target_username,
            target_user_id=str(user_id),
        )
        run_id = run.id
        session.commit()

    resultado = []
    from_cache = 0
    refreshed = 0
    stale = 0
    seen_pks = set()

    for idx, (uid, short) in enumerate(usuarios.items(), 1):
        pk = int(uid)
        if pk in seen_pks:
            continue
        seen_pks.add(pk)
        try:
            cached = repository.get_cached_user(session, pk) if repository else None

            # Identidad: el listado es la fuente y siempre está al día.
            identidad = _identity_from_short(pk, short)

            if cached is not None and repository.metrics_are_fresh(cached, metrics_ttl_days):
                # HIT TOTAL: cero requests. El listado ya se descargó igual, así
                # que su identidad se aplica gratis y la fila no puede quedar
                # vieja en nombre, foto ni badges. Solo los contadores salen de
                # la cache — que es justo lo que el TTL gobierna.
                usuario = repository.user_to_dict(cached)
                usuario.update(identidad)
                from_cache += 1
                resultado.append(usuario)
                _emit(on_progress, {"type": "usuario", "idx": idx, "total": total,
                                    "usuario": usuario, "cached": True})
            else:
                # Hay que traer contadores. Se intenta el request caro; si
                # falla, si había cache se sirve con los números viejos en vez
                # de perder al usuario de la tabla.
                usuario = (
                    repository.user_to_dict(cached) if cached is not None
                    else {**identidad, "biography": "",
                          "follower_count": 0, "following_count": 0, "media_count": 0}
                )
                # El listado manda en identidad: está más fresco que la fila.
                usuario.update(identidad)
                if cached is not None:
                    usuario["biography"] = cached.biography or ""

                try:
                    user_info = cl.user_info_v1(uid)
                    usuario.update({
                        "username": user_info.username,
                        "full_name": user_info.full_name,
                        "biography": user_info.biography or "",
                        "follower_count": user_info.follower_count,
                        "following_count": user_info.following_count,
                        "media_count": user_info.media_count,
                        "is_verified": user_info.is_verified,
                        "is_private": user_info.is_private,
                        "profile_pic_url": str(user_info.profile_pic_url),
                        "profile_pic_url_hd": (
                            str(user_info.profile_pic_url_hd) if user_info.profile_pic_url_hd else None
                        ),
                    })
                    if repository:
                        repository.upsert_user(
                            session, {**usuario, "metrics_fresh": True}
                        )
                    refreshed += 1
                except Exception as e:
                    if cached is None:
                        raise  # sin cache no hay nada que servir → error normal
                    _emit(on_progress, {
                        "type": "error", "idx": idx,
                        "msg": f"{e} · servidos los contadores cacheados",
                    })
                    if repository:
                        repository.upsert_user(
                            session, {**usuario, "metrics_fresh": False}
                        )
                    stale += 1

                resultado.append(usuario)
                _emit(on_progress, {"type": "usuario", "idx": idx, "total": total,
                                    "usuario": usuario, "cached": False})

                # Delays SOLO cuando hubo request real (el hit total no toca la API).
                time.sleep(random.uniform(4, 8))
                if idx % 30 == 0:
                    time.sleep(random.uniform(40, 70))

            if repository and run_id is not None:
                # Se pasa `usuario` (el dict de esta corrida), no el objeto ORM:
                # tras un refresco de contadores el identity map sigue teniendo
                # los valores viejos y el snapshot congelaría el número viejo.
                repository.add_member(session, run_id, usuario, position=idx)

            if repository:
                session.commit()

        except Exception as e:
            if session is not None:
                session.rollback()
            _emit(on_progress, {"type": "error", "idx": idx, "msg": str(e)})
            time.sleep(random.uniform(15, 30))

    if repository:
        if run_id is not None:
            repository.finalize_run(session, run_id, total=len(resultado), from_cache=from_cache)
        session.commit()

    _emit(on_progress, {"type": "done", "total": len(resultado), "from_cache": from_cache,
                        "refreshed": refreshed, "stale": stale})

    return sorted(resultado, key=lambda x: x["follower_count"], reverse=True)


def _identity_from_short(pk: int, short) -> dict:
    """Identidad que ya venía en el listado: sin costo de API.

    Es lo que hace que la fila cacheada no pueda quedar vieja en nombre, foto
    ni badges: eso se relee del listado en cada análisis.
    """
    if short is None:
        return {}
    return {
        "pk": pk,
        "username": short.username,
        "full_name": short.full_name,
        "is_verified": bool(short.is_verified),
        "is_private": bool(short.is_private),
        "profile_pic_url": str(short.profile_pic_url) if short.profile_pic_url else None,
        "profile_pic_url_hd": (
            str(short.profile_pic_url_hd) if short.profile_pic_url_hd else None
        ),
    }


def _emit(callback: Callable | None, event: dict):
    if callback:
        callback(event)

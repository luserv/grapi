"""
Acceso a datos: caché de perfiles + historial de corridas.
Toda la lógica SQL vive acá para mantener instagram.py / main.py limpios.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, delete, func as sql_func, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from models import AnalysisRun, InstagramUser, RunMember


# ── Caché de perfiles ────────────────────────────────────────────────

def get_cached_user(session: Session, pk: int, ttl_days: int) -> InstagramUser | None:
    """Devuelve el perfil cacheado si existe y es más nuevo que ttl_days; si no, None."""
    user = session.get(InstagramUser, pk)
    if user is None:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    if user.last_fetched_at and user.last_fetched_at >= cutoff:
        return user
    return None  # existe pero está vencido → re-consultar


def upsert_user(session: Session, data: dict) -> InstagramUser:
    """Inserta o actualiza un perfil y marca last_fetched_at = ahora."""
    now = datetime.now(timezone.utc)
    user = session.get(InstagramUser, data["pk"])
    if user is None:
        user = InstagramUser(pk=data["pk"], first_seen_at=now)
        session.add(user)
    user.username = data["username"]
    user.full_name = data.get("full_name")
    user.biography = data.get("biography") or ""
    user.follower_count = data["follower_count"]
    user.following_count = data["following_count"]
    user.media_count = data["media_count"]
    user.is_verified = data["is_verified"]
    user.is_private = data["is_private"]
    user.profile_pic_url = data.get("profile_pic_url")
    user.profile_pic_url_hd = data.get("profile_pic_url_hd")
    user.last_fetched_at = now
    session.flush()
    return user


def user_to_dict(user: InstagramUser) -> dict:
    """Forma el dict que consume el frontend desde una fila cacheada."""
    return {
        "pk": user.pk,
        "username": user.username,
        "full_name": user.full_name,
        "biography": user.biography or "",
        "follower_count": user.follower_count,
        "following_count": user.following_count,
        "media_count": user.media_count,
        "is_verified": user.is_verified,
        "is_private": user.is_private,
        "profile_pic_url": user.profile_pic_url,
        "profile_pic_url_hd": user.profile_pic_url_hd,
    }


def search_users(
    session: Session,
    q: str = "",
    limit: int = 20,
    owner_username: str | None = None,
) -> list[InstagramUser]:
    """Busca usuarios cacheados por username o full_name.

    Si se pasa owner_username, devuelve solo los usuarios que aparecieron en
    alguna corrida de ese dueño (join InstagramUser → RunMember → AnalysisRun).
    """
    stmt = select(InstagramUser).distinct()
    if owner_username:
        stmt = (
            stmt
            .join(RunMember, RunMember.user_pk == InstagramUser.pk)
            .join(AnalysisRun, AnalysisRun.id == RunMember.run_id)
            .where(AnalysisRun.owner_username == owner_username)
        )
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(or_(
            sql_func.lower(InstagramUser.username).like(pattern),
            sql_func.lower(InstagramUser.full_name).like(pattern),
        ))
    stmt = stmt.order_by(InstagramUser.follower_count.desc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


# ── Historial de corridas ────────────────────────────────────────────

def create_run(
    session: Session,
    owner_username: str,
    modo: str,
    target_username: str | None,
    target_user_id: str | None,
) -> AnalysisRun:
    """Crea una corrida nueva. Si ya existe una para el mismo owner+modo+target,
    la reusa (no duplica registros)."""
    existing = _find_existing_run(session, owner_username, modo, target_username)
    if existing is not None:
        existing.target_user_id = target_user_id
        existing.created_at = datetime.now(timezone.utc)
        session.flush()
        return existing
    run = AnalysisRun(
        owner_username=owner_username,
        modo=modo,
        target_username=target_username,
        target_user_id=target_user_id,
    )
    session.add(run)
    session.flush()
    return run


def _find_existing_run(
    session: Session,
    owner_username: str,
    modo: str,
    target_username: str | None,
) -> AnalysisRun | None:
    stmt = (
        select(AnalysisRun)
        .where(AnalysisRun.owner_username == owner_username)
        .where(AnalysisRun.modo == modo)
        .where(AnalysisRun.target_username == target_username)
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def reset_run_members(session: Session, run_id: int) -> None:
    """Elimina todos los miembros de una corrida (para reemplazarlos)."""
    session.execute(
        delete(RunMember).where(RunMember.run_id == run_id)
    )
    session.flush()


def add_member(session: Session, run_id: int, user: InstagramUser, position: int) -> None:
    """Inserta el miembro en la corrida de forma idempotente.

    Si la misma (run_id, user_pk) ya existe —p. ej. porque el EventSource del
    front se reconectó y hay dos run_fetch escribiendo el mismo run a la vez—
    se actualiza la fila en lugar de violar uq_run_user. Usa el upsert nativo
    de Postgres (ON CONFLICT DO UPDATE)."""
    stmt = pg_insert(RunMember).values(
        run_id=run_id,
        user_pk=user.pk,
        position=position,
        follower_count=user.follower_count,
        following_count=user.following_count,
        media_count=user.media_count,
    ).on_conflict_do_update(
        constraint="uq_run_user",
        set_=dict(
            position=position,
            follower_count=user.follower_count,
            following_count=user.following_count,
            media_count=user.media_count,
        ),
    )
    session.execute(stmt)


def finalize_run(session: Session, run_id: int, total: int, from_cache: int) -> None:
    session.execute(
        update(AnalysisRun)
        .where(AnalysisRun.id == run_id)
        .values(total=total, from_cache=from_cache)
    )


def list_runs(session: Session, owner_username: str | None = None, limit: int = 50) -> list[AnalysisRun]:
    stmt = select(AnalysisRun).order_by(AnalysisRun.created_at.desc()).limit(limit)
    if owner_username:
        stmt = stmt.where(AnalysisRun.owner_username == owner_username)
    return list(session.scalars(stmt).all())


def get_run(session: Session, run_id: int) -> AnalysisRun | None:
    stmt = (
        select(AnalysisRun)
        .where(AnalysisRun.id == run_id)
        .options(selectinload(AnalysisRun.members).selectinload(RunMember.user))
    )
    return session.scalars(stmt).first()


def _run_usernames(session: Session, run_id: int) -> dict[str, RunMember]:
    stmt = (
        select(RunMember)
        .where(RunMember.run_id == run_id)
        .options(selectinload(RunMember.user))
    )
    return {m.user.username: m for m in session.scalars(stmt).all()}


class IncompatibleRuns(ValueError):
    """Las dos corridas no comparten modo + target, así que el diff no tiene sentido."""


def diff_runs(session: Session, base_id: int, compare_id: int) -> dict:
    """
    Compara dos corridas. 'base' = más vieja, 'compare' = más nueva.
    - gained: usernames presentes en compare y ausentes en base (nuevos).
    - lost:   usernames presentes en base y ausentes en compare (se fueron).

    Exige que ambas corridas compartan `modo` y `target_username`; si no,
    levanta IncompatibleRuns (comparar followers vs following no significaría nada).
    """
    base_run = session.get(AnalysisRun, base_id)
    compare_run = session.get(AnalysisRun, compare_id)
    if base_run is None or compare_run is None:
        raise ValueError("run_not_found")
    if (base_run.modo != compare_run.modo
            or base_run.target_username != compare_run.target_username):
        raise IncompatibleRuns(
            "Solo se pueden comparar corridas del mismo tipo y objetivo."
        )

    base = _run_usernames(session, base_id)
    compare = _run_usernames(session, compare_id)
    base_set, compare_set = set(base), set(compare)
    gained = sorted(compare_set - base_set)
    lost = sorted(base_set - compare_set)
    return {
        "base_id": base_id,
        "compare_id": compare_id,
        "gained": gained,
        "lost": lost,
        "gained_count": len(gained),
        "lost_count": len(lost),
    }

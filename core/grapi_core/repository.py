"""
Acceso a datos: caché de perfiles + historial de corridas.
Toda la lógica SQL vive acá para mantener instagram.py / main.py limpios.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, func as sql_func, or_
from sqlalchemy import insert
from sqlalchemy.orm import Session, selectinload

from grapi_core.models import AnalysisRun, InstagramUser, RunMember


# ── Caché de perfiles ────────────────────────────────────────────────

def get_cached_user(session: Session, pk: int) -> InstagramUser | None:
    """El perfil cacheado de `pk`, o None si nunca lo vimos.

    La fila NO tiene vencimiento: mientras exista, la identidad (username,
    full_name, badges) es conocida. Solo los contadores se vencen, y eso lo
    decide `metrics_are_fresh`.
    """
    return session.get(InstagramUser, pk)


def metrics_are_fresh(user: InstagramUser, ttl_days: int) -> bool:
    """¿Los contadores de `user` son más nuevos que ttl_days?

    ttl_days <= 0 fuerza el refresco (modo explícito "dame números frescos").
    """
    if ttl_days <= 0:
        return False
    if user.metrics_fetched_at is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    return user.metrics_fetched_at >= cutoff


def upsert_user(session: Session, data: dict) -> InstagramUser:
    """Inserta o actualiza un perfil y marca las dos fechas a ahora.

    `data["metrics_fresh"]` decide si además se renueva `metrics_fetched_at`.
    Va en False para actualizaciones de identidad que no trajeron contadores
    frescos del listado, para no mentirle al TTL.

    Usa INSERT … ON CONFLICT DO UPDATE (PostgreSQL) para evitar race
    conditions cuando dos hilos intentan insertar el mismo pk.
    """
    now = datetime.now(timezone.utc)
    metrics_fresh = bool(data.get("metrics_fresh", True))
    table = InstagramUser.__table__

    update_set = {
        "username": data["username"],
        "full_name": data.get("full_name"),
        "biography": data.get("biography") or "",
        "follower_count": data["follower_count"],
        "following_count": data["following_count"],
        "media_count": data["media_count"],
        "is_verified": data["is_verified"],
        "is_private": data["is_private"],
        "profile_pic_url": data.get("profile_pic_url"),
        "profile_pic_url_hd": data.get("profile_pic_url_hd"),
        "last_fetched_at": now,
    }
    if metrics_fresh:
        update_set["metrics_fetched_at"] = now

    stmt = (
        pg_insert(table)
        .values(
            pk=data["pk"],
            username=data["username"],
            full_name=data.get("full_name"),
            biography=data.get("biography") or "",
            follower_count=data["follower_count"],
            following_count=data["following_count"],
            media_count=data["media_count"],
            is_verified=data["is_verified"],
            is_private=data["is_private"],
            profile_pic_url=data.get("profile_pic_url"),
            profile_pic_url_hd=data.get("profile_pic_url_hd"),
            first_seen_at=now,
            last_fetched_at=now,
            metrics_fetched_at=now if metrics_fresh else None,
        )
        .on_conflict_do_update(
            index_elements=[table.c.pk],
            set_=update_set,
        )
    )
    session.execute(stmt)
    session.flush()

    user = session.get(InstagramUser, data["pk"])
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
    """Crea una corrida nueva. Siempre una, nunca reusa.

    No se busca una previa del mismo (owner, modo, target): `diff_runs` exige
    que las dos corridas a comparar compartan modo + target_username, así que
    reusar haría imposible tener un par comparable y el historial nunca
    podría mostrar un diff. Acumulá corridas y compará las que quieras.
    """
    run = AnalysisRun(
        owner_username=owner_username,
        modo=modo,
        target_username=target_username,
        target_user_id=target_user_id,
    )
    session.add(run)
    session.flush()
    return run


def add_member(session: Session, run_id: int, data: dict, position: int) -> None:
    """Inserta el miembro en la corrida, congelando el perfil de `data`.

    Toma el **dict**, no el objeto `InstagramUser`, a propósito. `upsert_user`
    escribe con `INSERT ... ON CONFLICT DO UPDATE`, que es SQL crudo: el
    identity map del ORM no se entera y `session.get()` devuelve el objeto con
    los atributos de ANTES del refresco. Como `add_member` se llama justo
    después de un refresco de contadores, leer del ORM congelaría el valor
    viejo en el historial — la misma mentira que acabamos de eliminar de
    `RunMember`, entering por otra puerta. El dict es lo que esta corrida vio.

    Idempotente: si la misma (run_id, user_pk) ya existe se actualiza en vez de
    violar `uq_run_user`, así que reintentar un usuario nunca rompe la corrida.
    """
    stmt = pg_insert(RunMember).values(
        run_id=run_id,
        user_pk=data["pk"],
        position=position,
        username=data["username"],
        full_name=data.get("full_name"),
        is_verified=bool(data.get("is_verified")),
        is_private=bool(data.get("is_private")),
        follower_count=data["follower_count"],
        following_count=data["following_count"],
        media_count=data["media_count"],
    ).on_conflict_do_update(
        constraint="uq_run_user",
        set_=dict(
            position=position,
            username=data["username"],
            full_name=data.get("full_name"),
            is_verified=bool(data.get("is_verified")),
            is_private=bool(data.get("is_private")),
            follower_count=data["follower_count"],
            following_count=data["following_count"],
            media_count=data["media_count"],
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
        .options(selectinload(AnalysisRun.members))
    )
    return session.scalars(stmt).first()


def run_owner(session: Session, run_id: int) -> str | None:
    """Dueño de la corrida, o None si no existe. Los endpoints de historial
    lo usan para no exponer corridas de otra cuenta."""
    run = session.get(AnalysisRun, run_id)
    return run.owner_username if run else None


def run_to_dict(run: AnalysisRun) -> dict:
    """Forma el dict que consume el frontend desde una fila de analysis_runs."""
    return {
        "id": run.id,
        "modo": run.modo,
        "target_username": run.target_username,
        "total": run.total,
        "from_cache": run.from_cache,
        "created_at": run.created_at,
    }


def member_to_dict(member: RunMember) -> dict:
    """Snapshot del miembro de una corrida.

    Todo sale de `run_members`: identidad, badges y conteos congelados en el
    momento del análisis. Nada se lee de `instagram_users` — mostrar el valor
    actual haría inútil la comparación entre corridas.
    """
    return {
        "username": member.username,
        "full_name": member.full_name,
        "follower_count": member.follower_count,
        "following_count": member.following_count,
        "media_count": member.media_count,
        "is_verified": member.is_verified,
        "is_private": member.is_private,
    }


def _run_usernames(session: Session, run_id: int) -> dict[str, RunMember]:
    stmt = select(RunMember).where(RunMember.run_id == run_id)
    return {m.username: m for m in session.scalars(stmt).all()}


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

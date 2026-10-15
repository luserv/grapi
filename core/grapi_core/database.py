"""
Engine y fábrica de sesiones de SQLAlchemy (sync, driver psycopg3).

Sync a propósito: el fetch de instagrapi es bloqueante y corre en un
ThreadPoolExecutor; una Session sync encaja sin puentes hilo↔event-loop.
FastAPI corre los endpoints `def` en su propio threadpool, así que tampoco
bloquea el loop asíncrono.
"""
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from grapi_core.config import settings

_url = make_url(settings.DATABASE_URL)
_is_sqlite = _url.get_backend_name() == "sqlite"

if _is_sqlite:
    # The sqlite file may live in a directory that does not exist yet
    # (e.g. a fresh bind mount); create it so the first connect succeeds.
    if _url.database and _url.database != ":memory:":
        Path(_url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
    # Sessions are used from the FastAPI threadpool and the fetch executor,
    # so sqlite must allow cross-thread use of a connection.
    engine = create_engine(
        _url,
        echo=settings.ECHO_SQL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        _url,
        echo=settings.ECHO_SQL,
        pool_pre_ping=True,   # revive conexiones muertas tras inactividad
        pool_size=5,
        max_overflow=10,
    )

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope() -> Session:
    """Sesión transaccional: commit al salir, rollback ante error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create any missing tables (idempotent; leaves existing schemas alone).

    Replaces the removed Alembic migrations for fresh SQLite databases. It
    does not alter tables that already exist.
    """
    from grapi_core.models import Base

    Base.metadata.create_all(bind=engine)

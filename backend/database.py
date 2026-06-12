"""
Engine y fábrica de sesiones de SQLAlchemy (sync, driver psycopg3).

Sync a propósito: el fetch de instagrapi es bloqueante y corre en un
ThreadPoolExecutor; una Session sync encaja sin puentes hilo↔event-loop.
FastAPI corre los endpoints `def` en su propio threadpool, así que tampoco
bloquea el loop asíncrono.
"""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings

engine = create_engine(
    settings.DATABASE_URL,
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


def get_session():
    """Dependencia de FastAPI: una sesión por request."""
    with session_scope() as session:
        yield session

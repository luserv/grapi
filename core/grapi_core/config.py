"""
Configuración central. Lee variables de entorno (y un .env si existe).
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Carga el .env de la raíz del proyecto si está presente
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass


class Settings:
    # Conexión a Postgres. Driver psycopg3 (sync).
    # En Docker, el host es "db" (nombre del servicio de docker-compose).
    # Fuera de Docker el default apunta a `localhost:11`, que es el puerto que
    # publica el propio docker-compose.yml — no al 5432 habitual, que acá no
    # existe. Sobrecribir con DATABASE_URL si tu Postgres vive en otro lado.
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://iguser:igpass@localhost:11/igdb",
    )

    # Días que un perfil cacheado aguanta con sus contadores frescos.
    # SOLO aplica a los contadores (follower/following/media): la identidad
    # (username, full_name, badges, fotos) se relee del listado de
    # following/followers en cada análisis, así que nunca queda vieja.
    # Subilo = menos requests pero números más viejos. Bajalo = números al día
    # a costa de un request por usuario.
    METRICS_TTL_DAYS: int = int(os.getenv("METRICS_TTL_DAYS", "180"))

    # En la descarga masiva de galerías, cada cuántas horas se vuelve a bajar
    # un usuario ya descargado. Default 24h porque las historias caducan a
    # diario: re-correr al otro día captura las historias nuevas.
    GALLERY_TTL_HOURS: int = int(os.getenv("GALLERY_TTL_HOURS", "24"))

    # Loguea cada sentencia SQL (debug).
    ECHO_SQL: bool = os.getenv("ECHO_SQL", "0") == "1"

    # Directorio donde se guardan galerías/historias descargadas.
    # En Docker apuntalo a un volumen montado para que persista y lo veas
    # desde el host. Default: backend/downloads (comportamiento previo).
    DOWNLOADS_DIR: str = os.getenv(
        "DOWNLOADS_DIR",
        str(Path(__file__).resolve().parent / "downloads"),
    )

    # Directorio de los archivos de sesión de Instagram (session_<user>.json).
    # Persistilo en Docker para no re-loguear (y reducir challenges) en cada
    # arranque del contenedor. Default: backend/ (comportamiento previo).
    SESSIONS_DIR: str = os.getenv(
        "SESSIONS_DIR",
        str(Path(__file__).resolve().parent),
    )


settings = Settings()

# Garantizar que los directorios persistentes existan al arrancar.
Path(settings.DOWNLOADS_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.SESSIONS_DIR).mkdir(parents=True, exist_ok=True)

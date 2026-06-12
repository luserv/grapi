"""
Modelos SQLAlchemy 2.0.

Tres tablas:
- instagram_users  → caché de perfiles (evita re-consultar la API).
- analysis_runs    → cada corrida de análisis (un snapshot con fecha).
- run_members      → qué usuarios aparecieron en cada corrida, con sus
                     conteos AL MOMENTO de la corrida (para diffs históricos).
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class InstagramUser(Base):
    """Caché del perfil de un usuario de Instagram (la última versión vista)."""
    __tablename__ = "instagram_users"

    pk: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(150), index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    biography: Mapped[str] = mapped_column(Text, default="")

    follower_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    media_count: Mapped[int] = mapped_column(Integer, default=0)

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)

    profile_pic_url: Mapped[str | None] = mapped_column(Text, default=None)
    profile_pic_url_hd: Mapped[str | None] = mapped_column(Text, default=None)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    memberships: Mapped[list["RunMember"]] = relationship(back_populates="user")


class AnalysisRun(Base):
    """Una corrida: 'a las X analicé los followers de @Y, encontré N'."""
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_username: Mapped[str] = mapped_column(String(150), index=True)
    modo: Mapped[str] = mapped_column(String(20))  # "following" | "followers"
    target_username: Mapped[str | None] = mapped_column(String(150))
    target_user_id: Mapped[str | None] = mapped_column(String(50))

    total: Mapped[int] = mapped_column(Integer, default=0)
    from_cache: Mapped[int] = mapped_column(Integer, default=0)  # cuántos salieron de caché

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    members: Mapped[list["RunMember"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RunMember(Base):
    """Vínculo corrida↔usuario, con snapshot de conteos al momento."""
    __tablename__ = "run_members"
    __table_args__ = (UniqueConstraint("run_id", "user_pk", name="uq_run_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    user_pk: Mapped[int] = mapped_column(
        ForeignKey("instagram_users.pk", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)  # orden dentro de la corrida

    # Snapshot: los conteos pueden cambiar entre corridas; esto los congela.
    follower_count: Mapped[int] = mapped_column(Integer)
    following_count: Mapped[int] = mapped_column(Integer)
    media_count: Mapped[int] = mapped_column(Integer)

    run: Mapped["AnalysisRun"] = relationship(back_populates="members")
    user: Mapped["InstagramUser"] = relationship(back_populates="memberships")

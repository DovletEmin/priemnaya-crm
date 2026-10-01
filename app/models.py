from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source:
    BOT = "bot"
    BUSINESS = "business"
    MANUAL = "manual"

    LABELS = {BOT: "Telegram-бот", BUSINESS: "Личный Telegram", MANUAL: "Вручную"}


class Status:
    NEW = "new"
    IN_PROGRESS = "in_progress"
    WON = "won"
    LOST = "lost"

    ORDER = [NEW, IN_PROGRESS, WON, LOST]
    LABELS = {NEW: "Новый", IN_PROGRESS: "В работе", WON: "Успешно", LOST: "Отказ"}
    OPEN = [NEW, IN_PROGRESS]


lead_tags = Table(
    "lead_tags",
    Base.metadata,
    Column("lead_id", ForeignKey("leads.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    contact: Mapped[str] = mapped_column(String(200), default="")
    request: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default=Source.MANUAL, index=True)
    status: Mapped[str] = mapped_column(String(20), default=Status.NEW, index=True)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    tg_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    tags: Mapped[list["Tag"]] = relationship(secondary=lead_tags, back_populates="leads", order_by="Tag.name")
    notes: Mapped[list["Note"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="Note.created_at"
    )

    @property
    def source_label(self) -> str:
        return Source.LABELS.get(self.source, self.source)

    @property
    def status_label(self) -> str:
        return Status.LABELS.get(self.status, self.status)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    color: Mapped[str] = mapped_column(String(7), default="#6B7180")

    leads: Mapped[list[Lead]] = relationship(secondary=lead_tags, back_populates="tags")


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    # manager — заметка менеджера, client — сообщение клиента, system — событие (смена статуса и т.п.)
    kind: Mapped[str] = mapped_column(String(20), default="manager")
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lead: Mapped[Lead] = relationship(back_populates="notes")


class BotSession(Base):
    """Шаг диалога с ботом. Храним в БД, потому что на serverless память между запросами не живёт."""

    __tablename__ = "bot_sessions"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    step: Mapped[str] = mapped_column(String(30), default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Manager(Base):
    """Чаты, куда бот присылает уведомления о новых лидах."""

    __tablename__ = "managers"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BusinessConnection(Base):
    """Подключение личного аккаунта через Telegram Business (пункт 2)."""

    __tablename__ = "business_connections"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger)
    owner_name: Mapped[str] = mapped_column(String(200), default="")
    is_enabled: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProcessedUpdate(Base):
    """Telegram повторяет доставку, если не получил 200 вовремя. Запоминаем update_id, чтобы не плодить дубли."""

    __tablename__ = "processed_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

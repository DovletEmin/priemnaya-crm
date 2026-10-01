"""Бизнес-логика лидов: общая для CRM, бота и Telegram Business."""

import html
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bot import telegram
from app.config import PUBLIC_URL
from app.models import Lead, Manager, Note, Source, Status, Tag

log = logging.getLogger(__name__)

TAG_COLORS = ["#229ED9", "#7C5CFF", "#E5484D", "#F59E0B", "#12A594", "#E54D9E", "#6B7180", "#3E63DD"]

DEFAULT_TAGS = [
    ("горячий", "#E5484D"),
    ("сайт", "#229ED9"),
    ("реклама", "#F59E0B"),
    ("SMM", "#7C5CFF"),
    ("повторный", "#12A594"),
]


def seed_tags(db: Session) -> None:
    if db.scalar(select(func.count(Tag.id))) == 0:
        db.add_all(Tag(name=n, color=c) for n, c in DEFAULT_TAGS)
        db.commit()


def create_lead(
    db: Session,
    *,
    name: str,
    contact: str = "",
    request: str = "",
    source: str = Source.MANUAL,
    tg_user_id: int | None = None,
    tg_username: str | None = None,
    tags: list[Tag] | None = None,
) -> Lead:
    lead = Lead(
        name=name.strip(),
        contact=contact.strip(),
        request=request.strip(),
        source=source,
        status=Status.NEW,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        tags=tags or [],
    )
    lead.notes.append(Note(kind="system", text=f"Лид создан · {Source.LABELS[source]}"))
    db.add(lead)
    db.commit()
    return lead


def get_or_create_tag(db: Session, name: str) -> Tag | None:
    name = " ".join(name.split())[:50]
    if not name:
        return None
    tag = db.scalar(select(Tag).where(func.lower(Tag.name) == name.lower()))
    if tag:
        return tag
    count = db.scalar(select(func.count(Tag.id))) or 0
    tag = Tag(name=name, color=TAG_COLORS[count % len(TAG_COLORS)])
    db.add(tag)
    db.flush()
    return tag


def lead_url(lead: Lead) -> str:
    return f"{PUBLIC_URL}/leads/{lead.id}" if PUBLIC_URL else ""


def notify_managers(db: Session, lead: Lead) -> None:
    """Шлём уведомление всем менеджерам, подписанным через /manager <код>."""
    managers = db.scalars(select(Manager)).all()
    if not managers:
        return
    e = html.escape
    lines = [
        f"🆕 <b>Новый лид #{lead.id}</b> · {e(lead.source_label)}",
        "",
        f"<b>Имя:</b> {e(lead.name)}",
        f"<b>Контакт:</b> {e(lead.contact or '—')}",
        f"<b>Запрос:</b> {e(lead.request or '—')}",
    ]
    if url := lead_url(lead):
        lines += ["", f'<a href="{url}">Открыть в CRM →</a>']
    for m in managers:
        telegram.send(m.chat_id, "\n".join(lines))

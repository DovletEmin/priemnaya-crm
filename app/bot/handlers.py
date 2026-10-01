"""Обработка апдейтов Telegram.

Один вход — handle_update(). Его вызывает и webhook (прод, Vercel), и scripts/poll.py (локальная разработка).

Сценарий заявки — конечный автомат: name → contact → request → confirm.
Текущий шаг хранится в таблице bot_sessions, поэтому диалог переживает холодные старты serverless.
"""

import html
import logging
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bot import telegram as tg
from app.config import MANAGER_CODE
from app.models import BotSession, BusinessConnection, Lead, Manager, Note, ProcessedUpdate, Source, Status
from app.services import create_lead, notify_managers

log = logging.getLogger(__name__)

BTN_TG_NAME = "👤 Взять имя из Telegram"
BTN_SHARE_PHONE = "📱 Поделиться номером"
BTN_WRITE_TG = "💬 Пишите мне в Telegram"

PHONE_RE = re.compile(r"^\+?[\d\s\-()]{7,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^(@|https?://t\.me/|t\.me/)[A-Za-z0-9_]{4,32}$")


# ---------------------------------------------------------------- entry point


def handle_update(db: Session, update: dict) -> None:
    if not _mark_processed(db, update.get("update_id")):
        return
    if msg := update.get("message"):
        _on_message(db, msg)
    elif cq := update.get("callback_query"):
        _on_callback(db, cq)
    elif bc := update.get("business_connection"):
        _on_business_connection(db, bc)
    elif bm := update.get("business_message"):
        _on_business_message(db, bm)


def _mark_processed(db: Session, update_id: int | None) -> bool:
    """False, если этот апдейт уже обработан (Telegram повторил доставку)."""
    if update_id is None:
        return True
    db.add(ProcessedUpdate(update_id=update_id))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


# ---------------------------------------------------------------- session helpers


def _session(db: Session, chat_id: int) -> BotSession:
    s = db.get(BotSession, chat_id)
    if s is None:
        s = BotSession(chat_id=chat_id, step="", data={})
        db.add(s)
    return s


def _set(db: Session, s: BotSession, step: str, **data) -> None:
    s.step = step
    # JSON-поле: присваиваем новый dict, чтобы SQLAlchemy заметил изменение
    s.data = {**(s.data or {}), **data} if step else {}
    db.commit()


def _full_name(user: dict) -> str:
    return " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p).strip()


# ---------------------------------------------------------------- bot dialog (пункт 1)


def _on_message(db: Session, msg: dict) -> None:
    chat = msg["chat"]
    if chat.get("type") != "private":
        return
    chat_id = chat["id"]
    user = msg.get("from", {})
    text = (msg.get("text") or "").strip()

    if text.startswith("/"):
        _on_command(db, chat_id, user, text)
        return

    s = _session(db, chat_id)
    if s.step == "name":
        _step_name(db, s, user, text)
    elif s.step == "contact":
        _step_contact(db, s, user, msg, text)
    elif s.step == "request":
        _step_request(db, s, text)
    elif s.step == "confirm":
        tg.send(chat_id, "Проверьте заявку выше и нажмите «Отправить» или «Заполнить заново».")
    else:
        _start(db, s, user)


def _on_command(db: Session, chat_id: int, user: dict, text: str) -> None:
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    s = _session(db, chat_id)

    if cmd == "/start":
        _start(db, s, user)
    elif cmd == "/cancel":
        _set(db, s, "")
        tg.send(chat_id, "Заявка отменена. Чтобы начать заново, нажмите /start", tg.REMOVE_KEYBOARD)
    elif cmd == "/manager":
        _manager(db, chat_id, user, arg.strip())
    else:
        tg.send(
            chat_id,
            "Я принимаю заявки для агентства.\n\n/start — оставить заявку\n/cancel — отменить заполнение",
        )


def _start(db: Session, s: BotSession, user: dict) -> None:
    s.data = {}
    _set(db, s, "name")
    keyboard = tg.reply_keyboard([[BTN_TG_NAME]]) if _full_name(user) else tg.REMOVE_KEYBOARD
    tg.send(
        s.chat_id,
        "Здравствуйте! Я помогу оставить заявку — это займёт меньше минуты.\n\n"
        "<b>Шаг 1 из 3.</b> Как к вам обращаться?",
        keyboard,
    )


def _step_name(db: Session, s: BotSession, user: dict, text: str) -> None:
    name = _full_name(user) if text == BTN_TG_NAME else text
    if not 2 <= len(name) <= 100:
        tg.send(s.chat_id, "Напишите, пожалуйста, имя текстом — от 2 до 100 символов.")
        return
    _set(db, s, "contact", name=name)

    first_row = [{"text": BTN_SHARE_PHONE, "request_contact": True}]
    if user.get("username"):
        first_row.append(BTN_WRITE_TG)
    tg.send(
        s.chat_id,
        f"Приятно познакомиться, {html.escape(name)}!\n\n"
        "<b>Шаг 2 из 3.</b> Как с вами связаться? Нажмите кнопку или напишите телефон, email или @username.",
        tg.reply_keyboard([first_row]),
    )


def _step_contact(db: Session, s: BotSession, user: dict, msg: dict, text: str) -> None:
    if c := msg.get("contact"):
        phone = c["phone_number"]
        contact = phone if phone.startswith("+") else "+" + phone
    elif text == BTN_WRITE_TG and user.get("username"):
        contact = "@" + user["username"]
    elif PHONE_RE.match(text) and sum(ch.isdigit() for ch in text) >= 7:
        contact = text
    elif EMAIL_RE.match(text) or USERNAME_RE.match(text):
        contact = text
    else:
        tg.send(
            s.chat_id,
            "Не похоже на контакт. Пришлите телефон (+7 900 123-45-67), email или @username — "
            "или нажмите кнопку ниже.",
        )
        return
    _set(db, s, "request", contact=contact)
    tg.send(
        s.chat_id,
        "<b>Шаг 3 из 3.</b> Опишите задачу: что нужно сделать, сроки, бюджет — всё, что считаете важным.",
        tg.REMOVE_KEYBOARD,
    )


def _step_request(db: Session, s: BotSession, text: str) -> None:
    if len(text) < 3:
        tg.send(s.chat_id, "Опишите запрос текстом — хотя бы пару слов.")
        return
    _set(db, s, "confirm", request=text[:4000])
    d, e = s.data, html.escape
    tg.send(
        s.chat_id,
        "Проверьте заявку:\n\n"
        f"<b>Имя:</b> {e(d['name'])}\n"
        f"<b>Контакт:</b> {e(d['contact'])}\n"
        f"<b>Запрос:</b> {e(d['request'])}",
        tg.inline_keyboard([[("✅ Отправить", "lead:send"), ("✏️ Заполнить заново", "lead:restart")]]),
    )


def _on_callback(db: Session, cq: dict) -> None:
    msg = cq.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    if chat_id is None:
        return
    user = cq.get("from", {})
    s = _session(db, chat_id)

    def answer(text: str | None = None) -> None:
        try:
            tg.call("answerCallbackQuery", callback_query_id=cq["id"], text=text)
        except Exception:
            log.exception("answerCallbackQuery")

    def drop_buttons() -> None:
        try:
            tg.call("editMessageReplyMarkup", chat_id=chat_id, message_id=msg["message_id"])
        except Exception:
            pass

    if cq.get("data") == "lead:restart":
        answer()
        drop_buttons()
        _start(db, s, user)
        return

    if cq.get("data") != "lead:send":
        answer()
        return

    # Двойное нажатие «Отправить» не создаст второй лид: после первого шаг уже сброшен.
    if s.step != "confirm":
        answer("Эта заявка уже отправлена")
        drop_buttons()
        return

    d = s.data
    lead = create_lead(
        db,
        name=d["name"],
        contact=d["contact"],
        request=d["request"],
        source=Source.BOT,
        tg_user_id=user.get("id"),
        tg_username=user.get("username"),
    )
    _set(db, s, "")
    answer("Заявка отправлена")
    drop_buttons()
    tg.send(
        chat_id,
        f"Спасибо! Заявка <b>№{lead.id}</b> принята — менеджер свяжется с вами в ближайшее время.\n\n"
        "Чтобы оставить ещё одну заявку, нажмите /start",
    )
    notify_managers(db, lead)


# ---------------------------------------------------------------- notifications


def _manager(db: Session, chat_id: int, user: dict, code: str) -> None:
    if code.lower() == "off":
        if m := db.get(Manager, chat_id):
            db.delete(m)
            db.commit()
        tg.send(chat_id, "Уведомления о новых лидах выключены.")
        return
    if not MANAGER_CODE or code != MANAGER_CODE:
        tg.send(chat_id, "Неверный код менеджера.")
        return
    if not db.get(Manager, chat_id):
        db.add(Manager(chat_id=chat_id, name=_full_name(user) or user.get("username", "")))
        db.commit()
    tg.send(
        chat_id,
        "Готово — сюда будут приходить уведомления о новых лидах.\nВыключить: <code>/manager off</code>",
    )


# ---------------------------------------------------------------- Telegram Business (пункт 2)


def _on_business_connection(db: Session, bc: dict) -> None:
    """Владелец аккаунта подключил (или отключил) бота в «Настройки → Telegram для бизнеса → Чат-боты»."""
    conn = db.get(BusinessConnection, bc["id"]) or BusinessConnection(id=bc["id"])
    conn.owner_user_id = bc["user"]["id"]
    conn.owner_name = _full_name(bc["user"])
    conn.is_enabled = bc.get("is_enabled", True)
    db.add(conn)
    db.commit()


def _business_owner_id(db: Session, connection_id: str) -> int | None:
    if conn := db.get(BusinessConnection, connection_id):
        return conn.owner_user_id
    try:
        bc = tg.call("getBusinessConnection", business_connection_id=connection_id)
    except Exception:
        log.exception("getBusinessConnection")
        return None
    _on_business_connection(db, bc)
    return bc["user"]["id"]


def _describe(msg: dict) -> str:
    if text := msg.get("text") or msg.get("caption"):
        return text
    for key, label in (
        ("photo", "фото"),
        ("voice", "голосовое сообщение"),
        ("video", "видео"),
        ("video_note", "видеосообщение"),
        ("document", "файл"),
        ("sticker", "стикер"),
        ("contact", "контакт"),
        ("location", "геолокация"),
    ):
        if key in msg:
            return f"[{label}]"
    return "[сообщение]"


def _on_business_message(db: Session, msg: dict) -> None:
    """Входящее в личный аккаунт: новый собеседник → новый лид, повторное сообщение → в историю его лида."""
    sender = msg.get("from", {})
    if sender.get("is_bot") or msg.get("chat", {}).get("type") != "private":
        return
    owner_id = _business_owner_id(db, msg["business_connection_id"])
    if owner_id is None or sender.get("id") == owner_id:
        return  # собственные исходящие владельца аккаунта не считаем лидами

    text = _describe(msg)
    lead = db.scalar(
        select(Lead)
        .where(Lead.tg_user_id == sender["id"], Lead.source == Source.BUSINESS, Lead.status.in_(Status.OPEN))
        .order_by(Lead.created_at.desc())
    )
    if lead:
        lead.notes.append(Note(kind="client", text=text))
        db.commit()
        return

    username = sender.get("username")
    lead = create_lead(
        db,
        name=_full_name(sender) or username or f"id {sender['id']}",
        contact=f"@{username}" if username else "",
        request=text,
        source=Source.BUSINESS,
        tg_user_id=sender["id"],
        tg_username=username,
    )
    notify_managers(db, lead)

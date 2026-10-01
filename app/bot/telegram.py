"""Минимальный клиент Telegram Bot API.

Используем «голый» HTTP вместо фреймворка: на serverless каждый апдейт — отдельный короткий запрос,
и нам нужен полный контроль над тем, где хранится состояние диалога (в БД, а не в памяти процесса).
"""

import logging

import httpx

from app.config import BOT_TOKEN

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    pass


def call(method: str, **params) -> dict | list | bool:
    if not BOT_TOKEN:
        raise TelegramError("BOT_TOKEN не задан")
    payload = {k: v for k, v in params.items() if v is not None}
    resp = httpx.post(API.format(token=BOT_TOKEN, method=method), json=payload, timeout=15)
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(f"{method}: {data.get('description')}")
    return data["result"]


def send(chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    try:
        call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            link_preview_options={"is_disabled": True},
        )
    except (TelegramError, httpx.HTTPError):
        log.exception("Не удалось отправить сообщение в чат %s", chat_id)


def reply_keyboard(rows: list[list[dict | str]]) -> dict:
    return {
        "keyboard": [[b if isinstance(b, dict) else {"text": b} for b in row] for row in rows],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def inline_keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


REMOVE_KEYBOARD = {"remove_keyboard": True}

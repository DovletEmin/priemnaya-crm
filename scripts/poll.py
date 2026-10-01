"""Локальный режим бота: long polling вместо webhook.

Запуск:  python -m scripts.poll
Обрабатывает апдейты тем же handle_update(), что и прод. Webhook на время работы снимается —
после локальной отладки переподключите бота в CRM (Подключения → «Подключить бота»).
"""

import logging
import time

from app.bot import telegram as tg
from app.bot.handlers import handle_update
from app.main import SessionLocal  # noqa: F401 — импорт создаёт таблицы

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("poll")

ALLOWED = ["message", "callback_query", "business_connection", "business_message"]


def main() -> None:
    me = tg.call("getMe")
    tg.call("deleteWebhook")
    log.info("Бот @%s слушает сообщения. Ctrl+C — остановить.", me["username"])
    offset = None
    while True:
        try:
            updates = tg.call("getUpdates", offset=offset, timeout=25, allowed_updates=ALLOWED)
        except Exception:
            log.exception("getUpdates")
            time.sleep(3)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            try:
                with SessionLocal() as db:
                    handle_update(db, upd)
            except Exception:
                log.exception("Ошибка обработки апдейта %s", upd["update_id"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

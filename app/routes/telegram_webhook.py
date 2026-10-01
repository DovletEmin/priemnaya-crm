import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.bot.handlers import handle_update
from app.config import WEBHOOK_SECRET
from app.db import SessionLocal

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    # Telegram передаёт секрет, указанный в setWebhook, — так чужие запросы не создадут лидов
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if WEBHOOK_SECRET and not hmac.compare_digest(got, WEBHOOK_SECRET):
        return JSONResponse({"ok": False}, status_code=403)

    update = await request.json()
    # Обработчик синхронный (БД + HTTP к Telegram) — выносим в пул потоков, чтобы не блокировать event loop
    await run_in_threadpool(_process, update)
    return {"ok": True}


def _process(update: dict) -> None:
    try:
        with SessionLocal() as db:
            handle_update(db, update)
    except Exception:
        # Всегда отвечаем 200: иначе Telegram будет бесконечно повторять «сломанный» апдейт
        log.exception("Ошибка обработки апдейта %s", update.get("update_id"))

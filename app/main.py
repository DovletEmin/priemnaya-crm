import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import SESSION_SECRET
from app.db import Base, SessionLocal, engine
from app.routes import telegram_webhook, web
from app.services import seed_tags
from app.web_utils import LoginRequired

logging.basicConfig(level=logging.INFO)
# httpx логирует полный URL запроса, а в URL Bot API лежит токен — не пускаем его в логи
logging.getLogger("httpx").setLevel(logging.WARNING)

ROOT = Path(__file__).resolve().parent.parent

# Схема создаётся при холодном старте. Для MVP этого достаточно; дальше — Alembic-миграции.
Base.metadata.create_all(engine)
with SessionLocal() as _db:
    seed_tags(_db)

app = FastAPI(title="Приёмная — мини-CRM", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=60 * 60 * 24 * 14, same_site="lax")

# На Vercel public/ раздаёт CDN (монтировать её нельзя), локально статику отдаёт сам FastAPI
if not os.getenv("VERCEL"):
    app.mount("/static", StaticFiles(directory=ROOT / "public" / "static"), name="static")

app.include_router(web.router)
app.include_router(telegram_webhook.router)


@app.exception_handler(LoginRequired)
def _login_required(request: Request, exc: LoginRequired):
    if request.headers.get("HX-Request"):
        resp = RedirectResponse("/login", status_code=204)
        resp.headers["HX-Redirect"] = "/login"
        return resp
    return RedirectResponse("/login", status_code=303)

import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _db_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./crm.db")
    # Neon/Vercel отдают postgres:// или postgresql:// — SQLAlchemy нужен явный драйвер psycopg
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _public_url() -> str:
    url = os.getenv("PUBLIC_URL", "")
    if not url and os.getenv("VERCEL_PROJECT_PRODUCTION_URL"):
        url = "https://" + os.environ["VERCEL_PROJECT_PRODUCTION_URL"]
    return url.rstrip("/")


DATABASE_URL = _db_url()
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
MANAGER_CODE = os.getenv("MANAGER_CODE", "")
PUBLIC_URL = _public_url()
TZ = ZoneInfo(os.getenv("APP_TZ", "Europe/Moscow"))

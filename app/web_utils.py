from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import TZ

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _local(dt: datetime) -> datetime:
    if dt.tzinfo is None:  # SQLite возвращает naive datetime — он у нас всегда в UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


def human_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = _local(dt)
    today = datetime.now(TZ).date()
    hm = local.strftime("%H:%M")
    if local.date() == today:
        return f"сегодня, {hm}"
    if local.date() == today - timedelta(days=1):
        return f"вчера, {hm}"
    date = f"{local.day} {MONTHS[local.month - 1]}"
    if local.year != today.year:
        date += f" {local.year}"
    return f"{date}, {hm}"


def full_time(dt: datetime | None) -> str:
    return _local(dt).strftime("%d.%m.%Y %H:%M") if dt else ""


def leads_url(f: dict, **overrides) -> str:
    """URL списка лидов с текущими фильтрами, часть которых заменена."""
    params = {k: v for k, v in {**f, **overrides}.items() if v not in (None, "")}
    return "/leads" + ("?" + urlencode(params) if params else "")


def contact_href(contact: str) -> str | None:
    c = contact.strip()
    if c.startswith("@"):
        return "https://t.me/" + c[1:]
    if "t.me/" in c:
        return c if c.startswith("http") else "https://" + c
    if "@" in c:
        return "mailto:" + c
    digits = "".join(ch for ch in c if ch.isdigit() or ch == "+")
    if sum(ch.isdigit() for ch in digits) >= 7:
        return "tel:" + digits
    return None


templates.env.filters["human_time"] = human_time
templates.env.filters["full_time"] = full_time
templates.env.globals["leads_url"] = leads_url
templates.env.globals["contact_href"] = contact_href


class LoginRequired(Exception):
    pass


def require_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise LoginRequired()
    return user


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"

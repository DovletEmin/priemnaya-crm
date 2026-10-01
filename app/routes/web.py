import hmac
import logging
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.bot import telegram as tg
from app.config import ADMIN_LOGIN, ADMIN_PASSWORD, BOT_TOKEN, MANAGER_CODE, PUBLIC_URL, WEBHOOK_SECRET
from app.db import get_db
from app.models import BusinessConnection, Lead, Manager, Note, Source, Status, Tag, lead_tags
from app.services import TAG_COLORS, create_lead, get_or_create_tag
from app.web_utils import is_htmx, require_user, templates

log = logging.getLogger(__name__)
router = APIRouter()
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"Status": Status, "Source": Source, **ctx})


def sidebar_ctx(db: Session) -> dict:
    """Теги с количеством лидов — для боковой панели на всех страницах."""
    rows = db.execute(
        select(Tag, func.count(lead_tags.c.lead_id))
        .outerjoin(lead_tags, lead_tags.c.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(Tag.name)
    ).all()
    total = db.scalar(select(func.count(Lead.id))) or 0
    return {"sidebar_tags": rows, "total_leads": total}


def get_lead(db: Session, lead_id: int) -> Lead:
    lead = db.get(Lead, lead_id, options=[selectinload(Lead.tags), selectinload(Lead.notes)])
    if not lead:
        raise HTTPException(404, "Лид не найден")
    return lead


# ---------------------------------------------------------------- auth


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", error=None)


@router.post("/login")
def login(request: Request, login: str = Form(""), password: str = Form("")):
    ok = hmac.compare_digest(login.encode(), ADMIN_LOGIN.encode()) & hmac.compare_digest(
        password.encode(), ADMIN_PASSWORD.encode()
    )
    if not ok:
        return render(request, "login.html", error="Неверный логин или пароль", login=login)
    request.session["user"] = login
    return RedirectResponse("/leads", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------- leads list


@router.get("/")
def index():
    return RedirectResponse("/leads", status_code=303)


@router.get("/leads", response_class=HTMLResponse)
def leads_list(
    request: Request,
    q: str = "",
    tag: int | None = None,
    status: str = "",
    source: str = "",
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    q = q.strip()
    base = select(Lead)
    if q:
        like = f"%{q}%"
        base = base.where(or_(Lead.name.ilike(like), Lead.contact.ilike(like), Lead.request.ilike(like)))
    if tag:
        base = base.where(Lead.tags.any(Tag.id == tag))
    if source in Source.LABELS:
        base = base.where(Lead.source == source)

    # Воронка считается по всем фильтрам, кроме статуса, — чтобы клик по сегменту показывал реальные числа
    sub = base.with_only_columns(Lead.status, func.count(Lead.id)).group_by(Lead.status)
    counts = {s: 0 for s in Status.ORDER} | dict(db.execute(sub).all())
    pipeline_total = sum(counts.values())

    if status in Status.LABELS:
        base = base.where(Lead.status == status)
    leads = db.scalars(base.options(selectinload(Lead.tags)).order_by(Lead.created_at.desc()).limit(500)).all()

    ctx = dict(
        leads=leads,
        counts=counts,
        pipeline_total=pipeline_total,
        f={"q": q, "tag": tag, "status": status, "source": source},
        active_tag=db.get(Tag, tag) if tag else None,
    )
    if is_htmx(request) and request.headers.get("HX-Target") == "results":
        return render(request, "partials/leads_results.html", **ctx)
    return render(request, "leads.html", **ctx, **sidebar_ctx(db), user=user)


# ---------------------------------------------------------------- create / edit


@router.get("/leads/new", response_class=HTMLResponse)
def lead_new_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_user)):
    tags = db.scalars(select(Tag).order_by(Tag.name)).all()
    return render(request, "lead_form.html", lead=None, all_tags=tags, form={}, errors={}, **sidebar_ctx(db))


def _validate(name: str, contact: str, request_text: str) -> dict:
    errors = {}
    if len(name.strip()) < 2:
        errors["name"] = "Укажите имя — хотя бы 2 символа"
    if not contact.strip() and not request_text.strip():
        errors["contact"] = "Нужен контакт или описание запроса, иначе с лидом нечего делать"
    return errors


@router.post("/leads/new")
async def lead_create(
    request: Request,
    name: str = Form(""),
    contact: str = Form(""),
    request_text: str = Form("", alias="request"),
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    form = await request.form()
    tag_ids = [int(t) for t in form.getlist("tags") if str(t).isdigit()]
    errors = _validate(name, contact, request_text)
    if errors:
        tags = db.scalars(select(Tag).order_by(Tag.name)).all()
        ctx = dict(lead=None, all_tags=tags, errors=errors, **sidebar_ctx(db))
        ctx["form"] = {"name": name, "contact": contact, "request": request_text, "tags": tag_ids}
        return render(request, "lead_form.html", **ctx)
    tags = db.scalars(select(Tag).where(Tag.id.in_(tag_ids))).all() if tag_ids else []
    lead = create_lead(db, name=name, contact=contact, request=request_text, source=Source.MANUAL, tags=list(tags))
    return RedirectResponse(f"/leads/{lead.id}", status_code=303)


@router.get("/leads/{lead_id}/edit", response_class=HTMLResponse)
def lead_edit_page(lead_id: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_user)):
    lead = get_lead(db, lead_id)
    form = {"name": lead.name, "contact": lead.contact, "request": lead.request}
    return render(request, "lead_form.html", lead=lead, all_tags=[], form=form, errors={}, **sidebar_ctx(db))


@router.post("/leads/{lead_id}/edit")
def lead_update(
    lead_id: int,
    request: Request,
    name: str = Form(""),
    contact: str = Form(""),
    request_text: str = Form("", alias="request"),
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    lead = get_lead(db, lead_id)
    errors = _validate(name, contact, request_text)
    if errors:
        form = {"name": name, "contact": contact, "request": request_text}
        return render(request, "lead_form.html", lead=lead, all_tags=[], form=form, errors=errors, **sidebar_ctx(db))
    lead.name, lead.contact, lead.request = name.strip(), contact.strip(), request_text.strip()
    lead.notes.append(Note(kind="system", text="Данные лида изменены"))
    db.commit()
    return RedirectResponse(f"/leads/{lead.id}", status_code=303)


@router.post("/leads/{lead_id}/delete")
def lead_delete(lead_id: int, db: Session = Depends(get_db), user: str = Depends(require_user)):
    db.delete(get_lead(db, lead_id))
    db.commit()
    return RedirectResponse("/leads", status_code=303)


# ---------------------------------------------------------------- lead card (HTMX-действия возвращают карточку целиком)


def lead_card(request: Request, db: Session, lead: Lead, **extra) -> HTMLResponse:
    tags = db.scalars(select(Tag).order_by(Tag.name)).all()
    template = "partials/lead_card.html" if is_htmx(request) else "lead.html"
    return render(request, template, lead=lead, all_tags=tags, **extra, **sidebar_ctx(db))


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_page(lead_id: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_user)):
    return lead_card(request, db, get_lead(db, lead_id))


@router.post("/leads/{lead_id}/status", response_class=HTMLResponse)
def lead_status(
    lead_id: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    lead = get_lead(db, lead_id)
    if status in Status.LABELS and status != lead.status:
        lead.notes.append(Note(kind="system", text=f"Статус: {lead.status_label} → {Status.LABELS[status]}"))
        lead.status = status
        db.commit()
    return lead_card(request, db, lead)


@router.post("/leads/{lead_id}/tags", response_class=HTMLResponse)
def lead_tag_add(
    lead_id: int,
    request: Request,
    name: str = Form(""),
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    lead = get_lead(db, lead_id)
    tag = get_or_create_tag(db, name)
    if tag and tag not in lead.tags:
        lead.tags.append(tag)
    db.commit()
    return lead_card(request, db, lead)


@router.post("/leads/{lead_id}/tags/{tag_id}/remove", response_class=HTMLResponse)
def lead_tag_remove(
    lead_id: int, tag_id: int, request: Request, db: Session = Depends(get_db), user: str = Depends(require_user)
):
    lead = get_lead(db, lead_id)
    lead.tags = [t for t in lead.tags if t.id != tag_id]
    db.commit()
    return lead_card(request, db, lead)


@router.post("/leads/{lead_id}/notes", response_class=HTMLResponse)
def lead_note_add(
    lead_id: int,
    request: Request,
    text: str = Form(""),
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    lead = get_lead(db, lead_id)
    if text.strip():
        lead.notes.append(Note(kind="manager", text=text.strip()[:4000]))
        db.commit()
    return lead_card(request, db, lead)


# ---------------------------------------------------------------- tags


@router.get("/tags", response_class=HTMLResponse)
def tags_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_user)):
    return render(request, "tags.html", colors=TAG_COLORS, error=None, **sidebar_ctx(db))


@router.post("/tags")
def tag_create(
    request: Request,
    name: str = Form(""),
    color: str = Form(""),
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    name = " ".join(name.split())[:50]
    if not name:
        return render(request, "tags.html", colors=TAG_COLORS, error="Введите название тега", **sidebar_ctx(db))
    if db.scalar(select(Tag).where(func.lower(Tag.name) == name.lower())):
        error = f"Тег «{name}» уже есть"
        return render(request, "tags.html", colors=TAG_COLORS, error=error, **sidebar_ctx(db))
    db.add(Tag(name=name, color=color if HEX_RE.match(color) else TAG_COLORS[0]))
    db.commit()
    return RedirectResponse("/tags", status_code=303)


@router.post("/tags/{tag_id}/color")
def tag_color(tag_id: int, color: str = Form(""), db: Session = Depends(get_db), user: str = Depends(require_user)):
    tag = db.get(Tag, tag_id)
    if tag and HEX_RE.match(color):
        tag.color = color
        db.commit()
    return RedirectResponse("/tags", status_code=303)


@router.post("/tags/{tag_id}/delete")
def tag_delete(tag_id: int, db: Session = Depends(get_db), user: str = Depends(require_user)):
    if tag := db.get(Tag, tag_id):
        db.delete(tag)
        db.commit()
    return RedirectResponse("/tags", status_code=303)


# ---------------------------------------------------------------- settings


def _base_url(request: Request) -> str:
    return PUBLIC_URL or str(request.base_url).rstrip("/")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), user: str = Depends(require_user)):
    bot, webhook, bot_error = None, None, None
    if BOT_TOKEN:
        try:
            bot = tg.call("getMe")
            webhook = tg.call("getWebhookInfo")
        except Exception as e:
            bot_error = str(e)
    return render(
        request,
        "settings.html",
        bot=bot,
        webhook=webhook,
        bot_error=bot_error,
        has_token=bool(BOT_TOKEN),
        expected_webhook=_base_url(request) + "/telegram/webhook",
        managers=db.scalars(select(Manager).order_by(Manager.created_at)).all(),
        connections=db.scalars(select(BusinessConnection)).all(),
        manager_code=MANAGER_CODE,
        message=request.query_params.get("msg"),
        **sidebar_ctx(db),
    )


@router.post("/settings/webhook")
def settings_webhook(request: Request, user: str = Depends(require_user)):
    url = _base_url(request) + "/telegram/webhook"
    try:
        tg.call(
            "setWebhook",
            url=url,
            secret_token=WEBHOOK_SECRET or None,
            allowed_updates=["message", "callback_query", "business_connection", "business_message"],
            drop_pending_updates=False,
        )
        msg = "Бот подключён"
    except Exception as e:
        log.exception("setWebhook")
        msg = f"Ошибка: {e}"
    return RedirectResponse(f"/settings?msg={quote(msg)}", status_code=303)


@router.post("/settings/managers/{chat_id}/delete")
def manager_delete(chat_id: int, db: Session = Depends(get_db), user: str = Depends(require_user)):
    if m := db.get(Manager, chat_id):
        db.delete(m)
        db.commit()
    return RedirectResponse("/settings", status_code=303)

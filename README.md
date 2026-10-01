# Приёмная — мини-CRM для заявок агентства

Лиды из Telegram-бота, из личного Telegram (через Telegram Business) и добавленные вручную — в одном списке, с тегами, статусами и историей.

**Стек:** Python 3.12 · FastAPI · SQLAlchemy · HTMX · Tailwind CSS · Telegram Bot API (webhook) · Vercel + Neon Postgres

## Как это устроено

```
Клиент ──► @бот (диалог: имя → контакт → запрос → подтверждение) ─┐
                                                                    │  webhook
Клиент ──► личный Telegram менеджера ──(Telegram Business)─────────┤  POST /telegram/webhook
                                                                    ▼
Менеджер ──► CRM в браузере (ручное добавление) ────────────► FastAPI ──► Postgres
                                                                    │
                                    уведомление о новом лиде ◄──────┘  (менеджерам, подписанным /manager <код>)
```

- **Webhook, а не polling** — на serverless нет постоянного процесса; каждый апдейт — отдельный HTTP-запрос.
- **Шаг диалога хранится в БД** (`bot_sessions`) — память функции между запросами не живёт.
- **Идемпотентность** — `update_id` запоминается, повторная доставка от Telegram не создаёт дубль лида.
- **Двойной клик «Отправить»** не создаёт второй лид — после первого нажатия шаг диалога сброшен.
- **Личный Telegram**: новый собеседник → новый лид; его следующие сообщения → в историю открытого лида. Исходящие сообщения владельца аккаунта игнорируются.

## Структура

```
app/
  main.py               приложение FastAPI (точка входа и для uvicorn, и для Vercel)
  models.py             Lead, Tag, Note, BotSession, Manager, BusinessConnection
  services.py           создание лида, теги, уведомления — общее для CRM и бота
  bot/handlers.py       сценарий бота и Telegram Business
  bot/telegram.py       тонкий клиент Bot API
  routes/web.py         страницы CRM (HTMX)
  routes/telegram_webhook.py
  templates/            Jinja2-шаблоны
frontend/input.css      дизайн-токены и Tailwind → public/static/app.css
scripts/poll.py         локальный запуск бота без webhook
scripts/seed_demo.py    демо-лиды
```

## Локальный запуск

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # заполните BOT_TOKEN, ADMIN_PASSWORD и т.д.

uvicorn app.main:app --reload     # CRM: http://localhost:8000
python -m scripts.poll            # бот (в соседнем терминале)
python -m scripts.seed_demo       # по желанию: демо-лиды
```

Стили (нужно только при изменении шаблонов): `cd frontend && npm install && npm run build`.

## Деплой на Vercel

1. Репозиторий на GitHub → **Import Project** в Vercel.
2. **Storage → Neon Postgres** — `DATABASE_URL` подставится автоматически.
3. Переменные окружения: `BOT_TOKEN`, `WEBHOOK_SECRET`, `ADMIN_LOGIN`, `ADMIN_PASSWORD`, `SESSION_SECRET`, `MANAGER_CODE`, `PUBLIC_URL`.
4. После деплоя: CRM → **Подключения → «Подключить бота»** (вызывает `setWebhook`).

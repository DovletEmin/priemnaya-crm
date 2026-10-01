"""Демо-лиды, чтобы CRM не была пустой при первом показе.  Запуск: python -m scripts.seed_demo"""

from datetime import timedelta

from sqlalchemy import select

from app.main import SessionLocal
from app.models import Lead, Note, Source, Status, Tag, utcnow

DEMO = [
    ("Мария Ковалёва", "@m_kovaleva", "Нужен лендинг для онлайн-школы английского, запуск рекламы в ноябре. Бюджет до 150 тыс.",
     Source.BOT, Status.NEW, ["сайт", "горячий"], 0.2),
    ("Игорь Ли", "+7 916 555-12-40", "Ведение VK и Telegram-канала для сети кофеен, 3 точки в Казани.",
     Source.MANUAL, Status.IN_PROGRESS, ["SMM"], 5),
    ("Studio Nord", "hello@studionord.ru", "Перезапуск таргета: сейчас заявка стоит 1200 ₽, хотим вдвое дешевле.",
     Source.BOT, Status.IN_PROGRESS, ["реклама"], 27),
    ("Алексей", "@alex_frm", "Добрый день! Вы делаете сайты на Тильде? Сколько стоит интернет-магазин?",
     Source.BUSINESS, Status.NEW, [], 49),
    ("Ольга Петренко", "+7 903 120-88-01", "Повторный заказ: обновить посадочную под весеннюю коллекцию.",
     Source.MANUAL, Status.WON, ["повторный", "сайт"], 120),
    ("Денис", "@denis_k", "Нужен бот для записи клиентов в барбершоп.",
     Source.BOT, Status.LOST, [], 200),
]


def main() -> None:
    with SessionLocal() as db:
        tags = {t.name: t for t in db.scalars(select(Tag))}
        for name, contact, req, source, status, tag_names, hours_ago in DEMO:
            created = utcnow() - timedelta(hours=hours_ago)
            lead = Lead(name=name, contact=contact, request=req, source=source, status=status,
                        created_at=created, updated_at=created, tags=[tags[n] for n in tag_names if n in tags])
            lead.notes.append(Note(kind="system", text=f"Лид создан · {Source.LABELS[source]}", created_at=created))
            db.add(lead)
        db.commit()
    print(f"Добавлено демо-лидов: {len(DEMO)}")


if __name__ == "__main__":
    main()

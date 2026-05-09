# LithTGBot

Telegram-бот для поиска товаров и отслеживания цен. Интегрирован с инфраструктурой Window of Light: ходит в её FastAPI за поиском и категориями, читает PostgreSQL для каталога и пишет собственные таблицы — отслеживания и историю запросов.

## Возможности

- 🔎 Текстовый поиск с нормализацией запросов (опечатки, RU↔EN, сокращения вроде «17 PM 256» → `iPhone 17 Pro Max 256GB`).
- 🗂 Каталог моделей с динамическим списком из БД.
- 🔔 Отслеживание цен: уведомления при изменении.
- 📜 История запросов с актуализацией цен через `asyncio.gather`.
- ⏱ Rate limit: 10 запросов/мин на пользователя (Redis).
- 🛠 Admin-команды: `/admin`, `/admin_stats`, `/admin_top_*`, `/db_table`, `/db_schema`.

## Стек

Python 3.10 · aiogram 3.3+ · SQLAlchemy 2.0 (async) · asyncpg · httpx · redis (async) · Celery 5.3+ · Alembic · pydantic 2.5+ · thefuzz.

## Структура

```
bot/handlers/      Telegram handlers (search, catalog, tracking, history, admin, common)
bot/keyboards/     Reply / inline keyboards
bot/middlewares/   Rate limit
services/          Бизнес-логика: normalizer, query_router, search, cleanup, redis_store
integrations/      Клиент Window of Light API (httpx)
database/          Модели + репозитории (catalog, tracked, history)
schemas/           Pydantic DTO
tasks/             Celery app + periodic price tracking
migrations/        Alembic
tests/             pytest
```

Полное ТЗ — [`CLAUDE.md`](./CLAUDE.md), быстрый индекс — [`LISTING.md`](./LISTING.md), правила работы — [`AGENTS.md`](./AGENTS.md).

## Запуск

```bash
cp .env.example .env  # заполнить токен бота, доступ к БД/Redis/WOL API
docker compose up -d
```

Локально без docker:

```bash
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python main.py
```

В docker-compose поднимаются три сервиса: `bot`, `celery_worker`, `celery_beat`.

## Тесты и линт

```bash
pytest -q
ruff check .
```

## Конфигурация

Все настройки — через `.env` (см. `.env.example`). Обязательны: `TELEGRAM_BOT_TOKEN`, `DB_*`, `REDIS_*`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`. Прокси для Telegram и `ADMIN_USER_IDS` опциональны.

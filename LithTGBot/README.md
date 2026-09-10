# LithTGBot

Telegram ↔ MAX bridge — сервис для управления автоматическими рассылками в мессенджере MAX (max.ru) через Telegram-бота.

## Стек

Python 3.11 · aiogram 3.x · PyMax (maxapi-python) · SQLAlchemy 2.0 (async, asyncpg) · PostgreSQL 15+ · AES-256 · Docker Compose

## Запуск

```bash
cp .env.example .env   # заполнить переменные
docker compose up -d   # db, vpn, bot, worker
```

## Архитектура

- **Bot** — Telegram-интерфейс (aiogram 3), управление проектами/группами/расписаниями
- **Worker** — фоновый процесс, рассылка через PyMax (WebSocket API MAX)
- **VPN** — gluetun (WireGuard) с Kill Switch
- **DB** — PostgreSQL, схема: users, projects, messages, groups, schedules, logs

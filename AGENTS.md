# AGENTS.md — Шпаргалка для ИИ-ассистента

## Правила работы

1. **Писать кратко.** Без преамбул, объяснений "что сделал" и саммари после каждого шага.
2. **Прибегать к мульти-агентам** (Task tool) для параллельного исследования и сложных задач.
3. **Точечные правки.** Не переписывать файлы целиком — менять только нужные строки/функции.
4. **Читать контекст** перед правкой: соседние строки, импорты, конвенции файла.
5. **Не добавлять комментарии** в код, если не просят.
6. **Не коммитить** без явной просьбы.
7. **Проверять** `ruff`/`pytest` после изменений, если есть сомнения.

---

## Техстек

Python 3.10 | aiogram 3.3+ | SQLAlchemy 2.0+ (async) | httpx | redis (async) | celery 5.3+ | pydantic 2.5+ | alembic | thefuzz

---

## Структура проекта и назначение файлов

### Корень

| Файл | Назначение |
|---|---|
| `main.py` | Точка входа. Создаёт Bot (с прокси), Dispatcher (Redis FSM), регистрирует 6 роутеров, запускает long-polling. Порядок роутеров критичен: search — последний (catch-all). |
| `config.py` | `Settings(BaseSettings)` — все настройки из `.env`. Парсит `admin_user_ids` в `set[int]`. Свойства: `database_url`, `redis_url`, `telegram_proxy_url`. |
| `requirements.txt` | 14 зависимостей. aiogram, httpx, SQLAlchemy, asyncpg, redis, celery, pydantic-settings, alembic, thefuzz, aiohttp_socks, pytest. |
| `.env.example` | Placeholder-ы для всех переменных. Без реальных паролей. |
| `alembic.ini` | Конфиг Alembic. `sqlalchemy.url` — плейсхолдер, реальный URL задаётся в `migrations/env.py`. |
| `docker-compose.yml` | 3 сервиса: `bot`, `celery_worker`, `celery_beat`. Общий Dockerfile и `.env`. |
| `Dockerfile` | Python 3.10-slim, gcc/libpq-dev, TZ=Europe/Moscow. |
| `CLAUDE.md` | Полное ТЗ (29 секций). Архитектура, API-контракты, нормализация, UI-форматы, acceptance criteria. |
| `LISTING.md` | Быстрый индекс проекта (27 секций). Дублирует структуру CLAUDE.md для навигации. |

### `bot/handlers/` — Telegram-обработчики

| Файл | Назначение |
|---|---|
| `common.py` | `/start`, `/help`, кнопка "🔎 Поиск". Динамическая панель моделей из БД (`_build_model_panel`). `CATEGORY_CONFIG` — маппинг категорий на эмодзи/названия. |
| `search.py` | **Самый большой (796 строк).** Текстовый поиск, пагинация (`s:token:page`), карточка товара (`p:short_id`), клик по модели (`m:short_id`), пагинация моделей (`ms:`), варианты цен (`pv:`), оригинал (`o:`), таблица цен (`pt:`), список цен (`pl:`). `_build_model_text()` — таблица сравнения цен по каналам. `_model_matches_query()` — защита от ложного совпадения "iPhone 17 Pro" с "iPhone 17 Pro Max". |
| `catalog.py` | `/catalog` (категории из WOL API), "последние товары", `/db_table` (admin-only, allowlist), `/db_schema` (admin-only). |
| `admin.py` | `/admin`, `/admin_stats`, `/admin_top_{day,week,month}`. Проверка `is_admin()` через `settings.admin_user_ids`. |
| `tracking.py` | `/tracked`, кнопка "🔔 Отслеживаемые", `t:short_id` (добавить), `ut:tracked_id` (отключить), `ph:short_id` (история цен). |
| `history.py` | `/history`, кнопка "📜 История", `hd:history_id` (удалить), `r:history_id` (повторить). Актуальные цены через `asyncio.gather`. |

### `bot/keyboards/` — Клавиатуры

| Файл | Назначение |
|---|---|
| `menu.py` | `ReplyKeyboardMarkup`: 4 кнопки (Поиск, История, Отслеживаемые, Помощь). **Нет кнопки "Каталог"** — несоответствие ТЗ. |
| `product.py` | Inline-клавиатуры: карточка товара (История цен / Отслеживать / Оригинал / Назад), пагинация поиска (← / стр.N / →). |

### `bot/middlewares/`

| Файл | Назначение |
|---|---|
| `rate_limit.py` | `RateLimitMiddleware`. Redis `INCR` по ключу `rate:{user_id}:{minute}`. 10 запросов/мин. Пропускает команды (`/`). Fallback при недоступности Redis. |

### `services/` — Бизнес-логика

| Файл | Назначение |
|---|---|
| `normalizer.py` | `QueryNormalizer`. Многостадийная нормализация: fuzzy matching (thefuzz), RU→EN маппинг, нормализация памяти (`256`→`256GB`), раскрытие сокращений (`17 PM`→`iPhone 17 Pro Max`), контекстная защита от ложных iPhone-совпадений. Синглтон: `normalizer`. |
| `query_router.py` | `QueryRouter`. Нормализованный текст → `ProductSearchRequest` для WOL API. Извлекает: цены ("до 90000"), процессор, память, connectivity, SIM. Определяет бренд/категорию по ключевым словам. Синглтон: `query_router`. |
| `search.py` | `SearchService`. Оркестрация: normalize → route → Redis cache → WOL API → cache → history → `SearchResultDTO`. `limit = page_size + 1` для определения следующей страницы. MD5-хеш запроса как ключ кэша. Синглтон: `search_service`. |
| `cleanup.py` | `CleanupService`.Автоудаление старых сообщений с результатами. Redis-список `cleanup:{chat_id}`, макс 3 сообщения. `register_message()` — добавить и удалить старые. Синглтон: `cleanup_service`. |
| `redis_store.py` | `RedisStore`. Короткие ID (8 hex из UUID) для callback_data. `generate_short_id()` → `product_short:{short_id}` (TTL 24ч). `save_query_token()` → `query_token:{token}` (TTL 30мин). Синглтон: `redis_store`. |

### `integrations/`

| Файл | Назначение |
|---|---|
| `wol_api.py` | `WolApiClient`. Async httpx-клиент для WOL API. Методы: `check_health`, `get_status`, `search_products`, `get_product`, `get_product_history`, `get_raw_post`, `get_categories`. Создаёт новый клиент на каждый запрос (нет пула соединений). Синглтон: `wol_api_client`. |

### `database/`

| Файл | Назначение |
|---|---|
| `models.py` | SQLAlchemy-модели 8 таблиц. **WOL (read-only):** `Category`, `Channel`, `RawPost`, `Product`, `PriceHistory`, `ApiKey`. **Bot:** `TrackedProduct` (user_id, product_id, цены, is_active), `UserSearchHistory` (user_id, query, normalized_query, product_id, final_price, results_count, metadata_json). `metadata_json = Column("metadata", JSONB)` —避免 конфликта с DeclarativeBase. |
| `session.py` | Async engine (asyncpg) + `async_sessionmaker`. `get_db_session()` — генератор сессий. |
| `repositories/catalog.py` | `CatalogRepository`. Allowlist: `products, raw_posts, price_history, categories, channels`. `browse_table()` — параметризованный SELECT с LIMIT/OFFSET. `get_table_schema()` — information_schema. `get_distinct_models()` — для панели моделей. **Баг строка 90-91:** `AND model !=` — неполное выражение (нет `''`). |
| `repositories/tracked.py` | `TrackedRepository`. CRUD: add_or_update (upsert), deactivate (soft-delete), get_user_tracked, get_all_active, update_prices. |
| `repositories/history.py` | `HistoryRepository`. CRUD: add_record, get_user_history, get_record, delete_record (с проверкой user_id). |

### `schemas/` — DTO

| Файл | Назначение |
|---|---|
| `product.py` | `ProductDTO`, `SearchResultDTO`, `PriceHistoryItemDTO`. |
| `search.py` | `ReplacementDTO`, `NormalizedQueryDTO`, `ProductSearchRequest` (прямое маппинг на WOL API payload). |

### `utils/`

| Файл | Назначение |
|---|---|
| `price_formatter.py` | `format_price(79990)` → `"79 990 ₽"`. `format_price(None)` → `"Цена не указана"`. |
| `text.py` | `escape_html()` — обёртка `html.escape()`. `truncate_text()` — обрезка с суффиксом. |

### `tasks/` — Celery

| Файл | Назначение |
|---|---|
| `celery.py` | Celery app. Beat schedule: `check_tracked_prices` в 10:00 UTC ежедневно. |
| `price_tracking.py` | `run_price_tracking()` — async: обходит все активные отслеживания, получает цену из WOL API, сравнивает с `last_seen_price`, шлёт уведомление при изменении, обновляет БД. `check_tracked_prices()` — sync обёртка через `asyncio.run()`. |

### `migrations/`

| Файл | Назначение |
|---|---|
| `env.py` | Async Alembic. `include_name()` — миграции только для таблиц бота (`tracked_products`, `user_search_history`). |
| `versions/c408f3d0c6bc_*.py` | Создание `tracked_products` (FK→products, unique, 3 индекса) и `user_search_history` (FK→products, 4 индекса). |

### `tests/`

| Файл | Назначение |
|---|---|
| `test_normalizer.py` | 8 тестов: PM/P сокращения, опечатки, RU→EN, Samsung, MacBook, ложные срабатывания. |
| `test_price_formatter.py` | 3 проверки: полная цена, 0, None. |
| `test_rate_limit.py` | Мок Redis: 10 проходят, 11-й блокируется. |
| `test_history.py` | 3 теста: сортировка с актуальными ценами, удаление, повтор. |
| `test_catalog.py` | **Заглушка** — `assert True`. |
| `test_tracking.py` | 1 тест: callback отслеживания с моками. |

---

## Callback data (формат)

| Действие | Формат | Пример |
|---|---|---|
| Пагинация поиска | `s:{token}:{page}` | `s:a3f2c1d0:2` |
| Клик по модели | `m:{short_id}` | `m:b4e3d2a1` |
| Пагинация моделей | `ms:{token}:{page}` | `ms:a3f2c1d0:1` |
| Карточка товара | `p:{short_id}` | `p:c5d4e3f2` |
| Отслеживание | `t:{short_id}` | `t:c5d4e3f2` |
| Отключить | `ut:{tracked_id}` | `ut:42` |
| История цен | `ph:{short_id}` | `ph:c5d4e3f2` |
| Оригинал | `o:{short_id}` | `o:c5d4e3f2` |
| Таблица цен | `pt:{token}` | `pt:a3f2c1d0` |
| Список цен | `pl:{token}:{page}` | `pl:a3f2c1d0:0` |
| Вариант цены | `pv:{short_id}` | `pv:c5d4e3f2` |
| Повтор запроса | `r:{history_id}` | `r:15` |
| Удаление истории | `hd:{history_id}` | `hd:15` |
| Назад к панели | `back_to_panel` | — |
| Обновить панель | `refresh_panel` | — |
| Нет действия | `noop` | — |

---

## Redis-ключи

| Паттерн | TTL | Используется |
|---|---|---|
| `search:{md5}:{page}` | 300с | SearchService |
| `query_token:{8hex}` | 1800с | RedisStore |
| `product_short:{8hex}` | 86400с | RedisStore |
| `rate:{user_id}:{minute}` | 60с | RateLimitMiddleware |
| `cleanup:{chat_id}` | 86400с | CleanupService |
| `last_search:{user_id}` | 1800с | search handler |
| `pv_map:{token}` | 1800с | search handler |
| `orig_lock:{user_id}:{short_id}` | 15с | search handler |

---

## Известные проблемы

| Проблема | Где |
|---|---|
| SQL-баг: `AND model !=` без значения | `database/repositories/catalog.py:90-91` |
| Нет `__init__.py` нигде | Все пакеты |
| Нет кнопки "Каталог" в меню | `bot/keyboards/menu.py` |
| `test_catalog.py` — заглушка | `tests/test_catalog.py` |
| httpx клиент пересоздаётся на каждый запрос | `integrations/wol_api.py` |

---

## Порядок регистрации роутеров в main.py

```
1. common      — /start, /help, меню
2. tracking    — /tracked, t:, ut:, ph:
3. history     — /history, hd:, r:
4. catalog     — /catalog, /db_table, /db_schema
5. admin       — /admin, /admin_stats, /admin_top_*
6. search      — catch-all текст (ОБЯЗАТЕЛЬНО последний)
```

---

## WOL API endpoints

| Endpoint | Метод | Назначение |
|---|---|---|
| `/health` | GET | Проверка доступности |
| `/status` | GET | Статус сервисов |
| `/api/v1/products/search` | POST | Поиск (structured JSON, не query string) |
| `/api/v1/products/{id}` | GET | Товар по UUID |
| `/api/v1/products/{id}/history` | GET | История цен |
| `/api/v1/raw-posts/{id}` | GET | Оригинальный пост |
| `/api/v1/categories` | GET | Категории и атрибуты |

---

## Время последнего обновления

2026-05-08. Проект ~85% готов. Основной функционал работает.

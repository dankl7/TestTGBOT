# LithTGBot — техническое задание и инструкции для ИИ-разработчика

## START HERE

Перед началом любой работы обязательно прочитай файл `LISTING.md`, если он существует. Этот файл содержит быстрый индекс проекта, схему интеграций, расположение модулей и важные соглашения.

---

## 1. Цель проекта

**LithTGBot** — Telegram-бот для поиска товаров и отслеживания цен, интегрированный с существующей инфраструктурой **Window of Light**.

Бот должен понимать короткие пользовательские запросы, сокращения, русско-английские варианты написания и частые опечатки. Главная задача — быстро показать пользователю актуальные товары из базы Window of Light, дать возможность посмотреть историю цен и подписаться на изменение цены.

---

## 2. Среда выполнения

- **Сервер:** Ubuntu 22.04.05
- **Python:** 3.10.12
- **Основной Telegram framework:** `aiogram 3.x`
- **База данных:** PostgreSQL Window of Light
- **Кэш:** Redis Window of Light
- **Фоновые задачи:** Celery + Celery beat

---

## 3. Главные архитектурные решения

1. Использовать только `aiogram 3.x`.
2. Не использовать `python-telegram-bot`, Telethon, Pyrogram и другие Telegram-фреймворки.
3. Основной поиск товаров выполнять через существующий FastAPI Window of Light: `/api/v1/products/search`.
4. PostgreSQL full-text search находится на стороне Window of Light API. В боте не дублировать сложную поисковую SQL-логику без необходимости.
5. Прямой доступ к PostgreSQL использовать для таблиц самого бота:
   - `tracked_products`
   - `user_search_history`
   - аналитика
   - fallback-операции, если они явно нужны
6. Для интеграции с Window of Light API создать отдельный слой `integrations/wol_api.py`.
7. Все изменения схемы БД делать через Alembic-миграции.
8. Не создавать таблицы вручную в runtime-коде бота.
9. Все секреты читать только из `.env`.
10. В `.env.example` использовать только placeholder-значения, без реальных паролей.
11. Handler-ы Telegram не должны содержать сложную бизнес-логику. Бизнес-логика должна быть в `services/`.
12. SQL-запросы должны быть в `database/repositories/`.
13. HTTP-запросы к Window of Light должны быть только в `integrations/wol_api.py`.
14. Фактический Window of Light API уже поднят на сервере `192.168.1.220:8002`; бот должен быть подстроен под его реальные request/response форматы.
15. Товары в Window of Light будут постоянно пополняться, поэтому бот не должен хардкодить фиксированный список товаров, моделей, цветов и SIM-типов. Все доступные варианты брать из API/БД и `attributes`.
16. Для вывода произвольных данных из БД нужна безопасная read-only оболочка: `CatalogService`/`DbBrowserService`, allowlist таблиц и колонок, параметризованные SELECT-запросы, лимиты выдачи.
17. Никогда не менять существующий проект Window of Light на сервере из кода LithTGBot. Бот только читает данные через API или read-only SQL и создаёт/обновляет только собственные таблицы бота.

---

## 4. Интеграция с Window of Light

Бот использует существующую инфраструктуру Window of Light. Фактический проект на сервере находится в:

- `/home/dankl/my-project/Window of Light/Window of Light`

Фактически проверенная инфраструктура:

| Компонент | Адрес | Комментарий |
|---|---|---|
| Window of Light FastAPI | `http://192.168.1.220:8002` | Внешний URL для LithTGBot |
| PostgreSQL | `192.168.1.144:5432` | БД `window_of_light`, используется WOL API |
| Redis | `192.168.1.144:6379` | Кэш WOL API и кэш бота |

### Основной поток поиска

```text
Пользователь → Telegram Bot → SearchService → Normalizer → WOL request builder → Redis cache бота → Window of Light FastAPI → PostgreSQL
```

### Реальные API endpoints Window of Light

| Endpoint | Метод | Назначение | Кэш WOL |
|---|---|---|---|
| `/health` | GET | Проверка доступности API, DB, Redis, Telegram | нет |
| `/status` | GET | Статус сервисов ingestion/parser | нет |
| `/api/v1/products/search` | POST | Поиск товаров по structured criteria | 5 минут |
| `/api/v1/products/{id}` | GET | Получение товара по UUID | 60 секунд |
| `/api/v1/products/{id}/history` | GET | История цен товара | 5 минут |
| `/api/v1/raw-posts/{id}` | GET | Оригинальный пост | 5 минут |
| `/api/v1/categories` | GET | Активные категории и список атрибутов | 5 минут |

### Реальный формат `/api/v1/products/search`

Window of Light API **не принимает свободную строку `query`**. Бот должен преобразовать пользовательский текст в structured JSON:

```json
{
  "category_id": "smartphones",
  "brand": "Apple",
  "model": "iPhone 17 Pro Max",
  "min_price": null,
  "max_price": null,
  "attributes": {
    "storage": "256GB"
  },
  "limit": 10,
  "offset": 0
}
```

Поддерживаемые поля запроса:

| Поле | Тип | Поведение WOL API |
|---|---|---|
| `category_id` | `str | null` | точное совпадение |
| `brand` | `str | null` | `ILIKE %brand%` |
| `model` | `str | null` | `ILIKE %model%` |
| `min_price` | `float | null` | `price >= min_price` |
| `max_price` | `float | null` | `price <= max_price` |
| `attributes` | `dict | null` | точное сравнение `attributes[key] == value` |
| `limit` | `int` | размер выдачи |
| `offset` | `int` | смещение |

Реальный ответ поиска:

```json
{
  "count": 3,
  "offset": 0,
  "limit": 3,
  "products": [
    {
      "id": "542a0bcc-d157-45e9-b156-e4db3401f3fa",
      "category_id": "smartphones",
      "brand": "Apple",
      "model": "iPhone 17 Pro Max",
      "price": 111000.0,
      "source_channel": "-1001963407298",
      "message_link": "https://t.me/-1001963407298/4203?line=4113576335",
      "timestamp": "2026-01-10T10:52:45+00:00",
      "attributes": {
        "flag": "🇪🇺",
        "color": "White",
        "storage": "256GB",
        "sim_type": "SIM+ESIM"
      },
      "raw_post_id": "c6ef315c-cb9e-4ee8-9560-6a7f082e7fa5"
    }
  ]
}
```

Важно: поле `count` в текущем WOL API — это количество товаров в текущем ответе, а не общее количество всех найденных товаров. Для кнопки `→` использовать стратегию `limit = page_size + 1` или считать, что следующая страница есть, если `count == page_size`.

### Реальные категории и атрибуты

Категории приходят из `/api/v1/categories`. На момент проверки есть:

| `category_id` | Название | Основные атрибуты |
|---|---|---|
| `smartphones` | Смартфоны | `storage`, `ram`, `sim_type`, `flag`, `color` |
| `laptops` | Ноутбуки | `processor`, `ram`, `storage`, `screen_size`, `color` |
| `tablets` | Планшеты | `storage`, `connectivity`, `processor`, `screen_size`, `color` |
| `accessories` | Аксессуары | `type`, `color`, `size`, `model` |
| `consoles` | Игровые приставки | `storage`, `color`, `version` |

### Поведение при недоступности API

Если Window of Light API недоступен:

1. Залогировать ошибку с контекстом.
2. Не падать всем ботом.
3. Показать пользователю короткое сообщение: `Поиск временно недоступен. Попробуйте позже.`
4. Если есть свежий Redis-кэш бота, можно показать кэшированные данные с пометкой, что данные могут быть не самыми свежими.

---

## 5. Технологический стек

| Назначение | Библиотека | Версия/условие |
|---|---|---|
| Telegram bot | `aiogram` | `3.x`, совместимо с Python 3.10 |
| HTTP client | `httpx` | `0.25+` |
| ORM | `SQLAlchemy` | `2.0+`, async API |
| PostgreSQL driver | `asyncpg` | `0.29+` |
| Redis | `redis` | `5.0+`, использовать `redis.asyncio` |
| Background tasks | `celery` | `5.3+` |
| Settings | `pydantic` | `2.5+` |
| Settings env loader | `pydantic-settings` | `2.1+` |
| Migrations | `alembic` | актуальная стабильная версия |
| Tests | `pytest` | `7.4+` |
| Async tests | `pytest-asyncio` | `0.23+` |

---

## 6. Рекомендуемая структура проекта

```text
LithTGBot/
├── bot/
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── common.py          # /start, /help
│   │   ├── search.py          # Поиск товаров
│   │   ├── catalog.py         # Универсальный вывод данных/каталог
│   │   ├── admin.py           # Админ-панель
│   │   ├── tracking.py        # Telegram-обработчики отслеживания
│   │   └── history.py         # История пользователя
│   ├── keyboards/
│   │   ├── __init__.py
│   │   ├── product.py         # Кнопки товара
│   │   ├── menu.py            # Главное меню
│   │   └── history.py         # Кнопки истории
│   ├── middlewares/
│   │   ├── __init__.py
│   │   ├── cleanup.py         # Автоудаление старых сообщений
│   │   └── rate_limit.py      # Rate limit поисковых запросов
│   └── filters/
│       └── __init__.py
├── services/
│   ├── __init__.py
│   ├── normalizer.py          # Нормализация запросов
│   ├── search.py              # Orchestration поиска
│   ├── catalog.py             # Универсальный read-only доступ к данным
│   ├── query_router.py        # Преобразование текста в structured WOL filters
│   ├── tracker.py             # Бизнес-логика отслеживания цен
│   ├── analytics.py           # Популярные запросы и статистика
│   └── cleanup.py             # Управление message_id для автоочистки
├── integrations/
│   ├── __init__.py
│   └── wol_api.py             # HTTP-клиент Window of Light API
├── database/
│   ├── __init__.py
│   ├── session.py             # Async SQLAlchemy engine/session
│   ├── models.py              # SQLAlchemy модели
│   └── repositories/
│       ├── __init__.py
│       ├── tracked.py         # CRUD tracked_products
│       ├── history.py         # CRUD user_search_history
│       └── catalog.py         # Безопасные read-only SELECT для каталога/admin
├── schemas/
│   ├── __init__.py
│   ├── product.py             # ProductDTO
│   ├── search.py              # Search DTO
│   ├── catalog.py             # DTO универсального каталога/табличного вывода
│   └── history.py             # History DTO
├── utils/
│   ├── __init__.py
│   ├── price_formatter.py     # Форматирование цен
│   └── text.py                # Безопасное форматирование текста Telegram
├── tasks/
│   ├── __init__.py
│   ├── celery.py              # Celery app
│   └── price_tracking.py      # Periodic-задача проверки цен
├── migrations/                # Alembic migrations
├── tests/
│   ├── test_normalizer.py
│   ├── test_price_formatter.py
│   ├── test_rate_limit.py
│   ├── test_history.py
│   └── test_tracking.py
├── config.py                  # Pydantic Settings
├── main.py                    # Точка входа бота
├── requirements.txt
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── CLAUDE.md
└── LISTING.md
```

Важно: в проекте использовать единое именование:

- `services/tracker.py` — бизнес-логика отслеживания цен.
- `bot/handlers/tracking.py` — Telegram handlers для отслеживания.

---

## 7. Конфигурация

### `.env.example`

В `.env.example` должны быть только placeholders.

```bash
# Telegram
TELEGRAM_BOT_TOKEN=change_me
TELEGRAM_PROXY_HOST=181.177.82.65
TELEGRAM_PROXY_PORT=8000
TELEGRAM_PROXY_USER=user
TELEGRAM_PROXY_PASS=pass
TELEGRAM_PROXY_TYPE=HTTP

# Window of Light API
WOL_API_BASE_URL=http://192.168.1.220:8002
WOL_API_TIMEOUT_SECONDS=10

# Database
DB_HOST=192.168.1.144
DB_PORT=5432
DB_NAME=window_of_light
DB_USER=wol_user
DB_PASSWORD=change_me
DB_READONLY_MODE=true

# Redis
REDIS_HOST=192.168.1.144
REDIS_PORT=6379
REDIS_DB=0

# Celery
CELERY_BROKER_URL=redis://192.168.1.144:6379/0
CELERY_RESULT_BACKEND=redis://192.168.1.144:6379/1

# Admin
ADMIN_USER_IDS=123456789,987654321

# Rate limiting
RATE_LIMIT_PER_MINUTE=10

# Search
SEARCH_PAGE_SIZE=10
SEARCH_CACHE_TTL_SECONDS=300

# Cleanup
MAX_SEARCH_MESSAGES_PER_CHAT=3

# Catalog / DB browser
CATALOG_MAX_ROWS=20
DB_BROWSER_ADMIN_ONLY=true
```

Не нужны `TELEGRAM_API_ID` и `TELEGRAM_API_HASH`, потому что бот работает через Telegram Bot API и `aiogram`, а не через MTProto.

### `config.py`

Требования:

1. Использовать `pydantic-settings`.
2. Парсить `ADMIN_USER_IDS` в `set[int]` или `list[int]`.
3. Не хардкодить секреты.
4. Валидировать обязательные поля при старте приложения.

---

## 8. База данных

Бот использует существующие таблицы Window of Light. Фактическая схема БД проверена через read-only introspection.

| Таблица | Назначение | Важные поля |
|---|---|---|
| `products` | Товары | `id UUID`, `category_id`, `brand`, `model`, `price NUMERIC(12,2)`, `source_channel`, `message_link`, `raw_post_id`, `attributes JSONB`, `timestamp`, `storage`, `ram`, `color`, `sim_type`, `screen_size`, `chip`, `connectivity`, `country_flag`, `sku` |
| `raw_posts` | Оригинальные Telegram-посты | `id UUID`, `channel_id`, `message_id`, `post_id`, `text`, `message_link`, `date`, `parsed_count`, `is_processed` |
| `price_history` | История цен | `id UUID`, `product_id UUID`, `price NUMERIC(12,2)`, `timestamp`, `source_channel` |
| `categories` | Категории | `id VARCHAR`, `name`, `parent_id`, `attributes JSONB`, `keywords JSONB`, `is_active` |
| `channels` | Мониторируемые каналы WOL | `id UUID`, `channel_id`, `username`, `title`, `is_active`, `last_message_id` |
| `api_keys` | API ключи WOL | Не использовать и не показывать в боте |

Фактические связи:

```text
categories.id ← products.category_id
raw_posts.id ← products.raw_post_id
products.id ← price_history.product_id
```

На момент проверки в БД было: `categories=5`, `raw_posts=115`, `products=1822`, `price_history=0`. Эти значения информационные и будут меняться, потому что товары пополняются.

Бот добавляет собственные таблицы в ту же БД.

### `tracked_products`

```sql
CREATE TABLE tracked_products (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    last_seen_price NUMERIC(12, 2),
    last_notified_price NUMERIC(12, 2),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, product_id)
);

CREATE INDEX idx_tracked_products_user_id ON tracked_products(user_id);
CREATE INDEX idx_tracked_products_product_id ON tracked_products(product_id);
CREATE INDEX idx_tracked_products_active ON tracked_products(is_active);
```

### `user_search_history`

```sql
CREATE TABLE user_search_history (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    query VARCHAR(500) NOT NULL,
    normalized_query VARCHAR(500),
    product_id UUID REFERENCES products(id) ON DELETE SET NULL,
    final_price NUMERIC(12, 2),
    results_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_search_history_user_created
ON user_search_history(user_id, created_at DESC);

CREATE INDEX idx_user_search_history_query_created
ON user_search_history(query, created_at DESC);

CREATE INDEX idx_user_search_history_product_id
ON user_search_history(product_id);

CREATE INDEX idx_user_search_history_query_count
ON user_search_history(query, results_count DESC);
```

### Правила миграций

1. Использовать Alembic.
2. Не создавать таблицы через `Base.metadata.create_all()` в production runtime LithTGBot.
3. Миграции должны быть идемпотентными с точки зрения повторного применения Alembic.
4. Если существующие таблицы Window of Light уже есть, не пытаться пересоздавать их.
5. Не изменять существующие таблицы Window of Light (`products`, `raw_posts`, `price_history`, `categories`, `channels`, `api_keys`) без отдельного согласования.
6. В SQLAlchemy не называть атрибут модели `metadata`, потому что это служебное имя Declarative Base. Для колонки `metadata` использовать Python-атрибут `metadata_json = Column("metadata", JSONB, ...)`.

### Универсальная read-only оболочка для данных из БД

Так как товары постоянно пополняются, LithTGBot должен иметь универсальную оболочку для вывода данных, а не только жёстко заданный поиск iPhone/Samsung.

Обязательные компоненты:

| Компонент | Назначение |
|---|---|
| `services/catalog.py` | Универсальный read-only сервис каталога и табличной выдачи |
| `services/query_router.py` | Разбор пользовательского текста в structured filters для WOL API |
| `database/repositories/catalog.py` | Безопасные read-only SELECT-запросы к allowlist таблицам |
| `bot/handlers/catalog.py` | Команды/кнопки просмотра категорий, фильтров и табличных данных |
| `schemas/catalog.py` | DTO для таблиц, строк, фильтров, facets |

Правила безопасности:

1. Обычный пользователь не получает доступ к произвольному SQL.
2. Обычный пользователь может искать и просматривать только товарные данные: `products`, связанные `raw_posts`, `price_history`, `categories`.
3. Админ может использовать DB browser, но только через allowlist таблиц и колонок.
4. Таблица `api_keys` запрещена к выводу всегда.
5. Запрещены любые `INSERT`, `UPDATE`, `DELETE`, `ALTER`, `DROP`, `TRUNCATE`.
6. Все SELECT-запросы должны быть параметризованы.
7. Каждый запрос обязан иметь `LIMIT`; максимум задаётся `CATALOG_MAX_ROWS`, по умолчанию 20.
8. Для длинных значений (`raw_posts.text`) показывать краткий preview и кнопку/команду для полного просмотра только админам или через карточку оригинала.
9. Логировать `user_id`, `table`, `filters`, `limit`, но не логировать секреты и не выводить `api_keys`.

Пользовательские сценарии:

| Сценарий | Команда/текст | Поведение |
|---|---|---|
| Список категорий | `/catalog` | Показать категории из `/api/v1/categories` |
| Последние товары | `последние товары` | Показать последние товары по `timestamp DESC` |
| Фильтр по категории | `смартфоны 256GB` | `category_id=smartphones`, `attributes.storage=256GB` |
| Фильтр по цене | `айфон до 90000` | `max_price=90000` |
| Админ-таблица | `/db_table products` | Read-only вывод allowlist колонок |
| Админ-схема | `/db_schema products` | Показать колонки и типы |

---

## 9. Внутренние DTO/схемы

Для стабильности между слоями проекта использовать DTO.

### `ProductDTO`

Поля:

- `id: UUID | str`
- `title: str`
- `brand: str | None`
- `model: str | None`
- `price: int | float | Decimal | None`
- `currency: str = "RUB"`
- `attributes: dict`
- `raw_post_id: UUID | str | None`
- `message_link: str | None`
- `updated_at: datetime | None`

### `SearchResultDTO`

Поля:

- `query: str`
- `normalized_query: str`
- `items: list[ProductDTO]`
- `total: int`
- `page: int`
- `page_size: int`

### `PriceHistoryItemDTO`

Поля:

- `product_id: UUID | str`
- `price: int`
- `timestamp: datetime`

---

## 10. Умный поиск и нормализация

### Цель

Пользователь может написать короткий запрос, например:

- `17 PM 256`
- `iphoe 16`
- `айфон 15 про макс 256`
- `s24 ultra 512`
- `mba 512`

Бот должен превратить это в понятный поисковый запрос и найти товары.

### Этапы нормализации

1. Trim строки.
2. Lowercase для анализа.
3. Замена `ё` на `е`.
4. Удаление лишних пробелов.
5. Нормализация русских слов.
6. Нормализация памяти.
7. Раскрытие сокращений.
8. Fuzzy matching для брендов и моделей.
9. Генерация `normalized_query`.
10. Возврат диагностической информации.

### Русские слова

| Вход | Нормализация |
|---|---|
| `айфон` | `iPhone` |
| `самсунг` | `Samsung` |
| `макбук` | `MacBook` |
| `айпад` | `iPad` |
| `про` | `Pro` |
| `про макс` | `Pro Max` |
| `ультра` | `Ultra` |
| `эйр` | `Air` |
| `мини` | `Mini` |

### iPhone сокращения

| Сокращение | Полный текст |
|---|---|
| `17 PM` | `iPhone 17 Pro Max` |
| `17 P` | `iPhone 17 Pro` |
| `17` | `iPhone 17` |
| `16 PM` | `iPhone 16 Pro Max` |
| `16 P` | `iPhone 16 Pro` |
| `16` | `iPhone 16` |
| `15 PM` | `iPhone 15 Pro Max` |
| `15 P` | `iPhone 15 Pro` |
| `15` | `iPhone 15` |
| `SE3` | `iPhone SE 3` |
| `SE2` | `iPhone SE 2` |
| `SE` | `iPhone SE` |

### Samsung сокращения

| Сокращение | Полный текст |
|---|---|
| `S24 Ultra` | `Samsung Galaxy S24 Ultra` |
| `S24+` | `Samsung Galaxy S24+` |
| `S24` | `Samsung Galaxy S24` |
| `Z Fold` | `Samsung Galaxy Z Fold` |
| `Z Flip` | `Samsung Galaxy Z Flip` |
| `A56` | `Samsung Galaxy A56` |
| `A36` | `Samsung Galaxy A36` |

### MacBook сокращения

| Сокращение | Полный текст |
|---|---|
| `MBA` | `MacBook Air` |
| `MBP` | `MacBook Pro` |
| `MB` | `MacBook` |

### iPad сокращения

| Сокращение | Полный текст |
|---|---|
| `iPad Pro` | `iPad Pro` |
| `iPad Air` | `iPad Air` |
| `iPad Mini` | `iPad Mini` |

### Память

| Вход | Нормализация |
|---|---|
| `128` | `128GB` |
| `256` | `256GB` |
| `512` | `512GB` |
| `128g` | `128GB` |
| `256g` | `256GB` |
| `512g` | `512GB` |
| `128gb` | `128GB` |
| `256gb` | `256GB` |
| `512gb` | `512GB` |
| `128гб` | `128GB` |
| `256гб` | `256GB` |
| `512гб` | `512GB` |
| `1t` | `1TB` |
| `1tb` | `1TB` |
| `1тб` | `1TB` |

### Порядок раскрытия сокращений

Сначала раскрывать длинные сокращения, потом короткие:

1. `17 PM` раньше `17 P`.
2. `17 P` раньше `17`.
3. `S24 Ultra` раньше `S24`.
4. `SE3` и `SE2` раньше `SE`.
5. `MBA` и `MBP` раньше `MB`.

### Fuzzy matching

Требования:

1. Использовать расстояние Левенштейна или близкий алгоритм.
2. Допуск для коротких слов — не более 1 ошибки.
3. Для слов длиннее 5 символов — не более 2 ошибок.
4. Исправлять бренды и модели:
   - `iphoe` → `iPhone`
   - `iphon` → `iPhone`
   - `samsng` → `Samsung`
   - `macbok` → `MacBook`
5. Не применять fuzzy matching к ценам.
6. Не исправлять числа агрессивно.

### Защита от ложной нормализации iPhone

Числа `15`, `16`, `17` раскрывать в iPhone-модель только если:

1. Запрос состоит только из модели/памяти, например `17 256`.
2. Или рядом есть признаки Apple/iPhone:
   - `p`
   - `pm`
   - `pro`
   - `max`
   - `iphone`
   - `айфон`
   - объём памяти
   - цвет
   - `sim`
   - `esim`

Это нужно, чтобы запросы вроде `17 чехол` не превращались ошибочно в `iPhone 17`.

### Результат нормализации

`Normalizer` должен возвращать не просто строку, а структуру:

- `original_query`
- `normalized_query`
- `tokens`
- `applied_replacements`
- `confidence`

Пример:

```json
{
  "original_query": "17 PM 256",
  "normalized_query": "iPhone 17 Pro Max 256GB",
  "tokens": ["17", "PM", "256"],
  "applied_replacements": [
    {"from": "17 PM", "to": "iPhone 17 Pro Max"},
    {"from": "256", "to": "256GB"}
  ],
  "confidence": 0.98
}
```

---

## 11. Поиск товаров

### Процесс

1. Handler получает текст пользователя.
2. Проверяет, что это не команда.
3. Проверяет rate limit.
4. Вызывает `Normalizer`.
5. Получает `normalized_query` и диагностические признаки: категория, бренд, модель, память, цвет, SIM-тип, цена.
6. `QueryRouter`/`SearchService` преобразует нормализованный текст в реальный `ProductSearchRequest` Window of Light.
7. Проверяет Redis cache бота.
8. Если cache miss — вызывает Window of Light API `/api/v1/products/search`.
9. Сохраняет результат в Redis на 5 минут.
10. Сохраняет запись в `user_search_history`.
11. Отправляет пользователю первую страницу результатов.
12. Регистрирует `message_id` для автоочистки.

### Маппинг запроса в WOL API

Примеры:

| Пользовательский запрос | WOL request |
|---|---|
| `17 PM 256` | `category_id=smartphones`, `brand=Apple`, `model=iPhone 17 Pro Max`, `attributes.storage=256GB` |
| `s24 ultra 512` | `category_id=smartphones`, `brand=Samsung`, `model=Samsung Galaxy S24 Ultra`, `attributes.storage=512GB` |
| `mba m3 512` | `category_id=laptops`, `brand=Apple`, `model=MacBook Air`, `attributes.processor=M3`, `attributes.storage=512GB` |
| `ipad pro 11 256 cellular` | `category_id=tablets`, `brand=Apple`, `model=iPad Pro`, `attributes.screen_size=11`, `attributes.storage=256GB`, `attributes.connectivity=Cellular` |

Важно: `attributes` в WOL API сравниваются точно как строки. Поэтому нормализатор должен приводить значения к формату, который реально хранится в БД: `256GB`, `1TB`, `SIM+ESIM`, `ESIM`, `White`, `Black`, `M3` и т.д.

### Пагинация

- Размер страницы: 10 товаров.
- WOL API не возвращает общее количество всех результатов.
- Для определения наличия следующей страницы запрашивать `limit = page_size + 1` и показывать пользователю только первые `page_size` элементов.
- `offset = page * page_size`.
- Кнопки:
  - `←`
  - `стр. N`
  - `→`
- При пагинации не выполнять новый поиск, если данные есть в Redis.
- Если Redis недоступен, можно повторить запрос к API.

### Ранжирование результатов

Если ранжирование выполняется на стороне бота, использовать приоритеты:

1. Точное совпадение модели и памяти.
2. Совпадение бренда.
3. Совпадение модели.
4. Наличие нужного объёма памяти.
5. Более свежие товары выше старых.
6. При равной релевантности — цена по возрастанию.

### Цвета и SIM-типы

Нормализация не должна искусственно добавлять все цвета и SIM-типы в текст запроса.

Правильная логика:

1. Для `17 PM 256` искать `iPhone 17 Pro Max 256GB`.
2. Все цвета, флаги стран и SIM-типы брать из найденных товаров и их `attributes`.
3. Если пользователь явно указал цвет или SIM-тип — использовать это как фильтр.

---

## 12. Redis

Использовать Redis для кэша, rate limit, коротких callback tokens и автоочистки.

| Назначение | Ключ | TTL |
|---|---|---|
| Search cache | `search:{query_hash}:{page}` | 300 секунд |
| Query token | `query_token:{token}` | 1800 секунд |
| Product short id | `product_short:{short_id}` | 86400 секунд |
| Rate limit | `rate:{user_id}:{minute}` | 60 секунд |
| Cleanup messages | `cleanup:{chat_id}` | 86400 секунд |

Если Redis недоступен:

1. Логировать ошибку.
2. Продолжить работу без кэша.
3. Для rate limit использовать in-memory fallback или временно отключить лимит.
4. Не падать всем ботом.

---

## 13. Rate limiting

Лимит: **10 поисковых запросов в минуту на пользователя**.

Rate limit применяется к:

- обычным текстовым поисковым запросам.

Rate limit не применяется к:

- `/start`
- `/help`
- `/history`
- `/tracked`
- `/catalog`
- `/admin`
- callback-кнопкам пагинации
- callback-кнопкам товара

При превышении лимита показать:

```text
Слишком много запросов. Попробуйте через N секунд.
```

---

## 14. Telegram интерфейс

### `/start`

Команда должна:

1. Кратко объяснить, что умеет бот.
2. Показать примеры запросов:
   - `17 PM 256`
   - `S24 Ultra`
   - `MBA M3 512`
3. Показать главное меню.

### `/help`

Команда должна объяснять:

1. Как искать товары.
2. Какие сокращения поддерживаются.
3. Как отслеживать цену.
4. Как смотреть историю.

### Главное меню

Кнопки:

- `🔎 Поиск`
- `🗂 Каталог`
- `📜 История`
- `🔔 Отслеживаемые`
- `ℹ️ Помощь`

### Формат результата поиска

Пример:

```text
🔎 iPhone 17 Pro Max 256GB
Найдено: 24

1. iPhone 17 Pro Max 256GB White eSIM — 89 900 ₽
2. iPhone 17 Pro Max 256GB Black physical — 104 900 ₽
3. iPhone 17 Pro Max 256GB Natural SIM+eSIM — 111 000 ₽
```

### Inline-клавиатура товара

```text
[📊 История цен] [🔔 Отслеживать] [📄 Оригинал]
[← Назад]
```

---

## 15. Callback data

Telegram ограничивает `callback_data` 64 байтами.

Запрещено помещать в `callback_data`:

- полный поисковый запрос;
- длинный JSON;
- длинный UUID вместе с большим количеством параметров.

Использовать короткие callback-и:

| Действие | Формат |
|---|---|
| Поиск, страница | `s:{token}:{page}` |
| Товар | `p:{short_id}` |
| Отслеживать | `t:{short_id}` |
| История цен | `ph:{short_id}` |
| Оригинал | `o:{short_id}` |
| Повторить запрос | `r:{history_id}` |
| Удалить историю | `hd:{history_id}` |
| Отключить отслеживание | `ut:{tracked_id}` |

Полные значения хранить в Redis:

- `query_token:{token}` → полный запрос и параметры поиска.
- `product_short:{short_id}` → полный UUID товара.

---

## 16. Форматирование цены

Файл: `utils/price_formatter.py`.

Требования:

| Вход | Выход |
|---|---|
| `79990` | `79 990 ₽` |
| `0` | `0 ₽` |
| `None` | `Цена не указана` |

Цены форматировать с пробелами между тысячами.

---

## 17. Автоочистка сообщений

Цель: в чате должно оставаться не более 3 последних сообщений бота с результатами поиска.

Правила:

1. Для каждого `chat_id` хранить список `message_id` в Redis.
2. После отправки нового результата добавлять его `message_id` в список.
3. Если сообщений больше 3 — удалять самые старые.
4. Ошибки удаления не должны ломать сценарий.
5. Не удалять пользовательские сообщения, если это явно не указано.
6. Не удалять системные сообщения `/start`, `/help`, `/admin`.
7. Handler-ы, отправляющие результаты поиска, должны явно регистрировать отправленный `message_id` в `CleanupService`.
8. Middleware может выполнять предварительную очистку, но сохранение новых сообщений лучше делать после успешной отправки/редактирования.

Не использовать несуществующий параметр `delete_webhook_preview`. Если нужно отключить превью ссылок, использовать корректные возможности `aiogram 3.x` для link preview или выносить ссылки в inline-кнопки.

---

## 18. История пользователя

Команда: `/history`.

Функционал:

1. Показать последние 20 поисковых запросов пользователя.
2. Для каждого элемента показывать актуальную цену на момент просмотра.
3. Дать кнопку `Повторить`.
4. Дать кнопку `Удалить`.

При каждом успешном поиске сохранять:

- `user_id`
- `query`
- `normalized_query`
- `results_count`
- `product_id`, если пользователь открыл или выбрал конкретный товар
- `final_price`, если товар был выбран
- `created_at`

Важно: в истории показывать актуальную цену на момент просмотра, а не только сохранённую `final_price`.

Если товар удалён или недоступен:

- показать запрос;
- вместо цены написать `товар недоступен`;
- оставить возможность повторить запрос.

Пример формата:

```text
📜 История поиска
━━━━━━━━━━━━━━━━━━━━━━
1. iPhone 17 Pro Max 256GB
   89 990 ₽ (акт.) • 25.04.2026
   [Повторить] [Удалить]

2. Samsung S24 Ultra
   74 990 ₽ (акт.) • 24.04.2026
   [Повторить] [Удалить]
```

---

## 19. Отслеживание цен

### Команды и кнопки

- Кнопка `🔔 Отслеживать` добавляет товар в `tracked_products`.
- Команда `/tracked` показывает активные отслеживания.
- Кнопка `Отключить` деактивирует отслеживание.
- Кнопка `📊 История цен` показывает текстовую сводку истории цен.

### Логика добавления

1. Пользователь нажимает `🔔 Отслеживать`.
2. Бот получает актуальную цену товара.
3. Создаёт запись в `tracked_products`.
4. Сохраняет текущую цену в `last_seen_price`.
5. Если запись уже есть и активна — показать, что товар уже отслеживается.
6. Если запись есть, но `is_active = false` — активировать её снова.

### Celery beat

Периодичность: каждый день в 10:00.

Процесс:

1. Получить все активные отслеживания.
2. Для каждого товара получить актуальную цену через Window of Light API или БД.
3. Сравнить цену с `last_seen_price`.
4. Если цена изменилась:
   - отправить уведомление пользователю;
   - обновить `last_seen_price`;
   - обновить `last_notified_price`;
   - записать изменение в `price_history`, если это ответственность бота.
5. Если цена не изменилась — ничего не отправлять.

Важно: «уведомления при любом изменении цены» означает любое изменение, обнаруженное при очередной проверке. Если проверка выполняется раз в день, бот не узнаёт об изменениях между проверками мгновенно.

### Celery и async

Celery task может быть синхронной функцией-обёрткой.

Внутри неё разрешено запускать async-код через `asyncio.run(...)`.

Бизнес-логика должна оставаться в async-сервисах.

Примерная схема:

1. `tasks/price_tracking.py` содержит Celery task.
2. Celery task вызывает `asyncio.run(run_price_tracking())`.
3. `run_price_tracking()` использует async repositories, async API client и `aiogram.Bot`.

---

## 20. История цен

Кнопка: `📊 История цен`.

Правила:

1. По умолчанию показывать последние 7 дней.
2. Если записей за 7 дней нет — показать последние доступные записи.
3. По запросу можно показать всю доступную историю.
4. Процент изменения считать относительно предыдущей записи.
5. Если предыдущей записи нет — процент не показывать.
6. Внизу показывать минимум и максимум за период.

Формат:

```text
📊 История цен: iPhone 16 Pro 256GB
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 28.04 — 94 990 ₽ (↓ -5.2%)
📅 25.04 — 99 990 ₽ (→ без изменений)
📅 22.04 — 99 990 ₽ (↑ +3.1%)
📅 19.04 — 96 990 ₽

Мин: 89 990 ₽  |  Макс: 104 990 ₽
```

Обозначения:

- `↑ +3.1%` — цена выросла.
- `↓ -5.2%` — цена упала.
- `→ без изменений` — цена не изменилась.

Если истории нет, показать:

```text
История цен пока отсутствует.
Текущая цена: 89 990 ₽
```

---

## 21. Админ-панель

Команда: `/admin`.

Доступ только для пользователей из `ADMIN_USER_IDS`.

Если пользователь не админ:

```text
Недостаточно прав.
```

Функции:

- топ-10 запросов за день;
- топ-10 запросов за неделю;
- топ-10 запросов за месяц;
- количество уникальных пользователей;
- количество поисковых запросов;
- количество отслеживаемых товаров;
- количество активных отслеживаний.

Рекомендуемые команды:

| Команда | Назначение |
|---|---|
| `/admin` | Главное меню админа |
| `/admin_stats` | Краткая статистика |
| `/admin_top_day` | Топ запросов за день |
| `/admin_top_week` | Топ запросов за неделю |
| `/admin_top_month` | Топ запросов за месяц |

---

## 22. Обработка ошибок

Все ошибки логировать через `logging`.

Пользователю показывать короткие понятные сообщения.

| Ситуация | Ответ пользователю |
|---|---|
| PostgreSQL недоступен | `База временно недоступна. Попробуйте позже.` |
| Window of Light API недоступен | `Поиск временно недоступен. Попробуйте позже.` |
| Redis недоступен | Пользователю не показывать, продолжить без кэша |
| Товар не найден | `Ничего не найдено. Попробуйте изменить запрос.` |
| Истории цен нет | `История цен пока отсутствует.` |
| Товар удалён | `Товар больше не доступен.` |
| Ошибка удаления Telegram-сообщения | Логировать warning, не показывать пользователю |

Логи должны содержать контекст, если он есть:

- `user_id`
- `chat_id`
- `query`
- `normalized_query`
- `product_id`
- `callback_data`

---

## 23. Безопасность

1. Telegram token только в `.env`.
2. DB password только в `.env`.
3. Admin IDs только в `.env`.
4. Не логировать секреты.
5. Не хранить реальные пароли в `.env.example`, `CLAUDE.md`, `LISTING.md`, README или тестах.
6. Callback-и должны проверять пользователя, если действие относится к личной истории или личным отслеживаниям.
7. Админ-команды должны проверять `ADMIN_USER_IDS`.

---

## 24. Требования к коду

1. Все I/O операции должны быть async, где это поддерживается библиотеками.
2. Использовать `async def` / `await` для Telegram, HTTP, DB, Redis.
3. Все публичные функции должны иметь type hints.
4. Основные сервисы должны иметь русские docstrings.
5. Handler-ы не должны содержать сложную бизнес-логику.
6. SQL-запросы должны быть в repositories.
7. HTTP-запросы к Window of Light должны быть только в `integrations/wol_api.py`.
8. Нельзя хардкодить токены, пароли и admin IDs.
9. Нельзя падать всем ботом при ошибке одного пользовательского запроса.
10. Сложные функции должны быть покрыты тестами.
11. Форматирование текста Telegram должно учитывать Markdown/HTML escaping, если используется parse mode.

---

## 25. Минимальные тесты

### `tests/test_normalizer.py`

Проверить:

- `17 PM 256` → `iPhone 17 Pro Max 256GB`
- `16 P 512` → `iPhone 16 Pro 512GB`
- `iphoe 16` → `iPhone 16`
- `айфон 15 про макс 256` → `iPhone 15 Pro Max 256GB`
- `s24 ultra 512` → `Samsung Galaxy S24 Ultra 512GB`
- `mba 512` → `MacBook Air 512GB`
- `17 чехол` не должен автоматически превращаться в `iPhone 17`, если нет признаков поиска телефона.

### `tests/test_price_formatter.py`

Проверить:

- `79990` → `79 990 ₽`
- `0` → `0 ₽`
- `None` → `Цена не указана`

### `tests/test_rate_limit.py`

Проверить:

- первые 10 запросов разрешены;
- 11-й запрос заблокирован;
- после TTL запрос снова разрешён.

### `tests/test_history.py`

Проверить:

- история сортируется от новой к старой;
- показывается актуальная цена, а не старая `final_price`;
- удаление записи работает;
- повтор запроса работает.

### `tests/test_catalog.py`

Проверить:

- `/catalog` получает категории из WOL API;
- read-only repository строит только параметризованные `SELECT`;
- allowlist запрещает таблицу `api_keys`;
- каждый запрос имеет `LIMIT`;
- длинные поля вроде `raw_posts.text` обрезаются до preview;
- обычный пользователь не может вызвать админский `/db_table`.

### `tests/test_tracking.py`

Проверить:

- добавление товара в отслеживание;
- повторное добавление не создаёт дубль;
- отключение отслеживания;
- изменение цены создаёт уведомление;
- отсутствие изменения цены не создаёт уведомление.

---

## 26. Запуск

### Docker Compose

```bash
docker-compose up -d
```

### Вручную

```bash
pip install -r requirements.txt
alembic upgrade head
celery -A tasks.celery worker -l info
celery -A tasks.celery beat -l info
python main.py
```

---

## 27. Проверка функциональности

### Тестовые сценарии

1. **Поиск со сокращением**
   - Отправить `17 PM 256`.
   - Ожидание: товары `iPhone 17 Pro Max 256GB` со всеми найденными цветами и SIM-типами.

2. **Поиск с опечаткой**
   - Отправить `iphoe 16`.
   - Ожидание: исправление на `iPhone 16`.

3. **Добавление в отслеживание**
   - Нажать `🔔 Отслеживать`.
   - Ожидание: подтверждение.

4. **Просмотр истории цен**
   - Нажать `📊 История цен`.
   - Ожидание: текстовая сводка.

5. **Проверка автоочистки**
   - Сделать 4 поисковых запроса подряд.
   - Ожидание: в чате осталось максимум 3 сообщения бота с результатами поиска.

6. **История с актуальной ценой**
   - Отправить `/history`.
   - Ожидание: показаны актуальные цены.

7. **Rate limit**
   - Отправить 11 поисковых запросов за минуту.
   - Ожидание: 11-й запрос заблокирован.

8. **Каталог и read-only оболочка**
   - Отправить `/catalog`.
   - Ожидание: показаны актуальные категории из `/api/v1/categories`.
   - Отправить `последние товары`.
   - Ожидание: показаны последние товары без хардкода моделей.
   - Отправить `/db_table products` от админа.
   - Ожидание: показана allowlist-таблица с лимитом.
   - Отправить `/db_table api_keys` от админа.
   - Ожидание: доступ запрещён.

9. **Админ-панель**
   - Отправить `/admin` от админа.
   - Ожидание: меню статистики.
   - Отправить `/admin` не от админа.
   - Ожидание: `Недостаточно прав.`

---

## 28. Acceptance criteria

Проект считается готовым, если:

1. Бот запускается командой `python main.py`.
2. `/start` и `/help` работают.
3. Запрос `17 PM 256` возвращает товары `iPhone 17 Pro Max 256GB`.
4. Запрос `iphoe 16` исправляется до `iPhone 16`.
5. Поиск кэшируется в Redis.
6. Rate limit блокирует 11-й поисковый запрос за минуту.
7. Пагинация работает.
8. Кнопка `🔔 Отслеживать` добавляет товар в отслеживание.
9. `/tracked` показывает отслеживаемые товары.
10. Celery-задача проверяет цены.
11. При изменении цены пользователь получает уведомление.
12. `/history` показывает последние запросы с актуальными ценами.
13. Кнопка `📊 История цен` показывает текстовую историю цен.
14. `/catalog` показывает актуальные категории и позволяет просматривать пополняемый каталог без хардкода товаров.
15. Админская read-only оболочка может показать allowlist таблицы/колонки БД с лимитами и без произвольного SQL.
16. `/admin` доступен только администраторам.
17. Старые поисковые сообщения удаляются, остаётся максимум 3.
18. Все минимальные тесты проходят.
19. Секреты не захардкожены.
20. Есть Alembic-миграции для новых таблиц.
21. Основные сервисы имеют type hints и русские docstrings.
22. Ошибки БД/API/Redis логируются и не роняют весь бот.

---

## 29. Критические требования

- [ ] Использовать только `aiogram 3.x`.
- [ ] Асинхронность для Telegram, DB, HTTP, Redis.
- [ ] Обработка ошибок с логированием.
- [ ] Rate limiting: 10 поисковых запросов в минуту.
- [ ] Normalizer сокращений RU/EN.
- [ ] Fuzzy matching для опечаток.
- [ ] Защита от ложной нормализации коротких чисел.
- [ ] Поиск через реальный Window of Light API `http://192.168.1.220:8002`.
- [ ] Преобразование свободного текста в structured `ProductSearchRequest`.
- [ ] Универсальная read-only оболочка для пополняемого каталога и безопасного вывода данных из БД.
- [ ] Redis-кэш поиска.
- [ ] Пагинация по 10 товаров.
- [ ] Показ всех найденных цветов и SIM-типов из результатов.
- [ ] Автоудаление старых сообщений.
- [ ] Актуальные цены в истории.
- [ ] Отслеживание цены через Celery beat.
- [ ] Уведомления при обнаруженном изменении цены.
- [ ] Админ-панель с защитой по `ADMIN_USER_IDS`.
- [ ] Unit-тесты.
- [ ] Тесты read-only каталога/DB browser.
- [ ] Alembic-миграции.
- [ ] Docstrings на русском.
- [ ] Type hints.

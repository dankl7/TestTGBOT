# LithTGBot — индекс данных и быстрый справочник

## START HERE

Перед началом работы с проектом прочитай этот файл. Он содержит быстрый индекс модулей, таблиц, интеграций и основных соглашений. Подробное техническое задание находится в `CLAUDE.md`.

---

## 1. Назначение проекта

**LithTGBot** — Telegram-бот для поиска товаров и отслеживания цен из инфраструктуры **Window of Light**.

Основные возможности:

- умный поиск по коротким запросам;
- понимание RU/EN сокращений;
- исправление частых опечаток;
- поиск товаров через Window of Light FastAPI;
- Redis-кэширование;
- история пользовательских запросов;
- отслеживание цен;
- уведомления при изменении цены;
- админ-статистика.

---

## 2. Ключевые правила проекта

1. Telegram framework: только `aiogram 3.x`.
2. Не использовать `python-telegram-bot`, Telethon, Pyrogram.
3. Основной поиск товаров: через реальный Window of Light API `/api/v1/products/search` на `http://192.168.1.220:8002`.
4. Window of Light API не принимает свободную строку `query`; пользовательский текст нужно преобразовывать в structured filters.
5. Прямой доступ к PostgreSQL: только для таблиц бота, read-only оболочки каталога и вспомогательных операций.
6. Все новые таблицы создавать через Alembic.
7. Все секреты хранить только в `.env`.
8. В `.env.example` использовать только placeholder-значения.
9. Длинные данные не хранить в Telegram `callback_data`; использовать Redis tokens.
10. Handler-ы не должны содержать сложную бизнес-логику.
11. Все I/O операции делать async, где это поддерживается.
12. Существующий проект Window of Light на сервере не менять из LithTGBot.

---

## 3. Инфраструктура Window of Light

| Компонент | Адрес | Назначение |
|---|---|---|
| PostgreSQL | `192.168.1.144:5432` | БД `window_of_light`, товары WOL и таблицы бота |
| Redis | `192.168.1.144:6379` | Кэш WOL API, кэш бота, rate limit, callback tokens, cleanup |
| FastAPI | `http://192.168.1.220:8002` | Фактический внешний API поиска и получения товаров |

Фактический проект Window of Light на сервере:

- `/home/dankl/my-project/Window of Light/Window of Light`

---

## 4. API Endpoints Window of Light

| Endpoint | Метод | Описание | Используется для | Кэш WOL |
|---|---|---|---|---|
| `/health` | GET | Статус API, DB, Redis, Telegram | Проверка доступности | нет |
| `/status` | GET | Статус ingestion/parser | Диагностика | нет |
| `/api/v1/products/search` | POST | Structured-поиск товаров | Основной поиск в боте | 5 мин |
| `/api/v1/products/{id}` | GET | Товар по UUID | Детали, актуальная цена | 60 сек |
| `/api/v1/products/{id}/history` | GET | История цен | Текстовая сводка цен | 5 мин |
| `/api/v1/raw-posts/{id}` | GET | Оригинальный пост | Кнопка `📄 Оригинал` | 5 мин |
| `/api/v1/categories` | GET | Активные категории и атрибуты | Каталог, QueryRouter | 5 мин |

### Формат `/api/v1/products/search`

WOL API принимает structured JSON, не свободную строку:

```json
{
  "category_id": "smartphones",
  "brand": "Apple",
  "model": "iPhone 17 Pro Max",
  "min_price": null,
  "max_price": null,
  "attributes": {"storage": "256GB"},
  "limit": 10,
  "offset": 0
}
```

Фильтры:

| Поле | Поведение |
|---|---|
| `category_id` | точное совпадение |
| `brand` | `ILIKE %brand%` |
| `model` | `ILIKE %model%` |
| `min_price` | `price >= min_price` |
| `max_price` | `price <= max_price` |
| `attributes` | точное сравнение JSONB-значений как строк |
| `limit`, `offset` | пагинация |

Важно: `count` в ответе — количество товаров в текущем ответе, не общее число всех найденных результатов.

---

## 5. База данных

### Существующие таблицы Window of Light

| Таблица | Что хранит | Ключевые поля | Пример использования |
|---|---|---|---|
| `products` | Спарсенные товары из постов | `id UUID`, `brand`, `model`, `price NUMERIC(12,2)`, `category_id`, `raw_post_id`, `attributes`, `storage`, `ram`, `color`, `sim_type`, `screen_size`, `chip`, `connectivity`, `country_flag`, `sku`, `timestamp` | Поиск и карточка товара |
| `raw_posts` | Оригинальный текст Telegram-поста | `id UUID`, `text`, `message_link`, `channel_id`, `message_id`, `post_id`, `date`, `parsed_count`, `is_processed` | Кнопка оригинала |
| `price_history` | История изменения цен | `id UUID`, `product_id UUID`, `price NUMERIC(12,2)`, `timestamp`, `source_channel` | История цен |
| `categories` | Категории товаров | `id VARCHAR`, `name`, `parent_id`, `attributes JSONB`, `keywords JSONB`, `is_active` | Фильтрация и поиск |
| `channels` | Мониторируемые каналы WOL | `id UUID`, `channel_id`, `username`, `title`, `is_active`, `last_message_id` | Только read-only диагностика |
| `api_keys` | API ключи WOL | `key_hash`, `name`, `expires_at` | Запрещено показывать в боте |

### Новые таблицы бота

| Таблица | Что хранит | Ключевые поля |
|---|---|---|
| `tracked_products` | Отслеживаемые товары пользователей | `user_id`, `product_id`, `last_seen_price`, `last_notified_price`, `is_active` |
| `user_search_history` | История поисковых запросов | `user_id`, `query`, `normalized_query`, `product_id`, `final_price`, `results_count`, `metadata` |

На момент read-only проверки было: `categories=5`, `raw_posts=115`, `products=1822`, `price_history=0`. Эти значения будут меняться, потому что товары постоянно пополняются.

### Фактические категории WOL

| `category_id` | Название | Основные атрибуты |
|---|---|---|
| `smartphones` | Смартфоны | `storage`, `ram`, `sim_type`, `flag`, `color` |
| `laptops` | Ноутбуки | `processor`, `ram`, `storage`, `screen_size`, `color` |
| `tablets` | Планшеты | `storage`, `connectivity`, `processor`, `screen_size`, `color` |
| `accessories` | Аксессуары | `type`, `color`, `size`, `model` |
| `consoles` | Игровые приставки | `storage`, `color`, `version` |

### Ключевые связи

```text
raw_posts.id ← products.raw_post_id
products.id ← price_history.product_id
products.id ← tracked_products.product_id
products.id ← user_search_history.product_id
```

### Важные индексы для таблиц бота

| Индекс | Таблица | Назначение |
|---|---|---|
| `idx_tracked_products_user_id` | `tracked_products` | Быстрый список отслеживаний пользователя |
| `idx_tracked_products_product_id` | `tracked_products` | Поиск отслеживаний по товару |
| `idx_tracked_products_active` | `tracked_products` | Выбор активных отслеживаний для Celery |
| `idx_user_search_history_user_created` | `user_search_history` | История пользователя по дате |
| `idx_user_search_history_query_created` | `user_search_history` | Аналитика запросов |
| `idx_user_search_history_product_id` | `user_search_history` | Связь истории с товаром |
| `idx_user_search_history_query_count` | `user_search_history` | Топ популярных запросов |

---

## 6. Рекомендуемая структура проекта

```text
LithTGBot/
├── bot/
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── search.py
│   │   ├── catalog.py
│   │   ├── admin.py
│   │   ├── tracking.py
│   │   └── history.py
│   ├── keyboards/
│   │   ├── __init__.py
│   │   ├── product.py
│   │   ├── menu.py
│   │   └── history.py
│   ├── middlewares/
│   │   ├── __init__.py
│   │   ├── cleanup.py
│   │   └── rate_limit.py
│   └── filters/
│       └── __init__.py
├── services/
│   ├── __init__.py
│   ├── normalizer.py
│   ├── search.py
│   ├── query_router.py
│   ├── catalog.py
│   ├── tracker.py
│   ├── analytics.py
│   └── cleanup.py
├── integrations/
│   ├── __init__.py
│   └── wol_api.py
├── database/
│   ├── __init__.py
│   ├── session.py
│   ├── models.py
│   └── repositories/
│       ├── __init__.py
│       ├── tracked.py
│       ├── history.py
│       └── catalog.py
├── schemas/
│   ├── __init__.py
│   ├── product.py
│   ├── search.py
│   ├── catalog.py
│   └── history.py
├── utils/
│   ├── __init__.py
│   ├── price_formatter.py
│   └── text.py
├── tasks/
│   ├── __init__.py
│   ├── celery.py
│   └── price_tracking.py
├── migrations/
├── tests/
├── config.py
├── main.py
├── requirements.txt
├── .env.example
├── alembic.ini
├── docker-compose.yml         # Конфигурация запуска сервисов (bot, celery)
├── Dockerfile                 # Инструкции для сборки образа Python
├── CLAUDE.md
└── LISTING.md
```

---

## 7. Где что лежит

| Файл/директория | Что внутри | Зачем нужен |
|---|---|---|
| `.env` | Реальные конфиги и секреты | Не хранить в git |
| `.env.example` | Пример конфига с placeholders | Основа для настройки |
| `CLAUDE.md` | Полное ТЗ и инструкции для ИИ | Главный документ разработки |
| `LISTING.md` | Быстрый индекс проекта | Начальная навигация |
| `docker-compose.yml` | Инфраструктура | Запуск Redis/Celery и других сервисов при необходимости |
| `alembic.ini` | Конфиг Alembic | Миграции БД |
| `migrations/` | Alembic migrations | Создание таблиц бота |
| `config.py` | Pydantic Settings | Чтение `.env` |
| `main.py` | Точка входа | Запуск Telegram-бота |
| `requirements.txt` | Зависимости | Установка окружения |

### `bot/`

| Файл | Что внутри | Зачем нужен |
|---|---|---|
| `bot/handlers/common.py` | `/start`, `/help` | Общие команды |
| `bot/handlers/search.py` | Обработчики текстового поиска и пагинации | Основной UX поиска |
| `bot/handlers/catalog.py` | `/catalog`, последние товары, фильтры, табличный вывод | Универсальный каталог для пополняемой БД |
| `bot/handlers/admin.py` | Админ-команды | Статистика и топ запросов |
| `bot/handlers/tracking.py` | Callback-и отслеживания | Добавить/убрать отслеживание |
| `bot/handlers/history.py` | `/history`, callbacks истории | История пользователя |
| `bot/keyboards/product.py` | Клавиатуры товара | История цен, отслеживать, оригинал |
| `bot/keyboards/menu.py` | Главное меню | Навигация |
| `bot/keyboards/history.py` | Кнопки истории | Повторить, удалить |
| `bot/middlewares/cleanup.py` | Middleware автоочистки | Не держать много сообщений в чате |
| `bot/middlewares/rate_limit.py` | Rate limit middleware/helper | 10 поисковых запросов в минуту |

### `services/`

| Файл | Что внутри | Зачем нужен |
|---|---|---|
| `services/normalizer.py` | Сокращения, RU/EN нормализация, fuzzy matching | `17 PM` → `iPhone 17 Pro Max` |
| `services/query_router.py` | Преобразование нормализованного текста в WOL filters | `17 PM 256` → `category_id`, `brand`, `model`, `attributes.storage` |
| `services/search.py` | Orchestration поиска | Normalizer → QueryRouter → cache → WOL API → history |
| `services/catalog.py` | Универсальная read-only оболочка | Категории, последние товары, facets, безопасный DB browser |
| `services/tracker.py` | Бизнес-логика отслеживания цен | Проверка цен, уведомления |
| `services/analytics.py` | Популярные запросы, статистика | Админ-панель |
| `services/cleanup.py` | Управление message_id | Автоудаление старых результатов |

### `integrations/`

| Файл | Что внутри | Зачем нужен |
|---|---|---|
| `integrations/wol_api.py` | Async HTTP-клиент Window of Light API | Поиск, товар, история цен, raw post |

### `database/`

| Файл | Что внутри | Зачем нужен |
|---|---|---|
| `database/session.py` | Async engine/sessionmaker | Подключение к PostgreSQL |
| `database/models.py` | SQLAlchemy модели | `TrackedProduct`, `UserSearchHistory` |
| `database/repositories/tracked.py` | CRUD отслеживаний | Работа с `tracked_products` |
| `database/repositories/history.py` | CRUD истории | Работа с `user_search_history` |
| `database/repositories/catalog.py` | Параметризованные read-only SELECT | Allowlist-вывод данных из `products`, `raw_posts`, `price_history`, `categories` |

### `schemas/`

| Файл | Что внутри | Зачем нужен |
|---|---|---|
| `schemas/product.py` | `ProductDTO` | Единый формат товара |
| `schemas/search.py` | `SearchResultDTO`, данные нормализации | Единый формат поиска |
| `schemas/catalog.py` | `TableSchemaDTO`, `TableRowDTO`, `FacetDTO` | Единый формат каталога/табличного вывода |
| `schemas/history.py` | DTO истории | Единый формат истории |

### `utils/`

| Файл | Что внутри | Зачем нужен |
|---|---|---|
| `utils/price_formatter.py` | Форматирование цен | `79990` → `79 990 ₽` |
| `utils/text.py` | Markdown/HTML escaping | Безопасный Telegram-текст |

### `tasks/`

| Файл | Что внутри | Зачем нужен |
|---|---|---|
| `tasks/celery.py` | Celery app config | Worker/beat entrypoint |
| `tasks/price_tracking.py` | Periodic задачи | Проверка изменения цен |

### `tests/`

| Файл | Что проверяет |
|---|---|
| `tests/test_normalizer.py` | Нормализация, сокращения, опечатки |
| `tests/test_price_formatter.py` | Форматирование цен |
| `tests/test_rate_limit.py` | Лимит запросов |
| `tests/test_history.py` | История и актуальные цены |
| `tests/test_tracking.py` | Отслеживание и уведомления |

---

## 8. Поток поиска

```text
1. Пользователь отправляет текст
2. bot/handlers/search.py принимает сообщение
3. Rate limit проверяет лимит
4. services/normalizer.py нормализует запрос
5. services/query_router.py преобразует текст в structured WOL filters
6. services/search.py проверяет Redis cache
7. При cache miss вызывается integrations/wol_api.py
8. WOL API ищет товары в PostgreSQL
9. Результат сохраняется в Redis
10. Запись сохраняется в user_search_history
11. Пользователь получает страницу результатов
12. services/cleanup.py сохраняет message_id и удаляет старые сообщения
```

---

## 9. Поток отслеживания цены

```text
1. Пользователь нажимает 🔔 Отслеживать
2. bot/handlers/tracking.py получает callback
3. services/tracker.py получает актуальную цену товара
4. database/repositories/tracked.py создаёт tracked_products
5. Celery beat ежедневно запускает tasks/price_tracking.py
6. Задача получает активные tracked_products
7. Для каждого товара получает актуальную цену
8. Если цена изменилась — отправляет уведомление
9. last_seen_price и last_notified_price обновляются
```

---

## 10. Поток истории пользователя

```text
1. Пользователь отправляет /history
2. bot/handlers/history.py получает последние 20 записей
3. Для записей с product_id запрашивается актуальная цена
4. Пользователь видит историю с актуальными ценами
5. Кнопка Повторить запускает поиск заново
6. Кнопка Удалить удаляет запись истории
```

---

## 11. Поток истории цен

```text
1. Пользователь нажимает 📊 История цен
2. bot/handlers/tracking.py или history.py получает callback
3. integrations/wol_api.py запрашивает /api/v1/products/{id}/history
4. services/tracker.py или отдельный formatter готовит текстовую сводку
5. Бот отправляет историю цен за 7 дней или последние доступные записи
```

---

## 12. Нормализация: быстрые примеры

| Вход | Нормализованный запрос |
|---|---|
| `17 PM 256` | `iPhone 17 Pro Max 256GB` |
| `16 P 512` | `iPhone 16 Pro 512GB` |
| `15 128` | `iPhone 15 128GB` |
| `iphoe 16` | `iPhone 16` |
| `айфон 15 про макс 256` | `iPhone 15 Pro Max 256GB` |
| `s24 ultra 512` | `Samsung Galaxy S24 Ultra 512GB` |
| `s24+ 256` | `Samsung Galaxy S24+ 256GB` |
| `mba 512` | `MacBook Air 512GB` |
| `mbp 1tb` | `MacBook Pro 1TB` |

Важное правило: `17 чехол` не должен автоматически превращаться в `iPhone 17`, если нет признаков поиска телефона.

---

## 13. Универсальная оболочка вывода данных из БД

Товары будут постоянно пополняться, поэтому LithTGBot должен уметь выводить не только заранее заданные модели, но и любые безопасные товарные данные из БД.

### Компоненты

| Компонент | Назначение |
|---|---|
| `services/catalog.py` | Read-only каталог, facets, табличная выдача |
| `database/repositories/catalog.py` | Параметризованные SELECT-запросы |
| `bot/handlers/catalog.py` | `/catalog`, `/db_table`, `/db_schema`, сценарии каталога |
| `schemas/catalog.py` | DTO таблиц, строк, фильтров, facets |

### Allowlist таблиц

| Таблица | Доступ обычному пользователю | Доступ админу | Комментарий |
|---|---|---|---|
| `products` | да | да | Основная товарная выдача |
| `categories` | да | да | Категории и атрибуты |
| `raw_posts` | ограниченно | да | Обычному пользователю через карточку оригинала |
| `price_history` | да | да | Через историю цены товара |
| `channels` | нет | да | Только диагностика |
| `api_keys` | нет | нет | Всегда запрещено |

### Правила безопасности

1. Никакого произвольного SQL от пользователя.
2. Только allowlist таблиц и колонок.
3. Только `SELECT`.
4. Все фильтры параметризованные.
5. Каждый запрос имеет `LIMIT`; максимум по умолчанию `20`.
6. Длинные поля вроде `raw_posts.text` показывать preview.
7. `api_keys` не выводить никогда.

### Сценарии

| Команда/текст | Поведение |
|---|---|
| `/catalog` | Показать категории из `/api/v1/categories` |
| `последние товары` | Последние товары по `timestamp DESC` |
| `смартфоны 256GB` | Фильтр `category_id=smartphones`, `attributes.storage=256GB` |
| `айфон до 90000` | Фильтр `max_price=90000` |
| `/db_schema products` | Админ: показать allowlist-колонки |
| `/db_table products` | Админ: показать таблицу с лимитом |

---

## 14. Redis ключи

| Назначение | Ключ | TTL |
|---|---|---|
| Search cache | `search:{query_hash}:{page}` | 300 сек |
| Query token | `query_token:{token}` | 1800 сек |
| Product short id | `product_short:{short_id}` | 86400 сек |
| Rate limit | `rate:{user_id}:{minute}` | 60 сек |
| Cleanup messages | `cleanup:{chat_id}` | 86400 сек |

Если Redis недоступен, бот должен продолжить работу без кэша и не падать.

---

## 15. Callback data

Telegram ограничивает `callback_data` 64 байтами.

Использовать короткие форматы:

| Действие | Формат |
|---|---|
| Страница поиска | `s:{token}:{page}` |
| Товар | `p:{short_id}` |
| Отслеживать | `t:{short_id}` |
| История цен | `ph:{short_id}` |
| Оригинал | `o:{short_id}` |
| Повторить запрос | `r:{history_id}` |
| Удалить историю | `hd:{history_id}` |
| Отключить отслеживание | `ut:{tracked_id}` |

Полные UUID и запросы хранить в Redis.

---

## 16. Команды бота

| Команда | Доступ | Назначение |
|---|---|---|
| `/start` | Все | Приветствие и примеры |
| `/help` | Все | Помощь и сокращения |
| `/history` | Все | Последние 20 запросов |
| `/tracked` | Все | Активные отслеживания пользователя |
| `/catalog` | Все | Категории и пополняемый каталог товаров |
| `/admin` | Только admin | Админ-панель |
| `/admin_stats` | Только admin | Краткая статистика |
| `/admin_top_day` | Только admin | Топ запросов за день |
| `/admin_top_week` | Только admin | Топ запросов за неделю |
| `/admin_top_month` | Только admin | Топ запросов за месяц |

---

## 17. Основные UI-кнопки

### Главное меню

```text
[🔎 Поиск] [🗂 Каталог]
[📜 История] [🔔 Отслеживаемые]
[ℹ️ Помощь]
```

### Товар

```text
[📊 История цен] [🔔 Отслеживать] [📄 Оригинал]
[← Назад]
```

### История

```text
[Повторить] [Удалить]
```

### Пагинация

```text
[←] [1/5] [→]
```

---

## 18. Форматы вывода

### Результаты поиска

```text
🔎 iPhone 17 Pro Max 256GB
Найдено: 24

1. iPhone 17 Pro Max 256GB White eSIM — 89 900 ₽
2. iPhone 17 Pro Max 256GB Black physical — 104 900 ₽
3. iPhone 17 Pro Max 256GB Natural SIM+eSIM — 111 000 ₽
```

### История пользователя

```text
📜 История поиска
━━━━━━━━━━━━━━━━━━━━━━
1. iPhone 17 Pro Max 256GB
   89 990 ₽ (акт.) • 25.04.2026

2. Samsung S24 Ultra
   74 990 ₽ (акт.) • 24.04.2026
```

### История цен

```text
📊 История цен: iPhone 16 Pro 256GB
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 28.04 — 94 990 ₽ (↓ -5.2%)
📅 25.04 — 99 990 ₽ (→ без изменений)
📅 22.04 — 99 990 ₽ (↑ +3.1%)

Мин: 89 990 ₽  |  Макс: 104 990 ₽
```

---

## 19. Форматирование цены

| Вход | Выход |
|---|---|
| `79990` | `79 990 ₽` |
| `0` | `0 ₽` |
| `None` | `Цена не указана` |

---

## 20. Rate limit

Лимит: 10 поисковых запросов в минуту на пользователя.

Применяется к:

- текстовым поисковым запросам.

Не применяется к:

- `/start`
- `/help`
- `/history`
- `/tracked`
- `/admin`
- callback-кнопкам

Сообщение при превышении:

```text
Слишком много запросов. Попробуйте через N секунд.
```

---

## 21. Автоочистка сообщений

Цель: максимум 3 последних сообщения бота с результатами поиска в одном чате.

Правила:

1. Хранить список `message_id` в Redis по ключу `cleanup:{chat_id}`.
2. После отправки нового результата добавить `message_id`.
3. Если сообщений больше 3 — удалить самые старые.
4. Ошибки удаления логировать как warning.
5. Не удалять `/start`, `/help`, `/admin`.
6. Не удалять сообщения пользователя без явного требования.

---

## 22. Ошибки и fallback

| Ошибка | Поведение |
|---|---|
| PostgreSQL недоступен | `База временно недоступна. Попробуйте позже.` |
| Window of Light API недоступен | `Поиск временно недоступен. Попробуйте позже.` |
| Redis недоступен | Продолжить без кэша, залогировать ошибку |
| Товар не найден | `Ничего не найдено. Попробуйте изменить запрос.` |
| Истории цен нет | `История цен пока отсутствует.` |
| Товар удалён | `Товар больше не доступен.` |
| Telegram delete failed | Warning в лог, не показывать пользователю |

---

## 23. Минимальные тесты

| Тест | Что проверить |
|---|---|
| `test_normalizer.py` | Сокращения, RU/EN, fuzzy, защита от ложной нормализации |
| `test_price_formatter.py` | Формат цены |
| `test_rate_limit.py` | 10 запросов проходят, 11-й блокируется |
| `test_history.py` | Последние 20 записей, актуальная цена, удаление, повтор |
| `test_catalog.py` | `/catalog`, allowlist, запрет `api_keys`, LIMIT, preview длинных полей |
| `test_tracking.py` | Добавление, дубли, отключение, уведомления при изменении цены |

---

## 24. Переменные окружения

| Переменная | Назначение | Пример |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота от BotFather | `change_me` |
| `WOL_API_BASE_URL` | URL Window of Light API | `http://192.168.1.220:8002` |
| `WOL_API_TIMEOUT_SECONDS` | Timeout HTTP-запросов | `10` |
| `DB_HOST` | PostgreSQL host | `192.168.1.144` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_NAME` | PostgreSQL database | `window_of_light` |
| `DB_USER` | PostgreSQL user | `wol_user` |
| `DB_PASSWORD` | PostgreSQL password | `change_me` |
| `DB_READONLY_MODE` | Read-only режим для прямых WOL-таблиц | `true` |
| `REDIS_HOST` | Redis host | `192.168.1.144` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_DB` | Redis DB number | `0` |
| `CELERY_BROKER_URL` | Celery broker | `redis://192.168.1.144:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery result backend | `redis://192.168.1.144:6379/1` |
| `ADMIN_USER_IDS` | Telegram ID админов | `123456789,987654321` |
| `RATE_LIMIT_PER_MINUTE` | Поисковый лимит | `10` |
| `SEARCH_PAGE_SIZE` | Размер страницы поиска | `10` |
| `SEARCH_CACHE_TTL_SECONDS` | TTL кэша поиска | `300` |
| `MAX_SEARCH_MESSAGES_PER_CHAT` | Максимум сообщений поиска | `3` |
| `CATALOG_MAX_ROWS` | Максимум строк DB browser/catalog | `20` |
| `DB_BROWSER_ADMIN_ONLY` | DB browser только для админов | `true` |

---

## 25. Запуск

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

## 26. Acceptance checklist

- [ ] `python main.py` запускает бота.
- [ ] `/start` работает.
- [ ] `/help` работает.
- [ ] `17 PM 256` ищет `iPhone 17 Pro Max 256GB`.
- [ ] `iphoe 16` исправляется до `iPhone 16`.
- [ ] Поиск идёт через Window of Light API `http://192.168.1.220:8002`.
- [ ] Свободный текст преобразуется в structured `ProductSearchRequest`.
- [ ] `/catalog` показывает актуальные категории из WOL API.
- [ ] Read-only оболочка выводит allowlist-таблицы/колонки с лимитом.
- [ ] `/db_table api_keys` всегда запрещён даже админу.
- [ ] Результаты кэшируются в Redis.
- [ ] Пагинация работает.
- [ ] Rate limit блокирует 11-й запрос за минуту.
- [ ] Callback data короче 64 байт.
- [ ] Кнопка `🔔 Отслеживать` работает.
- [ ] `/tracked` показывает отслеживаемые товары.
- [ ] Celery beat проверяет цены.
- [ ] Уведомление отправляется при изменении цены.
- [ ] `/history` показывает актуальные цены.
- [ ] `📊 История цен` показывает текстовую сводку.
- [ ] `/admin` защищён по `ADMIN_USER_IDS`.
- [ ] Автоочистка оставляет максимум 3 поисковых сообщения.
- [ ] Alembic-миграции созданы.
- [ ] Unit-тесты проходят.
- [ ] Секреты не захардкожены.

---

## 27. Последнее обновление

- **Версия проекта:** `0.1.0`
- **Документ обновлён:** `2026-05-04`

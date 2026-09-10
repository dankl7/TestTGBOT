# Window of Light — Документация проекта

## Краткое описание

**Window of Light** — бэкенд-сервис для парсинга и хранения данных о товарах из Telegram-каналов. Состоит из двух компонентов: **Telegram Ingestion** (мониторинг каналов через MTProto) и **FastAPI API** (REST-интерфейс для поиска и получения данных). Парсит посты с ценами на электронику по YAML-конфигурации и сохраняет в PostgreSQL. Для клиента `LithTGBot` поле `timestamp` остаётся источником строки `Собрано:` и отражает время последнего релевантного Telegram-события: `message.date` для новых постов и `edit_date` для отредактированных.

**Стек:** Python 3.11 | FastAPI | Telethon (MTProto) | SQLAlchemy 2.0 (psycopg2) | Redis | Pydantic 2.0+ | uvicorn

---

## Как работает проект

1. Сервис подключается к Telegram через MTProto (Telethon) и мониторит указанные каналы
2. При появлении нового поста или редактировании существующего — парсит его по YAML-правилам (`config/parsing_rules/`)
3. Извлечённые товары нормализуются и сохраняются в PostgreSQL; товар с тем же `message_link` обновляется in-place, а `timestamp` берётся из `edit_date`, если прайс был обновлён редактированием старого поста
4. FastAPI предоставляет REST API для поиска товаров, получения истории цен, управления каналами и health/status
5. ProxyManager мониторит канал с прокси и автоматически ротирует MTProto-прокси
6. Redis используется как cache-слой для `/api/v1/products/search` и health-проверки зависимости; после новых или отредактированных постов search-cache WOL инвалидируется

---

## Структура проекта и назначение файлов

### Корень проекта

| Файл | Назначение |
|------|-----------|
| `docker-compose.yml` | 1 сервис: `app` с `network_mode: host`. |
| `Dockerfile` | Python 3.11-slim, gcc/libpq-dev. |
| `requirements.txt` | 18 Python-зависимостей. |
| `.env` | Конфигурация: DB, Telegram API, прокси. |

### `services/` — Основные сервисы

| Файл | Назначение |
|------|-----------|
| `run_combined.py` | **Главный файл (~660 строк).** Объединяет FastAPI + Telegram ingestion в одном процессе. Содержит API-эндпоинты `/api/v1/products/search`, `/api/v1/products/{id}`, `/api/v1/products/{id}/history`, `/api/v1/categories`, `/api/v1/channels/`, `/api/v1/proxy/*`, `/health`, `/status`. Инициализирует БД и Redis синхронно, а Telegram ingestion держит в фоне с retry-циклом: если MTProto/SOCKS5 временно недоступны на старте, HTTP API не падает и повторяет подключение каждые 15 секунд. При внешнем восстановлении VPN `proxy_health_monitor.py` перезапускает контейнер WOL, чтобы ingestion заново подключился к Telegram на рабочем туннеле. `/status` отдаёт счетчики ingestion (`channels_monitored`, `messages_sent`, `messages_parsed`, `parser_products`) для админ-сводки бота. |
| `normalizer.py` | `NormalizerService`. Нормализация данных товаров: цвета (маппинг, сокращения, коррекция `Top re:sale` `White` → `Silver` для iPhone Pro/Pro Max), память (256→256GB), SIM-тип, модель. Для Sony-консолей отдельно нормализует `DualSense/DualShock -> PS5 DualShock`, `Portal -> PS5 Portal`, а также `PS5 128GB/512GB/...` в консольной категории как `PS5 Portal`. |
| `proxy_manager.py` | `ProxyManager`. MTProto прокси-менеджер: мониторинг канала ProxyMTProto, парсинг прокси из сообщений, ротация, health check. Дефолтный прокси `proxy.chunkycorp.shop:443`. |

### `parser/` — Парсинг постов

| Файл | Назначение |
|------|-----------|
| `parser_service.py` | `ParserService`. Оркестрация парсинга: координирует вызовы `UniversalParser`, сохраняет распарсенные товары в БД и после успешного сохранения инвалидирует WOL search-cache, чтобы бот не ждал TTL со старой датой. |
| `universal_parser.py` | `UniversalParser` (~630 строк). Блочный парсер: разбивает пост на секции по заголовкам, извлекает товары по эвристикам и YAML-контексту. Поддерживает форматы "Bests re:sale" и "Top re:sale". Для Sony-консолей различает `PS5`, `PS5 Slim`, `PS5 Pro`, `PS5 Portal`, `PS5 DualShock`, `PS5 VR2` и не схлопывает `portal` в `PS5 Pro`. Генерирует детерминированные UUID. |

### `ingestion/` — Telegram-ингест

| Файл | Назначение |
|------|-----------|
| `telegram_client.py` | `TelegramIngestionService`. Telethon-клиент для мониторинга каналов. Подключение через SOCKS5-прокси, полный исторический `scan_history()` при старте и live-подписка через `events.NewMessage()` и `events.MessageEdited()` для непрерывного сбора новых и отредактированных постов после стартового скана. Для edited posts в `RawMessage.timestamp` передаётся `message.edit_date`, чтобы клиент видел реальную свежесть прайса. |
| `config_loader.py` | `ChannelConfigLoader`. Загрузка конфигурации каналов из YAML. Hot-reload через watchdog. |

### `storage/` — Хранение данных

| Файл | Назначение |
|------|-----------|
| `repository.py` | `ProductRepository` и `CategoryRepository`. CRUD-операции: создание товаров, поиск по критериям, история цен, управление категориями. В поиске корректно обрабатываются нулевые границы цены (`0`), отрицательные `limit/offset` нормализуются, а операции записи откатывают транзакцию при ошибках. |

### `common/` — Общие компоненты

| Файл | Назначение |
|------|-----------|
| `config.py` | `Settings(BaseSettings)` — настройки из `.env`: DB, Telegram API, прокси. |
| `database.py` | SQLAlchemy-модели 6 таблиц: `Category`, `Product`, `PriceHistory`, `Channel`, `APIKey`, `RawPost`. `Database`-обёртка для сохранения товаров: новая запись создаётся для нового `message_link`, а существующая обновляется in-place с добавлением `price_history`, если Telegram-пост был отредактирован. `get_db()` — генератор сессий. |
| `models.py` | Pydantic-модели: `RawMessage`, `ParsedProduct`, `SearchCriteria`. |

### `config/` — YAML-конфигурация

| Файл | Назначение |
|------|-----------|
| `channels.yaml` | Список Telegram-каналов для мониторинга (link, title, is_active). |
| `parsing_rules/smartphones.yaml` | Правила парсинга для смартфонов. |
| `parsing_rules/laptops.yaml` | Правила парсинга для ноутбуков. |
| `parsing_rules/tablets.yaml` | Правила парсинга для планшетов. |
| `parsing_rules/consoles.yaml` | Правила парсинга для приставок. |
| `parsing_rules/accessories.yaml` | Правила парсинга для аксессуаров. |

### `templates/`

| Файл | Назначение |
|------|-----------|
| `index.html` | Frontend-шаблон (веб-интерфейс). |

### `tests/`

| Файл | Назначение |
|------|-----------|
| `test_parsers.py` | Регрессионные тесты парсеров: iPhone, Samsung, MacBook, Dyson, SIM-типы, детерминированные ID, fixtures, коррекция цвета Top re:sale `White` → `Silver`, а также Sony `PS5 Portal` / `PS5 DualShock` / `PS5 Pro Digital`. |
| `test_endpoints.py` | Тесты REST-эндпоинтов: `/health`, `/status`, сериализация поиска, товара, price history и API keys, а также регрессия на retry-старт ingestion без падения API при временно недоступном Telegram. |
| `test_repository.py` | Регрессии слоя репозиториев: нулевые price bounds, нормализация отрицательной пагинации и обновление существующего товара по `message_link`. |
| `test_ingestion_updates.py` | Регрессии ingestion: отредактированный Telegram-пост повторно передаётся в парсер и при необходимости обновляет `last_message_id`. |
| `data/bests_resale.txt` | Тестовый пост "Bests re:sale". |
| `data/top_resale.txt` | Тестовый пост "Top re:sale". |

---

## Пути к файлам

```
/home/dankl/my-project/Window of Light/Window of Light/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env
├── services/
│   ├── run_combined.py
│   ├── normalizer.py
│   └── proxy_manager.py
├── parser/
│   ├── parser_service.py
│   └── universal_parser.py
├── ingestion/
│   ├── telegram_client.py
│   └── config_loader.py
├── storage/
│   └── repository.py
├── common/
│   ├── config.py
│   ├── database.py
│   └── models.py
├── config/
│   ├── channels.yaml
│   └── parsing_rules/
│       ├── smartphones.yaml
│       ├── laptops.yaml
│       ├── tablets.yaml
│       ├── consoles.yaml
│       └── accessories.yaml
├── templates/
│   └── index.html
├── sessions/
│   ├── wol_session.session
│   └── wol_session.session-journal
└── tests/
    ├── test_parsers.py
    └── data/
        ├── bests_resale.txt
        └── top_resale.txt
```

---

## API Endpoints

| Endpoint | Метод | Назначение |
|----------|-------|-----------|
| `/` | GET | Веб-интерфейс (index.html) |
| `/health` | GET | Проверка здоровья (DB, Telegram) |
| `/status` | GET | Статус системы и счетчики ingestion/parsing для оперативного мониторинга |
| `/api/v1/products/search` | POST | Поиск товаров по критериям |
| `/api/v1/products/{id}` | GET | Товар по UUID |
| `/api/v1/products/{id}/history` | GET | История цен товара |
| `/api/v1/categories` | GET | Все категории с атрибутами |
| `/api/v1/channels/` | GET | Список мониторимых каналов |
| `/api/v1/channels/add` | POST | Добавить канал |
| `/api/v1/channels/remove` | POST | Удалить канал |
| `/api/v1/api-keys` | POST | Создать API-ключ |
| `/api/v1/proxy/current` | GET | Текущий прокси |
| `/api/v1/proxy/mtproto` | GET | MTProto прокси |
| `/api/v1/proxy/rotate` | POST | Ротация прокси |
| `/api/v1/proxy/mark_dead` | POST | Пометить прокси как мёртвый |
| `/api/v1/proxy/all` | GET | Все прокси |

---

## Таблицы PostgreSQL

| Таблица | Назначение |
|---------|-----------|
| `categories` | Категории товаров (id, name, attributes JSONB, keywords JSONB) |
| `products` | Товары (id, category_id, brand, model, price, source_channel, message_link, timestamp, attributes JSONB). Обновляются по `message_link`, если исходный Telegram-пост был отредактирован. |
| `price_history` | История цен (product_id, price, timestamp, source_channel). Пополняется и при редактировании исходного поста, если изменилась цена или timestamp. |
| `channels` | Telegram-каналы (channel_id, username, title, is_active) |
| `api_keys` | API-ключи (key_hash, name, is_active, expires_at) |
| `raw_posts` | Сырые посты (channel_id, message_id, text, date, is_processed, parsed_count). В текущем рантайме не существует публичного REST-эндпоинта для чтения raw-post по id. |

---

Примечание: свежесть строки `Собрано:` в `LithTGBot` зависит от двух факторов в `Window of Light`: live-ingestion должен получить новое событие из Telegram, а сохранение товара должно обновить существующую запись по тому же `message_link` вместо сохранения устаревших данных в выдаче. Если поставщик обновляет ассортимент редактированием старого поста, свежесть определяется по `edit_date`. Если в момент старта недоступен SOCKS5-прокси или сам Telegram, ingestion уходит в retry-цикл, но API `/health`, `/status` и `/api/v1/products/search` остаются доступны для бота и диагностики. Для долгоживущего восстановления после обрыва VPN проект опирается на внешний `LithTGBot/proxy_health_monitor.py`, который каждые 30 секунд проверяет доступность Telegram через SOCKS5 и при восстановлении перезапускает WOL-контейнер.

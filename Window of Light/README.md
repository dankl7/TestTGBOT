# Window of Light 🌐

Автоматизированная система сбора, обработки и хранения данных о товарах из Telegram-каналов.

## Архитектура

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Telegram      │────▶│   Ingestion      │────▶│   Parser       │────▶│   Storage       │
│   Channels      │     │   Service        │     │   Service      │     │   Repository    │
└─────────────────┘     └──────────────────┘     └──────────────────┘     └─────────────────┘
                                                                          │
                                                                          ▼
                                                                  ┌─────────────────┐
                                                                  │   PostgreSQL    │
                                                                  └─────────────────┘
                                                                          │
                                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │◀────│   API            │◀────│   Cache        │◀────│   Product       │
│   (React/Vue)   │     │   Endpoints      │     │   (Redis)      │     │   Repository    │
└─────────────────┘     └──────────────────┘     └─────────────────┘     └─────────────────┘
```

## Компоненты

### 1. Сбор данных (Ingestion)
- **telegram_client.py** - TelegramIngestionService
  - Подключение к Telegram через MTProto
  - Мониторинг каналов в реальном времени
  - Сканирование истории сообщений
  - Передача сообщений в Parser

### 2. Обработка и нормализация (Parser)
- **parser_service.py** - ParserService: координирует парсинг и запись в БД.
- **universal_parser.py** - UniversalParser:
  - Один проход по всему посту: распознаёт заголовки секций, переносит контекст бренда/категории, извлекает атрибуты (флаги, SIM-тип, storage, color).
  - Поддерживает форматы Top re:sale (флаг + sim_type перед моделью) и Bests re:sale (модель ⇒ цена ⇒ флаг с точечной разделителем тысяч).
  - Skip-логика жёстко ограничена двумя токенами: `asis`/`асис` и `с коробкой`/`с коробки`.

### 3. Хранение (Storage)
- **repository.py** - Repository Pattern
  - ProductRepository
  - CategoryRepository
  - Проверка дубликатов
  - Динамическое создание категорий
- **database.py** - SQLAlchemy модели
  - Products, Categories, PriceHistory, Channels, APIKeys

### 4. API
- **run_combined.py** - FastAPI endpoints
  - `/api/v1/products/{id}` - получить продукт
  - `/api/v1/products/search` - поиск продуктов
  - `/api/v1/categories` - список категорий
  - `/api/v1/channels/` - управление каналами
  - `/status` - статус системы
  - `/health` - health check

## Установка

### 1. Клонирование
```bash
git clone <repository>
cd window_of_light
```

### 2. Зависимости
```bash
pip install -r requirements.txt
```

### 3. Конфигурация
Создайте `.env` файл:
```env
# Telegram (из my.telegram.org)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+7xxxxxxxxxx

# PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=window_of_light
DB_USER=postgres
DB_PASSWORD=postgres

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Приложение
DEBUG=true
CACHE_TTL=600
```

### 4. База данных
```sql
CREATE DATABASE window_of_light;
```

### 5. Запуск
```bash
python services/run_combined.py
```

API доступно на: `http://localhost:8002`

## Структура проекта

```
window_of_light/
├── api/                    # API endpoints
│   └── products.py
├── common/                 # Общие компоненты
│   ├── config.py          # Настройки
│   ├── database.py        # DB модели
│   └── models.py          # Pydantic модели
├── config/                 # Конфигурация
│   ├── channels.yaml      # Каналы для мониторинга
│   └── parsing_rules/     # Правила парсинга
│       ├── smartphones.yaml
│       ├── laptops.yaml
│       └── ...
├── ingestion/              # Сбор данных
│   ├── telegram_client.py
│   └── config_loader.py
├── parser/                 # Парсинг
│   ├── parser_service.py   # Координация (parse + persist)
│   └── universal_parser.py # Чистая функция parse_products()
├── services/               # Сервисы
│   └── run_combined.py    # Combined service
├── storage/                # Хранение
│   ├── repository.py
│   └── storage_service.py
└── .env                    # Environment variables
```

## API Endpoints

### Products
```bash
# Получить продукт
GET /api/v1/products/{id}

# Поиск продуктов
POST /api/v1/products/search
{
  "category_id": "smartphones",
  "brand": "Apple",
  "min_price": 50000,
  "max_price": 150000,
  "limit": 50
}

# История цены
GET /api/v1/products/{id}/history
```

### Categories
```bash
# Все категории
GET /api/v1/categories
```

### Channels
```bash
# Список каналов
GET /api/v1/channels/

# Добавить канал
POST /api/v1/channels/add
{
  "link": "https://t.me/tech_deals",
  "title": "Tech Deals"
}

# Удалить канал
POST /api/v1/channels/remove
{
  "link": "https://t.me/tech_deals"
}
```

### System
```bash
# Статус
GET /status

# Health check
GET /health
```

## Правила парсинга

Формат YAML для категорий:

```yaml
category:
  id: "smartphones"
  name: "Smartphones"
  keywords:
    - "iphone"
    - "samsung"
  
  brand_patterns:
    apple:
      - "iphone"
      - "17 "
    samsung:
      - "samsung"
      - "galaxy"
  
  attributes:
    - name: "storage"
      patterns:
        - "(\\d+)\\s*GB"
    - name: "color"
      patterns:
        - "\\b(black|white|blue|red)\\b"
  
  flags_esim_only: ["🇧🇭", "🇯🇵", "🇺🇸"]
  flags_esim_physical: ["🇪🇺", "🇮🇳"]
  flags_physical_only: ["🇨🇳"]
```

## Производительность

### Оптимизации
- ✅ Lazy initialization LLM клиента
- ✅ Connection pooling для БД
- ✅ Redis кэширование (TTL: 10min)
- ✅ Проверка дубликатов по message_link
- ✅ Async/await для I/O операций
- ✅ Группировка сообщений в Parser

### Масштабирование
- Redis для кэширования и pub/sub
- PostgreSQL connection pool (10/30)
- Поддержка multi-process через uvicorn workers

## Безопасность

- API ключи через `X-API-Key` header
- Environment variables для secrets
- SQL injection защита (SQLAlchemy ORM)
- Validation через Pydantic

## Мониторинг

### Логи
```bash
# Structlog JSON формат
{"level": "info", "event": "Product saved", "brand": "Apple", "model": "iPhone 17"}
```

### Метрики
- `messages_sent` - количество отправленных сообщений
- `messages_parsed` - количество распарсенных продуктов
- `products_saved` - количество сохраненных в БД

## Troubleshooting

### Database connection error
```bash
# Проверьте PostgreSQL
pg_isready -h localhost -p 5432

# Создайте БД
createdb -U postgres window_of_light
```

### Telegram auth error
```bash
# Проверьте credentials из my.telegram.org
# Убедитесь, что TELEGRAM_API_ID и TELEGRAM_API_HASH верные
```

### Redis not available
```bash
# Проверьте Redis
redis-cli ping

# Или отключите Redis - система будет работать без кэша
```

## Лицензия

MIT

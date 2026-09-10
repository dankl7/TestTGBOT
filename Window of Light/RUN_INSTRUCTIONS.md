# Window of Light - Инструкция по запуску

## 📋 Предварительные требования

### 1. PostgreSQL
```bash
# Установите PostgreSQL (если не установлен)
# Windows: https://www.postgresql.org/download/windows/
# Или через Docker:
docker run -d --name postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15
```

### 2. Redis (опционально, для кэширования)
```bash
# Windows: https://github.com/microsoftarchive/redis/releases
# Или через Docker:
docker run -d --name redis -p 6379:6379 redis:7
```

### 3. Python зависимости
```bash
cd "C:\Users\danii\Desktop\Window of Light Workspace\window_of_light"
pip install -r requirements.txt
```

## 🚀 Быстрый старт

### Шаг 1: Очистка базы данных (если нужно)
```bash
python clear_db.py
# Введите 'YES' для подтверждения
```

### Шаг 2: Создание базы данных
```sql
-- В PostgreSQL:
CREATE DATABASE window_of_light;
```

### Шаг 3: Настройка .env файла
Создайте файл `.env` в корне проекта:
```env
# Telegram (из https://my.telegram.org)
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+7xxxxxxxxxx

# PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_NAME=window_of_light
DB_USER=postgres
DB_PASSWORD=postgres

# Redis (опционально)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Приложение
DEBUG=true
CACHE_TTL=600
API_KEY=your-secret-api-key
```

### Шаг 4: Запуск комбинированного сервиса
```bash
python services/run_combined.py
```

Или через uvicorn:
```bash
python -m uvicorn services.run_combined:app --reload --host 0.0.0.0 --port 8002
```

## 📡 API Endpoints

После запуска API доступно на: `http://localhost:8002`

### Основные endpoints:

#### Status
```bash
GET http://localhost:8002/status
GET http://localhost:8002/health
```

#### Products
```bash
# Получить продукт
GET http://localhost:8002/api/v1/products/{id}

# Поиск продуктов
POST http://localhost:8002/api/v1/products/search
{
  "category_id": "smartphones",
  "brand": "Apple",
  "min_price": 50000,
  "max_price": 150000,
  "limit": 50
}

# История цены
GET http://localhost:8002/api/v1/products/{id}/history
```

#### Categories
```bash
GET http://localhost:8002/api/v1/categories
```

#### Channels
```bash
# Список каналов
GET http://localhost:8002/api/v1/channels/

# Добавить канал
POST http://localhost:8002/api/v1/channels/add
{
  "link": "https://t.me/top_resale",
  "title": "Top re:sale"
}

# Удалить канал
POST http://localhost:8002/api/v1/channels/remove
{
  "link": "https://t.me/top_resale"
}
```

## 🧪 Тестирование парсера

Универсальный парсер покрывает оба формата (Top re:sale и Bests re:sale).

```bash
pytest tests/test_parsers.py -v
```

Если нужно прогнать парсер вручную на собственных данных:
```python
from datetime import datetime
from common.models import RawMessage
from parser.universal_parser import parse_products

with open('your_post.txt', encoding='utf-8') as f:
    text = f.read()

raw = RawMessage(
    id='manual',
    text=text,
    timestamp=datetime.utcnow(),
    channel_id='manual',
    message_link='https://t.me/manual/1',
)
print(len(parse_products(raw)))
```

## 🛠️ Troubleshooting

### Database connection error
```bash
# Проверьте PostgreSQL
pg_isready -h localhost -p 5432

# Создайте БД
createdb -U postgres window_of_light
```

### Telegram auth error
```bash
# Получите credentials из https://my.telegram.org
# Убедитесь, что TELEGRAM_API_ID и TELEGRAM_API_HASH верные
```

### Redis not available
```bash
# Проверьте Redis
redis-cli ping

# Или запустите без Redis - система будет работать без кэша
```

## 📊 Мониторинг

### Логи
Система использует structlog для логирования в JSON формате:
```json
{"level": "info", "event": "Product saved", "brand": "Apple", "model": "iPhone 17"}
```

### Метрики
- `messages_sent` - количество отправленных сообщений
- `messages_parsed` - количество распарсенных продуктов  
- `products_saved` - количество сохраненных в БД

## 🧹 Очистка данных

### Очистить всю базу данных:
```bash
python clear_db.py
# Введите 'YES' для подтверждения
```

### Очистить через SQL:
```sql
TRUNCate TABLE products, price_history, categories, channels, api_keys RESTART IDENTITY CASCADE;
```

## 📝 Примечания

- Парсеры работают асинхронно
- TopResaleParser игнорирует ASIS/обменки (настраивается)
- BestsResaleParser игнорирует (ASIS) и refurbished
- Normalizer удаляет sim_type для non-phone устройств
- Все продукты нормализуются перед записью в БД

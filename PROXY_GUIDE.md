# AdGuard VPN Proxy — Инструкция по настройке и использованию

## Обзор

Все сервисы проекта **Window of Light** работают через **AdGuard VPN** в режиме SOCKS5-прокси. Это обеспечивает анонимность и обход блокировок Telegram API.

---

## Текущая конфигурация

| Параметр | Значение |
|----------|----------|
| **VPN-провайдер** | AdGuard VPN CLI v1.7.12 |
| **Режим** | SOCKS5 |
| **Адрес прокси** | `127.0.0.1:1080` |
| **Локация** | RIGA (Латвия) |
| **IP через VPN** | `80.246.31.202` |
| **Авторизация** | `daniililyuchenko23@gmail.com` (email-код) |

---

## Команды управления VPN

### Основные команды

```bash
# Статус VPN
adguardvpn-cli status

# Подключиться (самый быстрый сервер)
adguardvpn-cli connect -f -y

# Подключиться к конкретной локации
adguardvpn-cli connect -l "Germany" -y

# Отключиться
adguardvpn-cli disconnect

# Проверить IP через прокси
curl -s --socks5-hostname 127.0.0.1:1080 https://ifconfig.me
```

### Просмотр локаций

```bash
# Список всех локаций (sorted by ping)
adguardvpn-cli list-locations --count 10
```

### Конфигурация

```bash
# Показать текущую конфигурацию
adguardvpn-cli config show

# Сменить режим (tun/socks)
adguardvpn-cli config set-mode socks

# Установить порт SOCKS
adguardvpn-cli config set-socks-port 1080

# Включить/выключить автозапуск
adguardvpn-cli config set-autoconnect true
```

### Авторизация

```bash
# Войти в аккаунт
adguardvpn-cli login

# Выйти из аккаунта
adguardvpn-cli logout
```

---

## Управление Docker-контейнерами

### LithTGBot (Telegram-бот)

```bash
cd ~/my-project/Window\ of\ Light/LithTGBot

# Запустить все сервисы
docker compose up -d

# Остановить все сервисы
docker compose down

# Пересобрать и запустить
docker compose up -d --build

# Просмотр логов бота
docker compose logs bot -f

# Просмотр логов Celery Worker
docker compose logs celery_worker -f

# Просмотр логов Celery Beat
docker compose logs celery_beat -f

# Статус контейнеров
docker compose ps
```

### Window of Light (парсер + API)

```bash
cd ~/my-project/Window\ of\ Light/Window\ of\ Light

# Запустить
docker compose up -d

# Остановить
docker compose down

# Пересобрать и запустить
docker compose up -d --build

# Просмотр логов
docker compose logs -f

# Статус контейнеров
docker compose ps
```

---

## Проверка работоспособности

### Проверка VPN

```bash
# Проверить VPN статус
adguardvpn-cli status

# Проверить IP
curl -s --socks5-hostname 127.0.0.1:1080 https://ifconfig.me

# Проверить Telegram API через прокси
curl -s --socks5-hostname 127.0.0.1:1080 https://api.telegram.org/bot<TOKEN>/getMe
```

### Проверка контейнеров

```bash
# Все запущенные контейнеры
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Проверить подключение бота к Telegram
docker compose -f ~/my-project/Window\ of\ Light/LithTGBot/docker-compose.yml logs bot | grep -i "polling"

# Проверить подключение парсера к Telegram
docker compose -f ~/my-project/Window\ of\ Light/Window\ of\ Light/docker-compose.yml logs | grep -i "Telegram client initialised"
```

### Проверка регрессий после изменений логики бота и парсера

```bash
# Проверить, что бот оставляет только минимальную цену для повторяющегося цвета,
# корректно показывает флаги у обеих цен Best | Top и использует source timestamp для строки Собрано с временем UTC
cd ~/my-project/Window\ of\ Light
TELEGRAM_BOT_TOKEN=test-token pytest LithTGBot/tests/test_search_format.py

# Проверить каталог/поиск по PS5 Portal и PS5 DualShock,
# а также отсутствие отдельной кнопки gamepads в каталоге
TELEGRAM_BOT_TOKEN=test-token pytest LithTGBot/tests/test_catalog.py LithTGBot/tests/test_search_response.py

# Проверить коррекцию Top re:sale White -> Silver в парсере,
# а также нормализацию PS5 128GB/512GB -> PS5 Portal
pytest "Window of Light/tests/test_parsers.py"

# Проверить health/status API, которые использует админ-панель бота
pytest "Window of Light/tests/test_endpoints.py"
```

---

## Структура проекта

```
~/my-project/Window of Light/
├── LithTGBot/                    # Telegram-бот
│   ├── docker-compose.yml        # 3 сервиса: bot, celery_worker, celery_beat
│   ├── .env                      # Конфигурация (прокси, токены, БД)
│   ├── main.py                   # Точка входа бота
│   ├── config.py                 # Настройки (Settings)
│   ├── proxy_health_monitor.py   # Автоматический мониторинг прокси
│   ├── proxy-monitor.service     # systemd-сервис мониторинга
│   └── proxy_monitor.log         # Лог мониторинга
│
├── Window of Light/              # Парсер + API
│   ├── docker-compose.yml        # 1 сервис: app
│   ├── .env                      # Конфигурация (прокси, токены, БД)
│   ├── services/run_combined.py  # Точка входа + Redis cache для search/health
│   └── parser/universal_parser.py# Блочный парсер Telegram-постов
│
├── PROXY_GUIDE.md                # Эта инструкция
└── .env                          # Общие переменные (БД, Redis)
```

---

## Настройки прокси в .env файлах

### LithTGBot/.env

```bash
# Proxy (AdGuard VPN SOCKS5)
TELEGRAM_PROXY_TYPE=SOCKS5
TELEGRAM_PROXY_HOST=127.0.0.1
TELEGRAM_PROXY_PORT=1080
```

### Window of Light/.env

```bash
# Proxy (AdGuard VPN SOCKS5)
TELEGRAM_PROXY_HOST=127.0.0.1
TELEGRAM_PROXY_PORT=1080
TELEGRAM_PROXY_TYPE=SOCKS5
```

---

## Автозапуск VPN при старте сервера

Настроен через crontab:

```bash
# Просмотр crontab
crontab -l

# Результат:
# @reboot /home/dankl/start_adguard_vpn.sh
```

Скрипт автозапуска: `~/start_adguard_vpn.sh`

---

## Операционная панель администратора бота

В `LithTGBot` для пользователей из `ADMIN_USER_IDS` на стартовой reply-клавиатуре показывается кнопка `🔧 Админ`.

### Что показывает админ-панель

1. Сводку по боту: пользователи, поиски, активные отслеживания
2. Статус Window of Light API через `/status`
3. Health зависимостей через `/health` включая Redis cache WOL
4. Сведения о текущем прокси и MTProto-прокси
5. Локальные проверки `docker ps` и `adguardvpn-cli status`
6. Таблицу пользователей и их запросов за последние 24 часа

### Команды админа

```bash
/admin            # Список команд + полная сводка
/admin_stats      # Краткая статистика
/admin_top_day    # Топ запросов за 24 часа
/admin_top_week   # Топ запросов за 7 дней
/admin_top_month  # Топ запросов за 30 дней
/admin_users_day  # Пользователи, последние запросы, суточная активность
```

---

## Автоматический мониторинг прокси (Proxy Health Monitor)

### Обзор

Скрипт `proxy_health_monitor.py` — единый watchdog, который обеспечивает 24/7 работу всего проекта:
- **VPN/SOCKS5**: проверяет реальный трафик через прокси каждые 30 сек
- **Telegram-бот**: контролирует контейнер `lithtgbot`
- **Парсер (Window of Light)**: проверяет ingestion через `/status` API каждые 5 мин
- **Авторотация**: при проблемах автоматически переключает VPN-локацию

Для полностью автономной работы `proxy-monitor.service` должен быть установлен в systemd.

### Логика работы

1. **При старте**: проверяет SOCKS5-прокси. Если не работает — ротирует VPN по всем доступным локациям (sorted by ping)
2. **Каждые 30 сек**: проверяет порт 1080 → HTTP-запрос через SOCKS5 к `api.telegram.org`
3. **После 3 неудач подряд**: переподключает VPN к следующей локации из списка (19 локаций)
4. **При полном обрыве VPN** (порт не слушает): мгновенный `connect -f` к быстрому серверу
5. **Каждые 5 мин**: проверяет здоровье парсера через `http://127.0.0.1:8002/status`
6. **После восстановления**: перезапускает контейнеры `LithTGBot` и `Window of Light`
7. **Если все локации перепробованы**: ждёт 5 минут и начинает сначала

Дополнительно парсер (`run_combined.py`) имеет:
- Pre-flight проверку SOCKS5 перед попыткой подключения к Telegram
- Watchdog активности каналов: если 10 минут нет новых сообщений — переподключает клиент
- Экспоненциальный backoff при повторных ошибках прокси

### Файлы

| Файл | Назначение |
|------|-----------|
| `LithTGBot/proxy_health_monitor.py` | Скрипт мониторинга. Проверяет SOCKS5, контейнеры, парсер. |
| `LithTGBot/proxy-monitor.service` | systemd-сервис для автозапуска |
| `LithTGBot/proxy_monitor.log` | Лог мониторинга (ротация 5MB × 3) |
| `Window of Light/services/run_combined.py` | Ingestion с pre-flight проверкой прокси и watchdog |

### Установка systemd-сервиса

```bash
# Скопировать сервис
sudo cp "/home/dankl/my-project/Window of Light/LithTGBot/proxy-monitor.service" /etc/systemd/system/

# Перезагрузить systemd
sudo systemctl daemon-reload

# Запустить и добавить в автозагрузку
sudo systemctl enable --now proxy-monitor.service

# Проверить статус
sudo systemctl status proxy-monitor.service

# Просмотр логов
tail -f "/home/dankl/my-project/Window of Light/LithTGBot/proxy_monitor.log"
journalctl -u proxy-monitor.service -f
```

Примечание: код мониторинга уже готов, но если `proxy-monitor.service` не установлен в systemd, проверка каждые 30 секунд не будет запускаться автоматически после перезагрузки хоста.

### Ручной запуск (без systemd)

```bash
# Запустить в screen
screen -S proxy-monitor
python3 "/home/dankl/my-project/Window of Light/LithTGBot/proxy_health_monitor.py"
# Ctrl+A, D — отключиться от screen

# Или в tmux
tmux new -s proxy-monitor
python3 "/home/dankl/my-project/Window of Light/LithTGBot/proxy_health_monitor.py"
# Ctrl+B, D — отключиться
```

### Управление сервисом

```bash
# Статус
sudo systemctl status proxy-monitor.service

# Остановить
sudo systemctl stop proxy-monitor.service

# Перезапустить
sudo systemctl restart proxy-monitor.service

# Отключить автозапуск
sudo systemctl disable proxy-monitor.service

# Просмотр логов
journalctl -u proxy-monitor.service --since "1 hour ago"
```

### Параметры (в proxy_health_monitor.py)

| Параметр | Значение | Описание |
|----------|----------|----------|
| `CHECK_INTERVAL` | 30 сек | Интервал проверки прокси |
| `CHECK_TIMEOUT` | 15 сек | Таймаут запроса к Telegram API |
| `FAIL_THRESHOLD` | 3 | Неудачных проверок до ротации |
| `POST_ROTATION_WAIT` | 20 сек | Ожидание после ротации VPN |
| `ALL_SERVERS_EXHAUSTED_WAIT` | 300 сек | Ожидание после перебора всех серверов |
| `MAX_CONSECUTIVE_ROTATIONS` | 3 | Макс. циклов ротации перед длинной паузой |
| `PARSER_CHECK_INTERVAL` | 300 сек | Интервал проверки здоровья парсера |

### Логирование

Мониторинг пишет логи в два места:
- Файл: `LithTGBot/proxy_monitor.log` (ротация 5MB × 3 файла)
- stdout (для systemd → journalctl)

Пример лога:
```
2026-05-26 05:44:30 - INFO - === Proxy Health Monitor started ===
2026-05-26 05:44:30 - INFO - SOCKS: 127.0.0.1:1080 | Check interval: 30s | Fail threshold: 3
2026-05-26 05:44:31 - INFO - Available VPN locations (19): TALLINN, HELSINKI, COPENHAGEN...
2026-05-26 05:44:32 - INFO - Proxy healthy on startup
2026-05-26 05:45:02 - DEBUG - Proxy OK
2026-05-26 05:50:02 - INFO - Parser healthy: channels=2 msgs=23 parsed=588
2026-05-26 06:15:02 - WARNING - Proxy check FAILED (1/3) reason=http_request_failed
2026-05-26 06:15:32 - WARNING - Proxy check FAILED (2/3) reason=http_request_failed
2026-05-26 06:16:02 - WARNING - Proxy check FAILED (3/3) reason=http_request_failed
2026-05-26 06:16:02 - INFO - Rotating VPN: RIGA -> TALLINN (index 0)
2026-05-26 06:16:05 - INFO - VPN disconnected
2026-05-26 06:16:08 - INFO - VPN connected to TALLINN
2026-05-26 06:16:28 - INFO - Proxy OK after rotation to TALLINN
2026-05-26 06:16:28 - INFO - Bot containers restarted
2026-05-26 06:16:38 - INFO - Window of Light container restarted
```

---

## Решение проблем

### VPN не подключается

```bash
# Проверить статус
adguardvpn-cli status

# Переподключиться
adguardvpn-cli disconnect
adguardvpn-cli connect -f -y

# Проверить логи
cat ~/adguardvpn.log
```

### Бот не подключается к Telegram

```bash
# Проверить логи бота
docker compose -f ~/my-project/Window\ of\ Light/LithTGBot/docker-compose.yml logs bot --tail=50

# Проверить, работает ли прокси
curl -s --socks5-hostname 127.0.0.1:1080 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"

# Перезапустить контейнеры
docker compose -f ~/my-project/Window\ of\ Light/LithTGBot/docker-compose.yml restart
```

Если в логах есть `ProxyError: Connection refused by destination host`, это почти всегда означает, что SOCKS5 на `127.0.0.1:1080` не поднят или поднят, но сам VPN-туннель не маршрутизирует трафик. При установленном `proxy-monitor.service` этот сценарий должен отрабатываться автоматически. Для ручной диагностики:

```bash
# Проверить, слушает ли локальный SOCKS-порт
ss -ltnp | grep ':1080'

# Проверить выход через SOCKS
curl -s --socks5-hostname 127.0.0.1:1080 https://ifconfig.me

# Если порт слушает, но выхода нет — переподключить VPN к другой локации
adguardvpn-cli disconnect
adguardvpn-cli connect -l FRANKFURT -y
```

### Парсер не подключается к Telegram

```bash
# Проверить логи
docker compose -f ~/my-project/Window\ of\ Light/Window\ of\ Light/docker-compose.yml logs --tail=50

# Проверить, установлен ли PySocks
docker exec wol_app python3 -c "import socks; print('OK')"

# Перезапустить контейнер
docker compose -f ~/my-project/Window\ of\ Light/Window\ of\ Light/docker-compose.yml restart
```

Если ранее `Window of Light` падал целиком при недоступном Telegram/прокси на старте, теперь сервис стартует с доступным HTTP API и пытается переподключить ingestion в фоне каждые 15 секунд. Поэтому `curl http://127.0.0.1:8002/health` и `curl http://127.0.0.1:8002/status` должны оставаться доступны даже в момент проблем с MTProto.

### Парсер показывает старую дату данных

Если в Telegram-боте строка `Собрано:` зависла на старой дате, проверьте не только запуск контейнера, но и обработку новых и отредактированных сообщений.

```bash
# Проверить счетчики ingestion/parsing
curl -s http://127.0.0.1:8002/status

# Ожидаем рост counters: messages_sent / messages_parsed / parser_products

# Проверить, что клиент Telethon поднят и слушает новые посты
docker compose -f ~/my-project/Window\ of\ Light/Window\ of\ Light/docker-compose.yml logs --tail=100 | grep -i "Telegram client initialised"

# Если поставщик правит существующий пост, а не публикует новый,
# дата должна обновиться после события редактирования того же сообщения

# При необходимости перезапустить сервис WOL
docker compose -f ~/my-project/Window\ of\ Light/Window\ of\ Light/docker-compose.yml restart
```

Важно: теперь `Собрано:` в боте строится по `timestamp` из Window of Light, а не по `created_at` записи в БД, и выводится в формате `dd.mm.yyyy HH:MM UTC`. Для новых постов это `message.date`, для edited posts — `message.edit_date`. Если live ingestion не получает событие `NewMessage` или `MessageEdited`, дата закономерно не меняется. После успешного сохранения WOL также сбрасывает свой search-cache, поэтому бот не должен ждать TTL для обновления даты.

### Контейнеры не видят прокси

Убедитесь, что в `docker-compose.yml` добавлено:

```yaml
network_mode: host
```

Это позволяет контейнерам использовать прокси на хосте (127.0.0.1:1080).

### Top re:sale показывает `White` вместо `Silver`

В проекте добавлена автоматическая коррекция этого кейса для iPhone Pro/Pro Max:
- на этапе парсинга `Window of Light`
- на этапе нормализации перед сохранением
- на этапе формирования ответа в `LithTGBot`

Если в выдаче снова появился `White` для Pro-линейки из Top re:sale, сначала прогоните регрессионные тесты из секции выше и проверьте, не изменился ли ID канала Top re:sale.

---

## Технические детали

### Как работает прокси

1. **AdGuard VPN CLI** создаёт SOCKS5-прокси на `127.0.0.1:1080`
2. **Docker-контейнеры** используют `network_mode: host`, поэтому видят прокси
3. **LithTGBot** подключается к Telegram Bot API через `aiohttp_socks.ProxyConnector`
4. **Window of Light** подключается к Telegram MTProto через `PySocks`

### Библиотеки для прокси

| Проект | Библиотека | Назначение |
|--------|------------|------------|
| LithTGBot | `aiohttp_socks` | SOCKS5 для aiogram (Telegram Bot API) |
| Window of Light | `PySocks` + `python-socks` | SOCKS5 для Telethon (Telegram MTProto) |

### Docker network_mode: host

Все контейнеры используют `network_mode: host`:
- Контейнер видит прокси на `127.0.0.1:1080`
- Не нужно маппить порты
- Контейнер использует сеть хоста

---

## Обновление VPN

```bash
# Проверить обновления
adguardvpn-cli check-update

# Обновить
adguardvpn-cli update -y
```

---

## Контакты

- **Логин AdGuard**: your-email@example.com
- **Telegram Bot**: @YourMonitorBot
- **База данных**: PostgreSQL на <DB_HOST>
- **Redis**: <REDIS_HOST>:6379

---

Примечание: если поставщик меняет цену редактированием уже существующего поста, `Window of Light` теперь повторно парсит это сообщение и обновляет товар по тому же `message_link`, чтобы `LithTGBot` не показывал старую дату.

---

*Последнее обновление: 19 мая 2026. Актуализировано под мониторинг VPN каждые 30 секунд, автоматический рестарт `LithTGBot` и `Window of Light` после восстановления прокси, диагностику `ProxyError`, обязательную установку `proxy-monitor.service`, безопасную проверку `getMe` без хранения токена в документе и фоновый рестарт Telegram ingestion в Window of Light.*

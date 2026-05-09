FROM mirror.gcr.io/library/python:3.10-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev tzdata && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Moscow

# Копирование и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY . .

# Права на запуск
RUN chmod +x main.py

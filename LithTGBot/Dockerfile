FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev tzdata && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --create-home --shell /bin/sh app

ENV TZ=Europe/Moscow

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/media /app/sessions && chown -R app:app /app

USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD test -f /tmp/healthcheck || touch /tmp/healthcheck

CMD ["python3", "main.py"]

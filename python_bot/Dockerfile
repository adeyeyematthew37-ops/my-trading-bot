# ─────────────────────────────────────────────────────────────
#  Dockerfile — CryptoBot Python Telegram Trading Bot
# ─────────────────────────────────────────────────────────────

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc libssl-dev libffi-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY python_bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY python_bot/ /app/

# /data is where the SQLite DB lives.
# On Railway: add a Volume mounted at /data so data survives redeploys.
# Railway dashboard → your service → Storage → Add Volume → mount at /data
RUN mkdir -p /data /app/data

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Default DB path — override with DB_PATH=/data/bot.db env var on Railway
ENV DB_PATH=/data/bot.db
ENV PORT=8080

EXPOSE 8080

CMD ["python", "/app/bot.py"]

# ─────────────────────────────────────────────────────────────
#  Dockerfile — CryptoBot Python Telegram Trading Bot
#  Railway builds this from the repo ROOT, so COPY paths
#  are relative to the repo root (not this file's location)
# ─────────────────────────────────────────────────────────────

FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libssl-dev \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache — faster rebuilds)
COPY python_bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy all bot source files
COPY python_bot/ /app/

# Persistent data directory for SQLite DB
RUN mkdir -p /app/data

# ── Environment Variables ─────────────────────────────────────
# Set these in Railway dashboard → Variables tab
#
# REQUIRED:
#   BOT_TOKEN          ← your Telegram bot token from @BotFather
#
# OPTIONAL:
#   ONEINCH_API_KEY    ← better swap routing (portal.1inch.dev)
#   COINGECKO_API_KEY  ← higher price rate limits (coingecko.com/api)
#   ETH_RPC_URL / BSC_RPC_URL / POLYGON_RPC_URL etc
# ─────────────────────────────────────────────────────────────

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DB_PATH=/app/data/bot.db
ENV PORT=8080

EXPOSE 8080

CMD ["python", "/app/bot.py"]

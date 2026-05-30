# ─────────────────────────────────────────────────────────────
#  Dockerfile — CryptoBot Python Telegram Trading Bot
#  Works on: Railway, Render, DigitalOcean, any VPS, locally
# ─────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libssl-dev \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (layer caching — faster rebuilds)
COPY python_bot/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the entire python_bot source
COPY python_bot/ .

# Create data directory for SQLite database
RUN mkdir -p /app/data

# ─────────────────────────────────────────────────────────────
#  ENVIRONMENT VARIABLES
#  Set these in Railway/Render/your platform dashboard.
#  DO NOT hardcode secrets here.
#
#  Required:
#    BOT_TOKEN       — from @BotFather on Telegram
#
#  Optional (improves swap routing & price limits):
#    ONEINCH_API_KEY    — from portal.1inch.dev
#    COINGECKO_API_KEY  — from coingecko.com/api
#
#  Custom RPC URLs (optional, public ones used by default):
#    ETH_RPC_URL
#    BSC_RPC_URL
#    POLYGON_RPC_URL
#    ARBITRUM_RPC_URL
#    BASE_RPC_URL
#    AVAX_RPC_URL
#    SOLANA_RPC_URL
# ─────────────────────────────────────────────────────────────

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DB_PATH=/app/data/bot.db

# Expose nothing — bot uses Telegram polling, no inbound port needed
# (Railway requires a PORT for health checks, so we expose a dummy one)
EXPOSE 8080

# Run the bot
CMD ["python", "bot.py"]

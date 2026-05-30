# config/secrets.example.py
# ─────────────────────────────────────────────────────────────
#  Copy this file to secrets.py and fill in your values.
#  secrets.py is gitignored and will NEVER be committed.
# ─────────────────────────────────────────────────────────────

# 1. Get from @BotFather on Telegram → /newbot
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"

# ── Everything below is optional ─────────────────────────────

ENCRYPTION_KEY = None  # Auto-generated on first run — leave as None

RPC_URLS = {
    "ethereum":  "https://eth.llamarpc.com",
    "bsc":       "https://bsc-dataseed1.binance.org",
    "polygon":   "https://polygon.llamarpc.com",
    "arbitrum":  "https://arb1.arbitrum.io/rpc",
    "base":      "https://mainnet.base.org",
    "avalanche": "https://api.avax.network/ext/bc/C/rpc",
    "solana":    "https://api.mainnet-beta.solana.com",
}

# Optional: better swap routing (free at portal.1inch.dev)
ONEINCH_API_KEY = ""

# Optional: higher price API limits (free at coingecko.com/api)
COINGECKO_API_KEY = ""

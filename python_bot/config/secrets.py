# ============================================================
#  config/secrets.py
#
#  LOCAL: Set BOT_TOKEN directly below
#  RAILWAY / DOCKER: Set BOT_TOKEN as an environment variable
#                    in your platform dashboard — no file edit needed
# ============================================================

import os

# ── Bot Token ─────────────────────────────────────────────────
# Railway/Render/Docker: set BOT_TOKEN env var in dashboard
# Local: paste your token from @BotFather below
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")

# ── Encryption Key ────────────────────────────────────────────
# Auto-generated and stored in DB on first run — leave as None
# If deploying to Railway with a volume, set this as an env var
# so your wallets survive redeployments:
#   ENCRYPTION_KEY=your_32_byte_hex_string
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", None)

# ── RPC Endpoints ─────────────────────────────────────────────
# Public free endpoints used by default.
# Override any via env vars for better reliability:
#   ETH_RPC_URL=https://mainnet.infura.io/v3/YOUR_KEY
RPC_URLS = {
    "ethereum":  os.environ.get("ETH_RPC_URL",      "https://eth.llamarpc.com"),
    "bsc":       os.environ.get("BSC_RPC_URL",      "https://bsc-dataseed1.binance.org"),
    "polygon":   os.environ.get("POLYGON_RPC_URL",  "https://polygon.llamarpc.com"),
    "arbitrum":  os.environ.get("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc"),
    "base":      os.environ.get("BASE_RPC_URL",     "https://mainnet.base.org"),
    "avalanche": os.environ.get("AVAX_RPC_URL",     "https://api.avax.network/ext/bc/C/rpc"),
    "solana":    os.environ.get("SOLANA_RPC_URL",   "https://api.mainnet-beta.solana.com"),
}

# ── Optional API Keys ─────────────────────────────────────────
# Set as env vars in Railway dashboard for better performance
ONEINCH_API_KEY   = os.environ.get("ONEINCH_API_KEY",   "")
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")

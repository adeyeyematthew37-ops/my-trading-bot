# utils/prices.py  —  Real-time price data from multiple sources

import requests
import time
from functools import lru_cache
from config.secrets import COINGECKO_API_KEY

_cache: dict = {}
CACHE_TTL = 30  # seconds

def _cached(key, fetch_fn):
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < CACHE_TTL:
        return _cache[key]["val"]
    val = fetch_fn()
    if val is not None:
        _cache[key] = {"val": val, "ts": now}
    return val

def get_price_coingecko(coin_id: str) -> dict | None:
    """Get price from CoinGecko by coin ID (e.g. 'ethereum', 'solana')."""
    def fetch():
        try:
            headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"},
                headers=headers, timeout=8
            )
            data = r.json().get(coin_id)
            if data:
                return {"price": data["usd"], "change24h": data.get("usd_24h_change", 0), "source": "coingecko"}
        except Exception:
            pass
        return None
    return _cached(f"cg_{coin_id}", fetch)

def get_price_dexscreener(chain: str, token_address: str) -> dict | None:
    """Get price from DexScreener — works for any token contract address."""
    chain_map = {
        "ethereum": "ethereum", "bsc": "bsc", "polygon": "polygon",
        "arbitrum": "arbitrum", "base": "base", "avalanche": "avalanche", "solana": "solana"
    }
    dex_chain = chain_map.get(chain, chain)
    def fetch():
        try:
            r = requests.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{token_address}",
                timeout=8
            )
            pairs = r.json().get("pairs") or []
            chain_pairs = [p for p in pairs if p.get("chainId") == dex_chain]
            if not chain_pairs:
                chain_pairs = pairs
            if not chain_pairs:
                return None
            pair = sorted(chain_pairs, key=lambda x: x.get("liquidity", {}).get("usd", 0), reverse=True)[0]
            return {
                "price": float(pair.get("priceUsd", 0)),
                "change24h": pair.get("priceChange", {}).get("h24", 0),
                "volume24h": pair.get("volume", {}).get("h24", 0),
                "liquidity": pair.get("liquidity", {}).get("usd", 0),
                "dex": pair.get("dexId", ""),
                "pair": pair.get("pairAddress", ""),
                "base_token": pair.get("baseToken", {}),
                "source": "dexscreener"
            }
        except Exception:
            pass
        return None
    return _cached(f"dex_{chain}_{token_address}", fetch)

def get_native_prices() -> dict:
    """Get USD prices for all native chain tokens."""
    ids = "ethereum,binancecoin,matic-network,avalanche-2,solana"
    try:
        headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
            headers=headers, timeout=8
        )
        return r.json()
    except Exception:
        return {}

def search_token(query: str) -> list:
    """Search CoinGecko for tokens by name/symbol."""
    try:
        headers = {"x-cg-demo-api-key": COINGECKO_API_KEY} if COINGECKO_API_KEY else {}
        r = requests.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": query}, headers=headers, timeout=8
        )
        return r.json().get("coins", [])[:5]
    except Exception:
        return []

def get_token_price(chain: str, token_address: str, coingecko_id: str = None) -> dict | None:
    """Universal price getter — tries CoinGecko first, falls back to DexScreener."""
    if coingecko_id:
        result = get_price_coingecko(coingecko_id)
        if result:
            return result
    return get_price_dexscreener(chain, token_address)

def fmt_price(price) -> str:
    if price is None:
        return "N/A"
    p = float(price)
    if p == 0:
        return "$0.00"
    if p < 0.000001:
        return f"${p:.2e}"
    if p < 0.01:
        return f"${p:.8f}"
    if p < 1:
        return f"${p:.6f}"
    if p < 1000:
        return f"${p:.4f}"
    return f"${p:,.2f}"

def fmt_change(change) -> str:
    if change is None:
        return ""
    c = float(change)
    arrow = "📈" if c >= 0 else "📉"
    sign = "+" if c >= 0 else ""
    return f"{arrow} {sign}{c:.2f}%"


# ── Token Deep Info (Fluxbot-style panel data) ────────────────────────────────

def get_token_full_info(chain: str, token_address: str) -> dict | None:
    """
    Fetch full token data from DexScreener: price, mcap, volume,
    liquidity, age, pair info — everything needed for the trade panel.
    """
    chain_map = {
        "ethereum":"ethereum","bsc":"bsc","polygon":"polygon",
        "arbitrum":"arbitrum","base":"base","avalanche":"avalanche","solana":"solana"
    }
    dex_chain = chain_map.get(chain, chain)
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{token_address}",
            timeout=10
        )
        pairs = r.json().get("pairs") or []
        if not pairs:
            return None

        chain_pairs = [p for p in pairs if p.get("chainId") == dex_chain]
        if not chain_pairs:
            chain_pairs = pairs

        # Pick most liquid pair
        pair = sorted(chain_pairs,
                      key=lambda x: x.get("liquidity",{}).get("usd",0),
                      reverse=True)[0]

        price_usd  = float(pair.get("priceUsd", 0) or 0)
        mcap       = pair.get("marketCap") or pair.get("fdv") or 0
        volume24h  = pair.get("volume",{}).get("h24", 0) or 0
        liquidity  = pair.get("liquidity",{}).get("usd", 0) or 0
        change1h   = pair.get("priceChange",{}).get("h1", 0) or 0
        change24h  = pair.get("priceChange",{}).get("h24", 0) or 0
        change5m   = pair.get("priceChange",{}).get("m5", 0) or 0
        buys24h    = pair.get("txns",{}).get("h24",{}).get("buys", 0) or 0
        sells24h   = pair.get("txns",{}).get("h24",{}).get("sells", 0) or 0
        pair_addr  = pair.get("pairAddress","")
        dex_name   = pair.get("dexId","")
        base_token = pair.get("baseToken",{})
        quote_token= pair.get("quoteToken",{})
        created_at = pair.get("pairCreatedAt")  # epoch ms

        # Age in hours
        age_hours = None
        if created_at:
            import time
            age_hours = (time.time() - created_at/1000) / 3600

        return {
            "price":        price_usd,
            "mcap":         float(mcap),
            "volume24h":    float(volume24h),
            "liquidity":    float(liquidity),
            "change5m":     float(change5m),
            "change1h":     float(change1h),
            "change24h":    float(change24h),
            "buys24h":      int(buys24h),
            "sells24h":     int(sells24h),
            "pair_address": pair_addr,
            "dex":          dex_name,
            "base_symbol":  base_token.get("symbol","?"),
            "base_name":    base_token.get("name","?"),
            "quote_symbol": quote_token.get("symbol","?"),
            "age_hours":    age_hours,
            "source":       "dexscreener",
        }
    except Exception as e:
        return None


def rug_check(chain: str, token_address: str) -> dict:
    """
    Basic rug-pull risk check using DexScreener data.
    Returns a risk score and list of warning flags.
    """
    info = get_token_full_info(chain, token_address)
    if not info:
        return {"score": "UNKNOWN", "warnings": ["Could not fetch token data"], "info": {}}

    warnings = []
    score_pts = 0  # higher = riskier

    # Very low liquidity
    if info["liquidity"] < 5000:
        warnings.append("🚨 Liquidity under $5k — easy to rug")
        score_pts += 40
    elif info["liquidity"] < 25000:
        warnings.append("⚠️ Low liquidity ($25k) — exit may be hard")
        score_pts += 20

    # Very new token
    if info["age_hours"] is not None:
        if info["age_hours"] < 1:
            warnings.append("🚨 Token is less than 1 hour old — extreme risk")
            score_pts += 35
        elif info["age_hours"] < 24:
            warnings.append(f"⚠️ Token only {info['age_hours']:.1f}h old — new and unproven")
            score_pts += 15

    # Low market cap
    if info["mcap"] and info["mcap"] < 10000:
        warnings.append("⚠️ Market cap under $10k — very easy to manipulate")
        score_pts += 20
    elif info["mcap"] and info["mcap"] < 50000:
        warnings.append("⚠️ Market cap under $50k — high manipulation risk")
        score_pts += 10

    # Extreme buy/sell imbalance (possible pump)
    total_txns = info["buys24h"] + info["sells24h"]
    if total_txns > 0:
        buy_ratio = info["buys24h"] / total_txns
        if buy_ratio > 0.85:
            warnings.append("📡 Unusual buy pressure (>85% buys) — possible pump")
            score_pts += 15

    # No volume
    if info["volume24h"] < 1000:
        warnings.append("⚠️ Almost no trading volume — illiquid")
        score_pts += 15

    # Determine score
    if score_pts == 0:
        score = "LOW ✅"
    elif score_pts <= 20:
        score = "MEDIUM ⚠️"
    elif score_pts <= 45:
        score = "HIGH 🔴"
    else:
        score = "EXTREME 🚨"

    if not warnings:
        warnings.append("✅ No major red flags detected")

    return {"score": score, "warnings": warnings, "info": info, "points": score_pts}


def fmt_mcap(val: float) -> str:
    if not val: return "N/A"
    if val >= 1_000_000_000: return f"${val/1_000_000_000:.2f}B"
    if val >= 1_000_000:     return f"${val/1_000_000:.2f}M"
    if val >= 1_000:         return f"${val/1_000:.2f}k"
    return f"${val:.2f}"


def get_chart_url(chain: str, token_address: str) -> str:
    chain_map = {
        "ethereum":"ethereum","bsc":"bsc","polygon":"polygon",
        "arbitrum":"arbitrum","base":"base","avalanche":"avalanche","solana":"solana"
    }
    dc = chain_map.get(chain, chain)
    return f"https://dexscreener.com/{dc}/{token_address}"

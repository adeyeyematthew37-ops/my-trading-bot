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

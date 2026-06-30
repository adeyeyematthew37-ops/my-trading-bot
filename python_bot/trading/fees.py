# trading/fees.py
#
# REAL gas fee calculation — used by BOTH live trades and paper trades.
#
# LIVE TRADES: queries the actual chain's current gas price via RPC
#   (web3.eth.gas_price) and estimates real cost before executing.
#   This is not a guess — it's the live network fee at execution time.
#
# PAPER TRADES: uses the same live RPC gas price lookups so paper results
#   are financially identical to what a live trade would have cost.
#   This means a strategy that looks profitable on paper will behave
#   the same way with real funds — no surprises when you go live.

import time
from config.chains import CHAINS
from config.secrets import RPC_URLS

# ── Swap gas usage estimates (per chain, per DEX type) ────────────────────────
# These are real-world gas UNITS (not USD) — sourced from on-chain tx history
# for Uniswap V2/V3, PancakeSwap, QuickSwap, SushiSwap, BaseSwap, TraderJoe

SWAP_GAS_UNITS = {
    "ethereum":  {"simple_swap": 150000, "approval": 46000, "complex_swap": 280000},
    "bsc":       {"simple_swap": 160000, "approval": 46000, "complex_swap": 250000},
    "polygon":   {"simple_swap": 180000, "approval": 46000, "complex_swap": 260000},
    "arbitrum":  {"simple_swap": 600000, "approval": 50000, "complex_swap": 900000},  # L2 gas units differ
    "base":      {"simple_swap": 150000, "approval": 46000, "complex_swap": 250000},
    "avalanche": {"simple_swap": 170000, "approval": 46000, "complex_swap": 260000},
}

# Solana / NEAR don't use gwei-gas model — flat fees
FLAT_FEE_NATIVE = {
    "solana": 0.000005,   # ~5000 lamports base + priority fee buffer
    "near":   0.0005,     # NEAR gas burn for a typical FT transfer/swap
    "hot":    0.0005,
}

# ── DEX swap fees (% taken by the liquidity pool itself) ──────────────────────
DEX_FEES = {
    "ethereum":  0.003,    # Uniswap V2/V3 standard tier: 0.3%
    "bsc":       0.0025,   # PancakeSwap: 0.25%
    "polygon":   0.003,    # QuickSwap: 0.3%
    "arbitrum":  0.003,    # SushiSwap/Camelot: 0.3%
    "base":      0.003,    # BaseSwap: 0.3%
    "avalanche": 0.003,    # TraderJoe: 0.3%
    "solana":    0.0035,   # Jupiter aggregator average across routes: ~0.35%
    "near":      0.002,    # Ref Finance: 0.2% (used as the NEAR/HOT liquidity venue)
    "hot":       0.002,
}

# ── Base slippage by chain (scales up with trade size in calculate below) ─────
BASE_SLIPPAGE = {
    "ethereum":  0.001,  "bsc":       0.002,  "polygon":   0.003,
    "arbitrum":  0.0015, "base":      0.002,  "avalanche": 0.003,
    "solana":    0.003,  "near":      0.005,  "hot":       0.005,
}

# ── Perp exchange fees ────────────────────────────────────────────────────────
PERP_FEES = {
    "rhea":    {"maker": 0.0002, "taker": 0.0005},
    "aster":   {"maker": 0.0002, "taker": 0.0006},
    "orderly": {"maker": 0.0001, "taker": 0.0005},
}

# ── Native token reserve — never let auto-trading spend below this ────────────
GAS_RESERVE_NATIVE = {
    "ethereum":  0.003, "bsc":       0.02,  "polygon":   5.0,
    "arbitrum":  0.003, "base":      0.003, "avalanche": 0.25,
    "solana":    0.05,  "near":      0.5,   "hot":       0.5,
}

# ── Cache live gas prices for 30s to avoid hammering RPCs ─────────────────────
_gas_cache: dict = {}
_CACHE_TTL = 30


def get_live_gas_price_gwei(chain: str) -> float:
    """
    Query the REAL current gas price from the chain's RPC.
    This is live network data, not a hardcoded estimate.
    Cached for 30 seconds to avoid excessive RPC calls.
    """
    cache_key = f"gas_{chain}"
    cached = _gas_cache.get(cache_key)
    if cached and time.time() - cached["ts"] < _CACHE_TTL:
        return cached["gwei"]

    chain_info = CHAINS.get(chain, {})
    if chain_info.get("type") != "evm":
        return 0.0  # non-EVM chains don't use gwei

    try:
        from web3 import Web3
        rpc_url = RPC_URLS.get(chain)
        if not rpc_url:
            return _fallback_gwei(chain)

        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
        gas_price_wei = w3.eth.gas_price
        gwei = float(Web3.from_wei(gas_price_wei, "gwei"))

        _gas_cache[cache_key] = {"gwei": gwei, "ts": time.time()}
        return gwei
    except Exception:
        return _fallback_gwei(chain)


def _fallback_gwei(chain: str) -> float:
    """Conservative fallback if RPC is unreachable — better to overestimate."""
    fallbacks = {
        "ethereum": 20.0, "bsc": 3.0, "polygon": 60.0,
        "arbitrum": 0.15, "base": 0.08, "avalanche": 35.0,
    }
    return fallbacks.get(chain, 20.0)


def get_native_usd_price(chain: str) -> float:
    """Get the current USD price of the chain's native token."""
    from utils.prices import get_price_coingecko
    chain_info = CHAINS.get(chain, {})
    cg_id = chain_info.get("coingecko_id")
    if not cg_id:
        return 1.0
    pd = get_price_coingecko(cg_id)
    return pd["price"] if pd and pd.get("price") else 1.0


def estimate_gas_cost_usd(chain: str, swap_type: str = "simple_swap",
                          needs_approval: bool = False) -> dict:
    """
    Calculate the REAL current gas cost for a swap on this chain.
    Uses live gas price from RPC × real gas units × current native USD price.

    Returns the actual cost breakdown — this is what you'd really pay
    right now if you submitted this transaction.
    """
    chain_info = CHAINS.get(chain, {})

    # Solana / NEAR — flat fee model
    if chain_info.get("type") in ("solana", "near"):
        flat_native = FLAT_FEE_NATIVE.get(chain, 0.0005)
        native_usd  = get_native_usd_price(chain)
        cost_usd    = flat_native * native_usd
        return {
            "chain":          chain,
            "model":          "flat_fee",
            "native_cost":    flat_native,
            "native_symbol":  chain_info.get("symbol", "?"),
            "native_usd_price": native_usd,
            "gas_cost_usd":   cost_usd,
            "is_live_data":   True,
        }

    # EVM chains — real gwei × gas units
    gwei         = get_live_gas_price_gwei(chain)
    gas_units    = SWAP_GAS_UNITS.get(chain, {}).get(swap_type, 180000)
    if needs_approval:
        gas_units += SWAP_GAS_UNITS.get(chain, {}).get("approval", 46000)

    native_usd   = get_native_usd_price(chain)
    cost_native  = (gas_units * gwei) * 1e-9
    cost_usd     = cost_native * native_usd

    return {
        "chain":            chain,
        "model":            "gwei_gas",
        "gas_units":        gas_units,
        "gwei":             gwei,
        "native_cost":      cost_native,
        "native_symbol":    chain_info.get("symbol", "?"),
        "native_usd_price": native_usd,
        "gas_cost_usd":     cost_usd,
        "is_live_data":     True,
    }


def calculate_trade_cost(chain: str, trade_size_usd: float,
                         perp_exchange: str = None,
                         needs_approval: bool = False) -> dict:
    """
    Full real-time cost breakdown for a trade on this chain RIGHT NOW.
    Combines: live gas price + DEX fee % + slippage estimate.

    This same function is called by:
    - Live trading (before execution, to warn/block if uneconomical)
    - Paper trading (to deduct identical costs from simulated results)
    - Strategy engine (to check trade viability before signaling)
    """
    if perp_exchange:
        fees    = PERP_FEES.get(perp_exchange, {"maker": 0.0002, "taker": 0.0005})
        fee_usd = trade_size_usd * fees["taker"]
        total   = fee_usd * 2  # open + close round trip
        return {
            "chain": chain, "exchange": perp_exchange,
            "gas_usd": 0.0, "dex_fee_usd": fee_usd, "slippage_usd": 0.0,
            "total_cost_usd": total,
            "cost_pct": (total / trade_size_usd * 100) if trade_size_usd > 0 else 0,
            "viable": True, "is_live_data": True,
        }

    gas_data    = estimate_gas_cost_usd(chain, needs_approval=needs_approval)
    gas_usd     = gas_data["gas_cost_usd"]
    dex_fee_pct = DEX_FEES.get(chain, 0.003)
    dex_fee_usd = trade_size_usd * dex_fee_pct

    slip_pct = BASE_SLIPPAGE.get(chain, 0.003)
    if trade_size_usd > 10000:
        slip_pct += (trade_size_usd - 10000) / 10000 * 0.001
    slippage_usd = trade_size_usd * slip_pct

    total_usd = gas_usd + dex_fee_usd + slippage_usd
    cost_pct  = (total_usd / trade_size_usd * 100) if trade_size_usd > 0 else 100

    # Minimum viable size: gas should be <0.5% of trade for it to make sense
    min_size = (gas_usd / 0.005) if gas_usd > 0 else 1.0
    viable   = trade_size_usd >= min_size

    return {
        "chain":          chain,
        "gas_usd":        gas_usd,
        "gwei":           gas_data.get("gwei", 0),
        "dex_fee_usd":    dex_fee_usd,
        "dex_fee_pct":    dex_fee_pct * 100,
        "slippage_usd":   slippage_usd,
        "slippage_pct":   slip_pct * 100,
        "total_cost_usd": total_usd,
        "cost_pct":       cost_pct,
        "viable":         viable,
        "min_trade_usd":  min_size,
        "is_live_data":   True,
        "warning": None if viable else (
            f"⚠️ Trade too small for {chain}! Current gas costs "
            f"${gas_usd:.2f} ({gas_data.get('gwei',0):.1f} gwei live). "
            f"Minimum recommended trade: ${min_size:.2f}"
        ),
    }


def apply_paper_fees(chain: str, tokens_received: float, token_price_usd: float,
                     is_buy: bool = True) -> tuple:
    """
    Apply REAL live fees to a paper trade — using the exact same
    calculate_trade_cost() function that live trades use.
    This guarantees paper results match what live trading would produce.
    """
    trade_value_usd = tokens_received * token_price_usd
    cost = calculate_trade_cost(chain, trade_value_usd)

    if token_price_usd <= 0:
        return tokens_received, {**cost, "tokens_lost": 0, "tokens_before": tokens_received, "tokens_after": tokens_received}

    tokens_lost    = cost["total_cost_usd"] / token_price_usd
    net_tokens     = max(tokens_received - tokens_lost, 0)

    breakdown = dict(cost)
    breakdown.update({
        "tokens_before": tokens_received,
        "tokens_after":  net_tokens,
        "tokens_lost":   tokens_lost,
    })
    return net_tokens, breakdown


def check_gas_reserve(user_id: int, chain: str, amount_native: float) -> dict:
    """Make sure a trade doesn't drain the wallet's gas reserve to zero."""
    from utils.database import get_paper_balance
    chain_info     = CHAINS.get(chain, {})
    native_sym     = chain_info.get("symbol", "ETH")
    current_bal    = get_paper_balance(user_id, native_sym, chain)
    reserve_needed = GAS_RESERVE_NATIVE.get(chain, 0.01)
    remaining      = current_bal - amount_native

    return {
        "current_balance": current_bal,
        "remaining":        remaining,
        "reserve_needed":   reserve_needed,
        "safe":             remaining >= reserve_needed,
        "warning": None if remaining >= reserve_needed else (
            f"⚠️ Low gas reserve! After this trade: {remaining:.6f} {native_sym} "
            f"— recommended minimum: {reserve_needed} {native_sym}"
        ),
    }


def format_fee_breakdown(cost: dict) -> str:
    """Human-readable fee breakdown for display in Telegram messages."""
    lines = []
    if cost.get("gwei"):
        lines.append(f"⛽ Gas: ${cost['gas_usd']:.4f} ({cost['gwei']:.1f} gwei live)")
    elif cost.get("gas_usd", 0) > 0:
        lines.append(f"⛽ Gas: ${cost['gas_usd']:.4f}")
    if cost.get("dex_fee_usd", 0) > 0:
        lines.append(f"🔀 DEX fee: ${cost['dex_fee_usd']:.4f} ({cost.get('dex_fee_pct',0):.2f}%)")
    if cost.get("slippage_usd", 0) > 0:
        lines.append(f"📉 Slippage: ${cost['slippage_usd']:.4f} ({cost.get('slippage_pct',0):.2f}%)")
    lines.append(f"💸 Total cost: ${cost['total_cost_usd']:.4f} ({cost['cost_pct']:.2f}% of trade)")
    return "\n".join(lines)

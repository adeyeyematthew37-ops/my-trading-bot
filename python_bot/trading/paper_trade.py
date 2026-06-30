# trading/paper_trade.py  —  Paper trading with REAL costs simulated
#
# Every paper trade deducts the same gas + DEX fee + slippage that a live
# trade on this chain would cost RIGHT NOW (live RPC gas price, not a
# guess). This means: if a strategy looks profitable on paper, it has
# already proven it can survive real trading costs on that specific chain.

from utils import database as db
from utils.prices import get_token_price, get_price_coingecko, get_token_full_info, fmt_price, fmt_mcap
from config.chains import CHAINS
from trading.fees import apply_paper_fees, check_gas_reserve, calculate_trade_cost


def _get_native_usd(chain: str) -> float:
    chain_info = CHAINS.get(chain, {})
    cg_id = chain_info.get("coingecko_id")
    if not cg_id:
        return 1.0
    pd = get_price_coingecko(cg_id)
    return pd["price"] if pd else 1.0


def paper_buy(user_id: int, chain: str, token_address: str, token_symbol: str,
              amount_native: float, strategy_id: int = None,
              coingecko_id: str = None) -> dict:
    """
    Paper buy with full position tracking for accurate PnL.
    Records entry price so we can compute unrealized PnL later.
    """
    chain_info = CHAINS.get(chain)
    if not chain_info:
        raise ValueError(f"Unknown chain: {chain}")

    native_symbol = chain_info["symbol"]

    # Normalize token symbol — always uppercase, strip whitespace
    # Use token address short form if symbol is generic
    if not token_symbol or token_symbol.upper() in ("TOKEN", "UNKNOWN", ""):
        token_symbol = token_address[:8].upper()
    token_symbol = token_symbol.upper().strip()

    # Fetch live price — try DexScreener for any unknown token
    price_data = get_token_price(chain, token_address, coingecko_id)
    if not price_data or not price_data.get("price"):
        from utils.prices import get_token_full_info
        info = get_token_full_info(chain, token_address)
        if info and info.get("price"):
            price_data = {"price": info["price"]}
            token_symbol = info.get("base_symbol", token_symbol).upper()
        else:
            raise ValueError(f"Could not fetch price for {token_symbol}")

    token_price_usd = price_data["price"]
    native_usd      = _get_native_usd(chain)
    usd_spent       = amount_native * native_usd
    tokens_raw      = usd_spent / token_price_usd  # before fees

    # ── Apply REAL fees: same gas/DEX/slippage a live trade would pay ────────
    gas_reserve = check_gas_reserve(user_id, chain, amount_native)
    tokens_received, fee_breakdown = apply_paper_fees(
        chain, tokens_raw, token_price_usd, is_buy=True
    )
    total_cost_usd = fee_breakdown["total_cost_usd"]
    # ─────────────────────────────────────────────────────────────────────────

    # Deduct native balance
    db.subtract_paper_balance(user_id, native_symbol, chain, amount_native)
    # Add token balance (NET of fees, same as a real swap) — UPPER normalized
    db.add_paper_balance(user_id, token_symbol, chain, tokens_received)

    # Save trade record
    trade_id = db.save_trade({
        "user_id":       user_id,
        "chain":         chain,
        "trade_type":    "buy",
        "mode":          "paper",
        "token_in":      "native",
        "token_out":     token_address,
        "symbol_in":     native_symbol,
        "symbol_out":    token_symbol,
        "amount_in":     amount_native,
        "amount_out":    tokens_received,
        "price_at_trade":token_price_usd,
        "entry_price":   token_price_usd,
        "status":        "success",
        "strategy":      str(strategy_id) if strategy_id else None,
    })

    # Open position record — cost basis includes the fees just paid,
    # so unrealized PnL reflects the TRUE breakeven point
    effective_entry = (usd_spent + total_cost_usd) / tokens_received if tokens_received > 0 else token_price_usd
    pos_id = db.open_position({
        "user_id":         user_id,
        "strategy_id":     strategy_id,
        "chain":           chain,
        "mode":            "paper",
        "token_address":   token_address,
        "token_symbol":    token_symbol.upper(),
        "qty":             tokens_received,
        "entry_price_usd": effective_entry,
        "entry_native":    amount_native,
        "entry_usd":       usd_spent + total_cost_usd,
    })

    return {
        "trade_id":      trade_id,
        "position_id":   pos_id,
        "spent":         amount_native,
        "spent_symbol":  native_symbol,
        "received":      tokens_received,
        "received_symbol": token_symbol,
        "price":         token_price_usd,
        "usd_value":     usd_spent,
        "native_usd":    native_usd,
        "fees": {
            "gas_usd":        fee_breakdown["gas_usd"],
            "dex_fee_usd":    fee_breakdown["dex_fee_usd"],
            "slippage_usd":   fee_breakdown["slippage_usd"],
            "total_cost_usd": total_cost_usd,
            "cost_pct":       fee_breakdown["cost_pct"],
            "gwei":           fee_breakdown.get("gwei", 0),
        },
        "gas_warning": gas_reserve.get("warning"),
    }


def paper_sell(user_id: int, chain: str, token_address: str, token_symbol: str,
               amount_tokens: float, strategy_id: int = None,
               coingecko_id: str = None) -> dict:
    """
    Paper sell with realized PnL calculation and position closing.
    Closes the matching open position and records exact profit/loss.
    """
    chain_info = CHAINS.get(chain)
    if not chain_info:
        raise ValueError(f"Unknown chain: {chain}")

    native_symbol = chain_info["symbol"]

    price_data = get_token_price(chain, token_address, coingecko_id)
    if not price_data or not price_data.get("price"):
        raise ValueError(f"Could not fetch price for {token_symbol or token_address}")

    exit_price_usd = price_data["price"]
    native_usd     = _get_native_usd(chain)
    usd_received   = amount_tokens * exit_price_usd
    native_raw     = usd_received / native_usd  # before fees

    # ── Apply REAL sell-side fees (gas + DEX fee + slippage) ─────────────────
    native_received, sell_fees = apply_paper_fees(
        chain, native_raw, native_usd, is_buy=False
    )
    total_cost_usd   = sell_fees["total_cost_usd"]
    usd_received_net = native_received * native_usd
    # ─────────────────────────────────────────────────────────────────────────

    db.subtract_paper_balance(user_id, token_symbol.upper(), chain, amount_tokens)
    db.add_paper_balance(user_id, native_symbol, chain, native_received)

    # Find and close open position(s) for this token/strategy
    positions = db.get_open_positions(user_id, strategy_id)
    matching  = [p for p in positions
                 if p["token_address"].lower() == token_address.lower()
                 and p["status"] == "open"]

    realized_pnl_usd = 0.0
    realized_pnl_pct = 0.0

    if matching:
        pos = matching[0]
        entry_usd = pos["entry_usd"]
        # Realized PnL = what you actually walked away with (post-fees)
        # minus what it actually cost you to get in (post-fees, already in entry_usd)
        realized_pnl_usd = usd_received_net - entry_usd
        realized_pnl_pct = ((exit_price_usd - pos["entry_price_usd"]) / pos["entry_price_usd"]) * 100 if pos["entry_price_usd"] > 0 else 0
        db.close_position(pos["id"], exit_price_usd, realized_pnl_usd)

    trade_id = db.save_trade({
        "user_id":       user_id,
        "chain":         chain,
        "trade_type":    "sell",
        "mode":          "paper",
        "token_in":      token_address,
        "token_out":     "native",
        "symbol_in":     token_symbol,
        "symbol_out":    native_symbol,
        "amount_in":     amount_tokens,
        "amount_out":    native_received,
        "price_at_trade":exit_price_usd,
        "exit_price":    exit_price_usd,
        "pnl_abs":       realized_pnl_usd,
        "status":        "success",
        "strategy":      str(strategy_id) if strategy_id else None,
    })

    return {
        "trade_id":         trade_id,
        "spent":            amount_tokens,
        "spent_symbol":     token_symbol,
        "received":         native_received,
        "received_symbol":  native_symbol,
        "price":            exit_price_usd,
        "usd_value":        usd_received_net,
        "realized_pnl_usd": realized_pnl_usd,
        "realized_pnl_pct": realized_pnl_pct,
        "native_usd":       native_usd,
        "fees": {
            "gas_usd":        sell_fees["gas_usd"],
            "dex_fee_usd":    sell_fees["dex_fee_usd"],
            "slippage_usd":   sell_fees["slippage_usd"],
            "total_cost_usd": total_cost_usd,
            "cost_pct":       sell_fees["cost_pct"],
        },
    }


def get_unrealized_pnl(user_id: int, strategy_id: int = None) -> dict:
    """
    Calculate current unrealized PnL across all open positions.
    Fetches live prices via DexScreener for ALL token types.
    """
    positions = db.get_open_positions(user_id, strategy_id)
    total_cost       = 0.0
    total_current    = 0.0
    position_details = []

    for pos in positions:
        # Try multiple price sources in order
        current_price = 0.0
        token_addr    = pos["token_address"]
        chain         = pos["chain"]

        try:
            # 1. DexScreener (works for ANY token with a pair)
            from utils.prices import get_price_dexscreener
            dex = get_price_dexscreener(chain, token_addr)
            if dex and dex.get("price"):
                current_price = float(dex["price"])
        except Exception:
            pass

        if not current_price:
            try:
                # 2. CoinGecko via universal lookup
                current_price = _get_token_usd_price(
                    pos.get("token_symbol",""), chain, token_addr
                )
            except Exception:
                pass

        if not current_price:
            # 3. Fallback to last known price
            current_price = pos.get("current_price") or pos["entry_price_usd"]

        if current_price:
            db.update_position_price(pos["id"], current_price)

        current_value = pos["qty"] * current_price
        cost_basis    = pos["entry_usd"]
        unrealized    = current_value - cost_basis
        pct = (
            ((current_price - pos["entry_price_usd"]) / pos["entry_price_usd"]) * 100
            if pos["entry_price_usd"] > 0 else 0
        )

        total_cost    += cost_basis
        total_current += current_value

        position_details.append({
            "position_id":   pos["id"],
            "token_symbol":  pos["token_symbol"],
            "token_address": token_addr,
            "chain":         chain,
            "qty":           pos["qty"],
            "entry_price":   pos["entry_price_usd"],
            "current_price": current_price,
            "cost_basis":    cost_basis,
            "current_value": current_value,
            "unrealized":    unrealized,
            "pct":           pct,
            "opened_at":     pos["opened_at"],
        })

    total_unrealized = total_current - total_cost
    return {
        "positions":        position_details,
        "total_cost":       total_cost,
        "total_current":    total_current,
        "total_unrealized": total_unrealized,
        "total_pct": ((total_current - total_cost) / total_cost * 100) if total_cost > 0 else 0,
    }


# Mapping of native chain tokens to CoinGecko IDs — comprehensive list
NATIVE_COINGECKO = {
    "ETH":   "ethereum",
    "BNB":   "binancecoin",
    "MATIC": "matic-network",
    "AVAX":  "avalanche-2",
    "SOL":   "solana",
    "NEAR":  "near",
    "HOT":   "hot-labs",
    "ARB":   "arbitrum",
    "OP":    "optimism",
    "FTM":   "fantom",
    "DOT":   "polkadot",
    "ADA":   "cardano",
    "BTC":   "bitcoin",
    "USDC":  None,   # stablecoin = $1
    "USDT":  None,   # stablecoin = $1
    "BUSD":  None,   # stablecoin = $1
    "DAI":   None,   # stablecoin = $1
}


def _get_token_usd_price(symbol: str, chain: str, token_address: str = None) -> float:
    """
    Universal price lookup for any asset in the paper portfolio.
    Priority: CoinGecko (native tokens) → stablecoin ($1) → DexScreener → 0
    """
    sym_upper = symbol.upper()

    # Stablecoins always $1
    if sym_upper in ("USDC", "USDT", "BUSD", "DAI", "FRAX", "LUSD"):
        return 1.0

    # Known native tokens via CoinGecko
    if sym_upper in NATIVE_COINGECKO:
        cg_id = NATIVE_COINGECKO[sym_upper]
        if cg_id is None:
            return 1.0  # stablecoin
        pd = get_price_coingecko(cg_id)
        if pd and pd.get("price"):
            return float(pd["price"])

    # Unknown tokens — try DexScreener with token address if we have it
    if token_address and token_address not in ("native", "near", ""):
        from utils.prices import get_price_dexscreener
        dex = get_price_dexscreener(chain, token_address)
        if dex and dex.get("price"):
            return float(dex["price"])

    # Try CoinGecko search as last resort
    try:
        from utils.prices import search_token
        results = search_token(sym_upper)
        if results:
            pd = get_price_coingecko(results[0]["id"])
            if pd and pd.get("price"):
                return float(pd["price"])
    except Exception:
        pass

    return 0.0


def get_paper_portfolio(user_id: int) -> dict:
    """
    Full paper portfolio with accurate USD values for ALL assets.
    Fetches live prices for native tokens, stablecoins, and unknown tokens.
    """
    balances = db.get_all_paper_balances(user_id)

    # Also get open position addresses for DexScreener lookup
    positions = db.get_open_positions(user_id)
    addr_map: dict = {}  # symbol -> (chain, token_address)
    for pos in positions:
        sym = pos.get("token_symbol", "").upper()
        if sym:
            addr_map[sym] = (pos["chain"], pos["token_address"])

    total_usd = 0.0
    items = []

    for bal in balances:
        symbol  = bal["asset"].upper()
        balance = bal["balance"]
        chain   = bal["chain"]

        # Look up token address from open positions if available
        chain_lookup, addr_lookup = addr_map.get(symbol, (chain, None))

        price   = _get_token_usd_price(symbol, chain_lookup, addr_lookup)
        usd_val = balance * price if price > 0 else 0.0

        total_usd += usd_val
        items.append({
            "symbol":    symbol,
            "chain":     chain,
            "balance":   balance,
            "price":     price,
            "usd_value": usd_val,
            "has_price": price > 0,
        })

    # Add unrealized PnL from open positions
    unrealized = get_unrealized_pnl(user_id)
    total_usd += max(0, unrealized["total_unrealized"])

    return {
        "items":             items,
        "total_usd":         total_usd,
        "unrealized_pnl":    unrealized["total_unrealized"],
        "open_positions":    unrealized["positions"],
    }

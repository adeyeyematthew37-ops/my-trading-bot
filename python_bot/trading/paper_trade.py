# trading/paper_trade.py  —  Paper trading with real PnL tracking

from utils import database as db
from utils.prices import get_token_price, get_price_coingecko, get_token_full_info, fmt_price, fmt_mcap
from config.chains import CHAINS


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
    tokens_received = usd_spent / token_price_usd

    # Deduct native balance
    db.subtract_paper_balance(user_id, native_symbol, chain, amount_native)
    # Add token balance — key is always UPPER normalized symbol
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

    # Open a position record for PnL tracking
    pos_id = db.open_position({
        "user_id":         user_id,
        "strategy_id":     strategy_id,
        "chain":           chain,
        "mode":            "paper",
        "token_address":   token_address,
        "token_symbol":    token_symbol.upper(),
        "qty":             tokens_received,
        "entry_price_usd": token_price_usd,
        "entry_native":    amount_native,
        "entry_usd":       usd_spent,
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
    native_received= usd_received / native_usd

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
        realized_pnl_usd = usd_received - entry_usd
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
        "usd_value":        usd_received,
        "realized_pnl_usd": realized_pnl_usd,
        "realized_pnl_pct": realized_pnl_pct,
        "native_usd":       native_usd,
    }


def get_unrealized_pnl(user_id: int, strategy_id: int = None) -> dict:
    """
    Calculate current unrealized PnL across all open positions.
    Fetches live prices for each open position.
    """
    positions = db.get_open_positions(user_id, strategy_id)
    total_cost      = 0.0
    total_current   = 0.0
    position_details = []

    for pos in positions:
        try:
            pd = get_token_price(pos["chain"], pos["token_address"])
            current_price = pd["price"] if pd and pd.get("price") else pos["entry_price_usd"]
        except Exception:
            current_price = pos["entry_price_usd"]

        db.update_position_price(pos["id"], current_price)

        current_value = pos["qty"] * current_price
        cost_basis    = pos["entry_usd"]
        unrealized    = current_value - cost_basis
        pct           = ((current_price - pos["entry_price_usd"]) / pos["entry_price_usd"]) * 100 \
                        if pos["entry_price_usd"] > 0 else 0

        total_cost    += cost_basis
        total_current += current_value

        position_details.append({
            "position_id":   pos["id"],
            "token_symbol":  pos["token_symbol"],
            "token_address": pos["token_address"],
            "chain":         pos["chain"],
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
        "positions":       position_details,
        "total_cost":      total_cost,
        "total_current":   total_current,
        "total_unrealized":total_unrealized,
        "total_pct":       ((total_current - total_cost) / total_cost * 100) if total_cost > 0 else 0,
    }


def get_paper_portfolio(user_id: int) -> dict:
    """Full paper portfolio with live USD values and unrealized PnL."""
    balances = db.get_all_paper_balances(user_id)
    total_usd = 0.0
    items = []

    native_cg = {
        "ETH":"ethereum","BNB":"binancecoin","MATIC":"matic-network",
        "AVAX":"avalanche-2","SOL":"solana",
    }

    for bal in balances:
        symbol  = bal["asset"]
        balance = bal["balance"]
        usd_val = 0.0
        price   = 0.0

        if symbol in native_cg:
            pd = get_price_coingecko(native_cg[symbol])
            if pd:
                price   = pd["price"]
                usd_val = balance * price

        total_usd += usd_val
        items.append({
            "symbol":    symbol,
            "chain":     bal["chain"],
            "balance":   balance,
            "price":     price,
            "usd_value": usd_val,
        })

    # Add unrealized PnL from open positions
    unrealized = get_unrealized_pnl(user_id)

    return {
        "items":             items,
        "total_usd":         total_usd,
        "unrealized_pnl":    unrealized["total_unrealized"],
        "open_positions":    unrealized["positions"],
    }

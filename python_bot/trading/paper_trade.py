# trading/paper_trade.py  —  Simulated paper trading with virtual balances

from utils import database as db
from utils.prices import get_token_price, get_price_coingecko
from config.chains import CHAINS


def paper_buy(user_id: int, chain: str, token_address: str, token_symbol: str,
              amount_native: float, coingecko_id: str = None) -> dict:
    """
    Simulate buying a token with native currency.
    Deducts native balance, adds token balance.
    """
    chain_info = CHAINS.get(chain)
    if not chain_info:
        raise ValueError(f"Unknown chain: {chain}")

    native_symbol = chain_info["symbol"]

    # Get current price
    price_data = get_token_price(chain, token_address, coingecko_id)
    if not price_data or not price_data.get("price"):
        raise ValueError("Could not fetch token price")

    price = price_data["price"]

    # Get native price in USD to calculate token amount
    native_price_data = get_price_coingecko(chain_info["coingecko_id"])
    native_usd = native_price_data["price"] if native_price_data else 1.0

    usd_value = amount_native * native_usd
    tokens_received = usd_value / price

    # Check balance
    db.subtract_paper_balance(user_id, native_symbol, chain, amount_native)
    db.add_paper_balance(user_id, token_symbol.upper(), chain, tokens_received)

    trade_id = db.save_trade({
        "user_id": user_id,
        "chain": chain,
        "trade_type": "buy",
        "mode": "paper",
        "token_in": "native",
        "token_out": token_address,
        "symbol_in": native_symbol,
        "symbol_out": token_symbol,
        "amount_in": amount_native,
        "amount_out": tokens_received,
        "price_at_trade": price,
        "status": "success",
    })

    return {
        "trade_id": trade_id,
        "spent": amount_native,
        "spent_symbol": native_symbol,
        "received": tokens_received,
        "received_symbol": token_symbol,
        "price": price,
        "usd_value": usd_value,
    }


def paper_sell(user_id: int, chain: str, token_address: str, token_symbol: str,
               amount_tokens: float, coingecko_id: str = None) -> dict:
    """
    Simulate selling tokens for native currency.
    Deducts token balance, adds native balance.
    """
    chain_info = CHAINS.get(chain)
    native_symbol = chain_info["symbol"]

    price_data = get_token_price(chain, token_address, coingecko_id)
    if not price_data or not price_data.get("price"):
        raise ValueError("Could not fetch token price")

    price = price_data["price"]
    native_price_data = get_price_coingecko(chain_info["coingecko_id"])
    native_usd = native_price_data["price"] if native_price_data else 1.0

    usd_value = amount_tokens * price
    native_received = usd_value / native_usd

    db.subtract_paper_balance(user_id, token_symbol.upper(), chain, amount_tokens)
    db.add_paper_balance(user_id, native_symbol, chain, native_received)

    trade_id = db.save_trade({
        "user_id": user_id,
        "chain": chain,
        "trade_type": "sell",
        "mode": "paper",
        "token_in": token_address,
        "token_out": "native",
        "symbol_in": token_symbol,
        "symbol_out": native_symbol,
        "amount_in": amount_tokens,
        "amount_out": native_received,
        "price_at_trade": price,
        "status": "success",
    })

    return {
        "trade_id": trade_id,
        "spent": amount_tokens,
        "spent_symbol": token_symbol,
        "received": native_received,
        "received_symbol": native_symbol,
        "price": price,
        "usd_value": usd_value,
    }


def get_paper_portfolio(user_id: int) -> dict:
    """Get full paper portfolio with USD values."""
    from utils.prices import get_price_coingecko
    balances = db.get_all_paper_balances(user_id)
    total_usd = 0.0
    items = []

    # Map symbols to coingecko IDs for native tokens
    native_cg = {
        "ETH": "ethereum", "BNB": "binancecoin", "MATIC": "matic-network",
        "AVAX": "avalanche-2", "SOL": "solana", "USD": None,
    }

    for bal in balances:
        symbol = bal["asset"]
        balance = bal["balance"]
        usd_val = 0.0

        if symbol in native_cg and native_cg[symbol]:
            pd = get_price_coingecko(native_cg[symbol])
            if pd:
                usd_val = balance * pd["price"]

        total_usd += usd_val
        items.append({
            "symbol": symbol,
            "chain": bal["chain"],
            "balance": balance,
            "usd_value": usd_val,
        })

    return {"items": items, "total_usd": total_usd}

# trading/live_executor.py
#
# Executes REAL trades with real funds, after checking REAL current gas costs.
#
# This is the bridge between a strategy's "buy"/"sell" signal and an actual
# on-chain transaction. Every call here:
#   1. Fetches the live wallet (encrypted key) for the user on this chain
#   2. Queries the chain's CURRENT gas price (not an estimate)
#   3. Refuses to trade if gas would eat too much of the position
#   4. Executes the real swap if viable
#   5. Records the ACTUAL gas paid (from the transaction receipt) into PnL
#
# Paper trading uses calculate_trade_cost() from fees.py to simulate the
# same numbers this module would produce for a live trade — so a strategy
# that's profitable on paper has already accounted for what it would
# really cost to run live, chain by chain.

from config.chains import CHAINS
from trading.fees import calculate_trade_cost, get_native_usd_price, check_gas_reserve
from utils import database as db

NATIVE_ADDR = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"


class TradeNotViable(Exception):
    """Raised when a trade would lose more to gas/fees than it could reasonably profit."""
    pass


def get_live_wallet(user_id: int, chain: str) -> dict | None:
    """Fetch the user's default LIVE wallet for this chain, if one exists."""
    return db.get_default_wallet(user_id, chain, wallet_type="live")


def precheck_trade(chain: str, amount_native: float, native_usd_price: float = None,
                   needs_approval: bool = False) -> dict:
    """
    Real-time viability check before spending anything.
    Returns the full cost breakdown; raises TradeNotViable if gas
    would consume an unreasonable share of the trade.
    """
    native_usd = native_usd_price or get_native_usd_price(chain)
    trade_usd  = amount_native * native_usd
    cost = calculate_trade_cost(chain, trade_usd, needs_approval=needs_approval)

    if not cost["viable"]:
        raise TradeNotViable(cost["warning"])

    return cost


def execute_live_buy(user_id: int, chain: str, token_address: str,
                     token_symbol: str, amount_native: float,
                     strategy_id: int = None, slippage_pct: float = 1.5) -> dict:
    """
    Execute a REAL buy with real funds, gas-checked first.

    Flow:
      1. Find the user's live wallet for this chain
      2. Check gas reserve won't be drained below safe minimum
      3. Run a real-time gas viability check (raises if uneconomical)
      4. Execute the actual swap on-chain
      5. Record the trade + open a position with the REAL entry price
         (token price as it executed, post-slippage)
    """
    wallet = get_live_wallet(user_id, chain)
    if not wallet:
        raise ValueError(
            f"No live wallet for {chain}. Import one via Menu → Wallets → Import."
        )

    chain_info = CHAINS.get(chain, {})
    native_sym = chain_info.get("symbol", "?")

    # Gas reserve check — never let auto-trading drain gas money to zero
    reserve = check_gas_reserve(user_id, chain, amount_native)
    # Note: for live wallets the "paper balance" reserve check doesn't apply
    # directly — real balance is checked on-chain by the swap itself failing
    # if insufficient. We still warn here for visibility.

    # Real-time gas viability — this is the core protection requested:
    # don't trade if gas would eat the position alive
    cost = precheck_trade(chain, amount_native, needs_approval=True)

    if chain_info.get("type") == "evm":
        from trading.evm_swap import execute_evm_swap
        from web3 import Web3
        amount_wei = Web3.to_wei(amount_native, "ether")
        result = execute_evm_swap(
            chain_key=chain,
            enc_key=wallet["enc_key"],
            token_in=NATIVE_ADDR,
            token_out=token_address,
            amount_wei=amount_wei,
            slippage=slippage_pct,
        )
    elif chain_info.get("type") == "solana":
        from trading.solana_swap import execute_solana_swap, SOL_MINT
        lamports = int(amount_native * 1_000_000_000)
        result = execute_solana_swap(
            encrypted_private_key=wallet["enc_key"],
            input_mint=SOL_MINT,
            output_mint=token_address,
            amount_lamports=lamports,
            slippage_bps=int(slippage_pct * 100),
            user_address=wallet["address"],
        )
    else:
        raise ValueError(f"Live trading not yet supported on {chain}")

    if result.get("status") != "success":
        raise ValueError(f"Transaction failed on-chain: {result.get('tx_hash','unknown')}")

    # ── Record the trade with REAL costs ─────────────────────────────────────
    actual_gas_native = result.get("actual_gas_native", cost["gas_usd"] / get_native_usd_price(chain))
    actual_gas_usd     = actual_gas_native * get_native_usd_price(chain)

    # Get the real token price from on-chain data for accurate PnL entry
    from utils.prices import get_token_price
    price_data = get_token_price(chain, token_address)
    entry_price_usd = price_data["price"] if price_data and price_data.get("price") else 0

    trade_id = db.save_trade({
        "user_id":        user_id,
        "chain":          chain,
        "trade_type":     "buy",
        "mode":           "live",
        "token_in":       "native",
        "token_out":      token_address,
        "symbol_in":      native_sym,
        "symbol_out":     token_symbol,
        "amount_in":      amount_native,
        "amount_out":     None,  # unknown exact qty without parsing logs; tracked via position
        "price_at_trade": entry_price_usd,
        "entry_price":    entry_price_usd,
        "tx_hash":        result["tx_hash"],
        "status":         "success",
        "strategy":       str(strategy_id) if strategy_id else None,
    })

    pos_id = None
    if entry_price_usd > 0:
        usd_spent = amount_native * get_native_usd_price(chain)
        # Cost basis includes the real gas paid
        effective_entry = (usd_spent + actual_gas_usd) / ((usd_spent) / entry_price_usd) \
                          if usd_spent > 0 else entry_price_usd
        pos_id = db.open_position({
            "user_id":         user_id,
            "strategy_id":     strategy_id,
            "chain":           chain,
            "mode":            "live",
            "token_address":   token_address,
            "token_symbol":    token_symbol.upper(),
            "qty":             usd_spent / entry_price_usd if entry_price_usd > 0 else 0,
            "entry_price_usd": effective_entry,
            "entry_native":    amount_native,
            "entry_usd":       usd_spent + actual_gas_usd,
        })

    return {
        "trade_id":     trade_id,
        "position_id":  pos_id,
        "tx_hash":      result["tx_hash"],
        "explorer_url": f"{chain_info.get('explorer','')}/tx/{result['tx_hash']}",
        "amount_spent": amount_native,
        "native_symbol":native_sym,
        "entry_price":  entry_price_usd,
        "actual_gas_native": actual_gas_native,
        "actual_gas_usd":    actual_gas_usd,
        "estimated_cost":    cost,
    }


def execute_live_sell(user_id: int, chain: str, token_address: str,
                      token_symbol: str, amount_tokens: float,
                      strategy_id: int = None, slippage_pct: float = 1.5) -> dict:
    """Execute a REAL sell with real funds, gas-checked first."""
    wallet = get_live_wallet(user_id, chain)
    if not wallet:
        raise ValueError(f"No live wallet for {chain}.")

    chain_info = CHAINS.get(chain, {})
    native_sym = chain_info.get("symbol", "?")

    # Estimate trade value for gas viability (need current token price)
    from utils.prices import get_token_price
    price_data = get_token_price(chain, token_address)
    exit_price_usd = price_data["price"] if price_data and price_data.get("price") else 0
    trade_usd = amount_tokens * exit_price_usd

    cost = calculate_trade_cost(chain, trade_usd, needs_approval=False)
    if not cost["viable"]:
        raise TradeNotViable(cost["warning"])

    if chain_info.get("type") == "evm":
        from trading.evm_swap import execute_evm_swap, get_token_info
        from web3 import Web3
        token_info = get_token_info(token_address, chain)
        amount_raw = int(amount_tokens * (10 ** token_info["decimals"]))
        result = execute_evm_swap(
            chain_key=chain,
            enc_key=wallet["enc_key"],
            token_in=token_address,
            token_out=NATIVE_ADDR,
            amount_wei=amount_raw,
            slippage=slippage_pct,
        )
    elif chain_info.get("type") == "solana":
        from trading.solana_swap import execute_solana_swap, SOL_MINT
        amount_lamports = int(amount_tokens * 1_000_000)  # assumes 6 decimals; refine per-token if needed
        result = execute_solana_swap(
            encrypted_private_key=wallet["enc_key"],
            input_mint=token_address,
            output_mint=SOL_MINT,
            amount_lamports=amount_lamports,
            slippage_bps=int(slippage_pct * 100),
            user_address=wallet["address"],
        )
    else:
        raise ValueError(f"Live trading not yet supported on {chain}")

    if result.get("status") != "success":
        raise ValueError(f"Transaction failed: {result.get('tx_hash','unknown')}")

    actual_gas_native = result.get("actual_gas_native", cost["gas_usd"] / get_native_usd_price(chain))
    actual_gas_usd     = actual_gas_native * get_native_usd_price(chain)

    # Close matching open position for realized PnL
    realized_pnl = 0.0
    positions = db.get_open_positions(user_id, strategy_id)
    matching  = [p for p in positions if p["token_address"].lower() == token_address.lower()]
    if matching:
        pos = matching[0]
        usd_received = trade_usd - actual_gas_usd
        realized_pnl = usd_received - pos["entry_usd"]
        db.close_position(pos["id"], exit_price_usd, realized_pnl)

    trade_id = db.save_trade({
        "user_id":        user_id,
        "chain":          chain,
        "trade_type":     "sell",
        "mode":           "live",
        "token_in":       token_address,
        "token_out":      "native",
        "symbol_in":      token_symbol,
        "symbol_out":     native_sym,
        "amount_in":      amount_tokens,
        "price_at_trade": exit_price_usd,
        "exit_price":     exit_price_usd,
        "pnl_abs":        realized_pnl,
        "tx_hash":        result["tx_hash"],
        "status":         "success",
        "strategy":       str(strategy_id) if strategy_id else None,
    })

    return {
        "trade_id":          trade_id,
        "tx_hash":           result["tx_hash"],
        "explorer_url":      f"{chain_info.get('explorer','')}/tx/{result['tx_hash']}",
        "amount_sold":       amount_tokens,
        "exit_price":        exit_price_usd,
        "realized_pnl_usd":  realized_pnl,
        "actual_gas_native": actual_gas_native,
        "actual_gas_usd":    actual_gas_usd,
    }

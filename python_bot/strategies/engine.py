# strategies/engine.py  —  All trading strategies with paper + live execution

import json
import time
from datetime import datetime, timedelta
from utils.prices import get_token_price, get_price_dexscreener, fmt_price
from utils import database as db

# ── Price History Cache ───────────────────────────────────────────────────────

_price_history: dict = {}  # token_key -> [prices]

def _record_price(chain: str, token: str, price: float):
    key = f"{chain}_{token}"
    if key not in _price_history:
        _price_history[key] = []
    _price_history[key].append({"price": price, "ts": time.time()})
    # Keep last 200 data points
    _price_history[key] = _price_history[key][-200:]

def _get_prices(chain: str, token: str, n: int) -> list[float]:
    key = f"{chain}_{token}"
    history = _price_history.get(key, [])
    return [h["price"] for h in history[-n:]]

# ── Technical Indicators ──────────────────────────────────────────────────────

def calc_sma(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period

def calc_ema(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_rsi(prices: list[float], period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_bollinger(prices: list[float], period: int = 20) -> dict | None:
    if len(prices) < period:
        return None
    sma = calc_sma(prices, period)
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = variance ** 0.5
    return {"upper": sma + 2 * std, "middle": sma, "lower": sma - 2 * std, "std": std}

def calc_macd(prices: list[float]) -> dict | None:
    ema12 = calc_ema(prices, 12)
    ema26 = calc_ema(prices, 26)
    if ema12 is None or ema26 is None:
        return None
    macd_line = ema12 - ema26
    return {"macd": macd_line, "ema12": ema12, "ema26": ema26}

# ── Strategy Definitions ──────────────────────────────────────────────────────

STRATEGIES = {
    "rsi_oversold": {
        "name": "RSI Oversold/Overbought",
        "description": "Buys when RSI < 30 (oversold), sells when RSI > 70 (overbought)",
        "params": {"rsi_buy": 30, "rsi_sell": 70, "period": 14, "trade_amount": 0.01},
        "risk": "Medium",
        "best_for": "Ranging markets",
    },
    "ma_crossover": {
        "name": "Moving Average Crossover",
        "description": "Buys when fast MA crosses above slow MA (golden cross), sells on death cross",
        "params": {"fast_ma": 9, "slow_ma": 21, "trade_amount": 0.01},
        "risk": "Low-Medium",
        "best_for": "Trending markets",
    },
    "momentum": {
        "name": "Price Momentum",
        "description": "Buys when price gains >2% in an hour, sells when it drops >2%",
        "params": {"buy_threshold": 2.0, "sell_threshold": -2.0, "lookback": 12, "trade_amount": 0.01},
        "risk": "High",
        "best_for": "Strong trends & breakouts",
    },
    "bollinger_bands": {
        "name": "Bollinger Band Squeeze",
        "description": "Buys at lower band, sells at upper band",
        "params": {"period": 20, "trade_amount": 0.01},
        "risk": "Medium",
        "best_for": "Mean-reverting assets",
    },
    "dca_auto": {
        "name": "Auto DCA",
        "description": "Buys a fixed amount at regular intervals regardless of price",
        "params": {"amount_per_order": 0.01, "freq_minutes": 1440},
        "risk": "Low",
        "best_for": "Long-term accumulation",
    },
    "grid": {
        "name": "Grid Trading",
        "description": "Places buy/sell orders at fixed price intervals to profit from volatility",
        "params": {"grid_count": 5, "range_pct": 10.0, "amount_per_grid": 0.005},
        "risk": "Medium",
        "best_for": "Sideways/choppy markets",
    },
}

# ── Signal Generation ─────────────────────────────────────────────────────────

def get_signal(strategy_name: str, chain: str, token: str, params: dict) -> dict:
    """
    Evaluate a strategy against current price history.
    Returns: {"signal": "buy"|"sell"|"hold", "reason": str, "indicators": dict}
    """
    price_data = get_token_price(chain, token)
    if not price_data:
        return {"signal": "hold", "reason": "No price data available", "indicators": {}}

    current_price = price_data["price"]
    if not current_price or current_price <= 0:
        return {"signal": "hold", "reason": "Invalid price data", "indicators": {}}

    _record_price(chain, token, current_price)
    prices = _get_prices(chain, token, 100)

    # Never fire a signal with fewer than 3 distinct price points
    # (prevents false RSI=0.0 signals on first run)
    if len(prices) < 3:
        return {
            "signal": "hold",
            "reason": f"Warming up — collecting price history ({len(prices)}/3 minimum)",
            "indicators": {"current_price": current_price}
        }

    # Check prices actually vary (flat line = no real data yet)
    if len(set(prices)) < 2:
        return {
            "signal": "hold",
            "reason": "Waiting for price movement data",
            "indicators": {"current_price": current_price}
        }

    indicators = {"current_price": current_price}

    if strategy_name == "rsi_oversold":
        rsi = calc_rsi(prices, params.get("period", 14))
        indicators["rsi"] = rsi
        if rsi is None:
            return {"signal": "hold", "reason": f"Collecting data ({len(prices)}/15 points)", "indicators": indicators}
        if rsi < params.get("rsi_buy", 30):
            return {"signal": "buy", "reason": f"RSI={rsi:.1f} — oversold (<{params.get('rsi_buy',30)})", "indicators": indicators}
        if rsi > params.get("rsi_sell", 70):
            return {"signal": "sell", "reason": f"RSI={rsi:.1f} — overbought (>{params.get('rsi_sell',70)})", "indicators": indicators}
        return {"signal": "hold", "reason": f"RSI={rsi:.1f} — neutral zone", "indicators": indicators}

    elif strategy_name == "ma_crossover":
        fast = calc_sma(prices, params.get("fast_ma", 9))
        slow = calc_sma(prices, params.get("slow_ma", 21))
        indicators.update({"fast_ma": fast, "slow_ma": slow})
        if fast is None or slow is None:
            return {"signal": "hold", "reason": f"Collecting data ({len(prices)}/21 points)", "indicators": indicators}
        # Check previous candle for crossover
        prev_prices = prices[:-1]
        prev_fast = calc_sma(prev_prices, params.get("fast_ma", 9))
        prev_slow = calc_sma(prev_prices, params.get("slow_ma", 21))
        if prev_fast and prev_slow:
            if prev_fast < prev_slow and fast > slow:
                return {"signal": "buy", "reason": f"Golden Cross: SMA{params.get('fast_ma',9)}={fast:.4f} crossed above SMA{params.get('slow_ma',21)}={slow:.4f}", "indicators": indicators}
            if prev_fast > prev_slow and fast < slow:
                return {"signal": "sell", "reason": f"Death Cross: SMA{params.get('fast_ma',9)}={fast:.4f} crossed below SMA{params.get('slow_ma',21)}={slow:.4f}", "indicators": indicators}
        trend = "above" if fast > slow else "below"
        return {"signal": "hold", "reason": f"SMA{params.get('fast_ma',9)} {trend} SMA{params.get('slow_ma',21)} — waiting for crossover", "indicators": indicators}

    elif strategy_name == "momentum":
        lb = params.get("lookback", 12)
        if len(prices) < lb:
            return {"signal": "hold", "reason": f"Collecting data ({len(prices)}/{lb} points)", "indicators": indicators}
        old_price = prices[-lb]
        change_pct = ((current_price - old_price) / old_price) * 100
        indicators["change_pct"] = change_pct
        if change_pct >= params.get("buy_threshold", 2.0):
            return {"signal": "buy", "reason": f"Momentum: +{change_pct:.2f}% over {lb} periods", "indicators": indicators}
        if change_pct <= params.get("sell_threshold", -2.0):
            return {"signal": "sell", "reason": f"Momentum: {change_pct:.2f}% over {lb} periods", "indicators": indicators}
        return {"signal": "hold", "reason": f"Momentum: {change_pct:+.2f}% — within threshold", "indicators": indicators}

    elif strategy_name == "bollinger_bands":
        bb = calc_bollinger(prices, params.get("period", 20))
        if bb is None:
            return {"signal": "hold", "reason": f"Collecting data ({len(prices)}/20 points)", "indicators": indicators}
        indicators.update({"bb_upper": bb["upper"], "bb_middle": bb["middle"], "bb_lower": bb["lower"]})
        if current_price <= bb["lower"]:
            return {"signal": "buy", "reason": f"Price at lower BB ({fmt_price(bb['lower'])})", "indicators": indicators}
        if current_price >= bb["upper"]:
            return {"signal": "sell", "reason": f"Price at upper BB ({fmt_price(bb['upper'])})", "indicators": indicators}
        return {"signal": "hold", "reason": f"Price within bands ({fmt_price(bb['lower'])} – {fmt_price(bb['upper'])})", "indicators": indicators}

    return {"signal": "hold", "reason": "Unknown strategy", "indicators": indicators}

def format_signal_message(strategy_name: str, signal: dict, token_symbol: str, chain: str, mode: str) -> str:
    sig = signal["signal"]
    emoji_map = {"buy": "🟢 BUY", "sell": "🔴 SELL", "hold": "⚪ HOLD"}
    mode_tag = "📝 PAPER" if mode == "paper" else "💰 LIVE"
    ind = signal["indicators"]
    lines = [
        f"{'━' * 30}",
        f"🤖 *Strategy Signal* [{mode_tag}]",
        f"📊 *{STRATEGIES.get(strategy_name, {}).get('name', strategy_name)}*",
        f"🪙 Token: *{token_symbol}* ({chain})",
        f"💵 Price: *{fmt_price(ind.get('current_price'))}*",
        f"",
        f"📡 Signal: *{emoji_map.get(sig, sig)}*",
        f"📝 Reason: {signal['reason']}",
    ]
    if ind.get("rsi") is not None:
        lines.append(f"📉 RSI: {ind['rsi']:.1f}")
    if ind.get("fast_ma") is not None:
        lines.append(f"📈 Fast MA: {fmt_price(ind['fast_ma'])}")
    if ind.get("slow_ma") is not None:
        lines.append(f"📈 Slow MA: {fmt_price(ind['slow_ma'])}")
    if ind.get("bb_upper") is not None:
        lines.append(f"〰️ BB: {fmt_price(ind['bb_lower'])} / {fmt_price(ind['bb_middle'])} / {fmt_price(ind['bb_upper'])}")
    lines.append(f"{'━' * 30}")
    return "\n".join(lines)

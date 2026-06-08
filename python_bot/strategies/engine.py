# strategies/engine.py  —  Trading strategies with beginner-friendly explanations

import json
import time
from datetime import datetime, timedelta
from utils.prices import get_token_price, get_price_dexscreener, fmt_price
from utils import database as db

# ── Price History Cache ───────────────────────────────────────────────────────
_price_history: dict = {}

def _record_price(chain: str, token: str, price: float):
    key = f"{chain}_{token}"
    if key not in _price_history:
        _price_history[key] = []
    _price_history[key].append({"price": price, "ts": time.time()})
    _price_history[key] = _price_history[key][-500:]

def _get_prices(chain: str, token: str, n: int) -> list:
    key = f"{chain}_{token}"
    return [h["price"] for h in _price_history.get(key, [])[-n:]]

# ── Technical Indicators ──────────────────────────────────────────────────────

def calc_sma(prices, period):
    if len(prices) < period: return None
    return sum(prices[-period:]) / period

def calc_ema(prices, period):
    if len(prices) < period: return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_rsi(prices, period=14):
    if len(prices) < period + 1: return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calc_bollinger(prices, period=20):
    if len(prices) < period: return None
    sma = calc_sma(prices, period)
    std = (sum((p - sma)**2 for p in prices[-period:]) / period) ** 0.5
    return {"upper": sma + 2*std, "middle": sma, "lower": sma - 2*std, "std": std}

def calc_macd(prices):
    e12 = calc_ema(prices, 12)
    e26 = calc_ema(prices, 26)
    if e12 is None or e26 is None: return None
    return {"macd": e12 - e26, "ema12": e12, "ema26": e26}


# ── Strategy Definitions — Beginner-Friendly ──────────────────────────────────

STRATEGIES = {
    "rsi_oversold": {
        "name": "RSI — Dip Buyer",
        "emoji": "📉",
        "short_desc": "Buys when the price has dropped a lot, sells when it's risen a lot",

        "plain_english": (
            "🤔 *What is this strategy?*\n"
            "Think of it like a shop sale detector\\. This bot watches the price of a token\\. "
            "When the price has dropped so much that most traders have panic\\-sold "
            "\\(making it \"oversold\"\\), the bot buys\\. "
            "When the price has risen so high that people are greedily buying "
            "\\(making it \"overbought\"\\), the bot sells\\.\n\n"

            "📈 *When does it BUY?*\n"
            "When the RSI number drops below {rsi_buy} out of 100\\. "
            "RSI is just a score from 0\\-100 that measures how beaten\\-down a price is\\. "
            "Below 30 means the token has been heavily sold off — "
            "historically a good time to buy the dip\\.\n\n"

            "📉 *When does it SELL?*\n"
            "When the RSI rises above {rsi_sell} out of 100\\. "
            "Above 70 means the token has been heavily bought up — "
            "the bot takes profit before a potential pullback\\.\n\n"

            "💰 *How much does it spend per trade?*\n"
            "It spends *{trade_amount} {native_symbol}* each time it buys\\. "
            "You can increase or decrease this below\\.\n\n"

            "⚠️ *Risk level: Medium*\n"
            "Works best in markets that go up and down in a range\\. "
            "Can lose money in strong downtrends\\."
        ),

        "params": {"rsi_buy": 30, "rsi_sell": 70, "period": 14, "trade_amount": 0.01},

        "editable_params": [
            {
                "key":     "trade_amount",
                "label":   "💰 Amount to spend per buy",
                "desc":    "How much native token (ETH/BNB/SOL) to spend each time the bot buys",
                "type":    "float",
                "min":     0.001,
                "max":     100.0,
                "step":    0.005,
            },
            {
                "key":     "rsi_buy",
                "label":   "📉 RSI Buy Level (how low before buying)",
                "desc":    "Buy when RSI drops below this. Lower = wait for bigger dips. Default: 30",
                "type":    "int",
                "min":     10,
                "max":     45,
                "step":    5,
                "presets": [20, 25, 30, 35, 40],
            },
            {
                "key":     "rsi_sell",
                "label":   "📈 RSI Sell Level (how high before selling)",
                "desc":    "Sell when RSI rises above this. Higher = wait for bigger gains. Default: 70",
                "type":    "int",
                "min":     55,
                "max":     90,
                "step":    5,
                "presets": [60, 65, 70, 75, 80],
            },
        ],
        "risk": "Medium",
        "best_for": "Ranging markets",
    },

    "ma_crossover": {
        "name": "MA Crossover — Trend Rider",
        "emoji": "📈",
        "short_desc": "Buys when an uptrend starts, sells when a downtrend starts",

        "plain_english": (
            "🤔 *What is this strategy?*\n"
            "Imagine drawing two lines through the price chart — "
            "a fast\\-moving one and a slow\\-moving one\\. "
            "When the fast line crosses above the slow line, an uptrend is starting "
            "\\(called a \"golden cross\"\\)\\. When it crosses below, a downtrend is starting "
            "\\(called a \"death cross\"\\)\\.\n\n"

            "📈 *When does it BUY?*\n"
            "When the {fast_ma}\\-period average price crosses above the "
            "{slow_ma}\\-period average price\\. "
            "This means short\\-term momentum is now stronger than the long\\-term trend — "
            "a classic sign an uptrend has started\\.\n\n"

            "📉 *When does it SELL?*\n"
            "When the {fast_ma}\\-period average crosses below the "
            "{slow_ma}\\-period average\\. "
            "The short\\-term is now weaker — a downtrend may be starting\\.\n\n"

            "💰 *How much does it spend per trade?*\n"
            "*{trade_amount} {native_symbol}* per buy\\. Adjustable below\\.\n\n"

            "⚠️ *Risk level: Low\\-Medium*\n"
            "More reliable in trending markets but can give false signals when "
            "prices move sideways\\."
        ),

        "params": {"fast_ma": 9, "slow_ma": 21, "trade_amount": 0.01},

        "editable_params": [
            {
                "key":     "trade_amount",
                "label":   "💰 Amount to spend per buy",
                "desc":    "How much to spend each time a buy signal fires",
                "type":    "float",
                "min":     0.001,
                "max":     100.0,
                "step":    0.005,
            },
            {
                "key":     "fast_ma",
                "label":   "⚡ Fast MA period (sensitivity)",
                "desc":    "Lower = reacts faster, more trades but more false signals. Default: 9",
                "type":    "int",
                "min":     3,
                "max":     20,
                "step":    1,
                "presets": [5, 7, 9, 12, 15],
            },
            {
                "key":     "slow_ma",
                "label":   "🐢 Slow MA period (smoothness)",
                "desc":    "Higher = smoother trend filter, fewer but higher quality signals. Default: 21",
                "type":    "int",
                "min":     15,
                "max":     100,
                "step":    5,
                "presets": [15, 21, 30, 50, 100],
            },
        ],
        "risk": "Low-Medium",
        "best_for": "Trending markets",
    },

    "momentum": {
        "name": "Momentum — Breakout Chaser",
        "emoji": "🚀",
        "short_desc": "Buys when a token is surging up fast, sells when it drops fast",

        "plain_english": (
            "🤔 *What is this strategy?*\n"
            "This bot chases momentum\\. If a token has jumped {buy_threshold}% or more "
            "in a short time, it jumps in expecting the move to continue\\. "
            "If it then drops {sell_threshold}% or more, it exits to cut losses\\.\n\n"

            "📈 *When does it BUY?*\n"
            "When the token's price has risen by more than *{buy_threshold}%* "
            "compared to {lookback} periods ago\\. "
            "This means the token has real momentum behind it\\.\n\n"

            "📉 *When does it SELL?*\n"
            "When price drops more than *{sell_threshold}%* from recent levels\\. "
            "This cuts losses quickly if the momentum reverses\\.\n\n"

            "💰 *How much does it spend per trade?*\n"
            "*{trade_amount} {native_symbol}* per trade\\. "
            "Because this strategy can have quick sharp moves, "
            "keeping this smaller is wise\\.\n\n"

            "⚠️ *Risk level: High*\n"
            "Can make big gains on breakouts but can also buy the top of a pump\\. "
            "Best used with smaller position sizes\\."
        ),

        "params": {"buy_threshold": 2.0, "sell_threshold": -2.0, "lookback": 12, "trade_amount": 0.005},

        "editable_params": [
            {
                "key":     "trade_amount",
                "label":   "💰 Amount to spend per buy",
                "desc":    "Keep this lower than other strategies due to higher risk",
                "type":    "float",
                "min":     0.001,
                "max":     50.0,
                "step":    0.005,
            },
            {
                "key":     "buy_threshold",
                "label":   "🚀 Buy threshold % (how big a surge to chase)",
                "desc":    "Only buy if price has risen by at least this %. Higher = fewer but stronger signals",
                "type":    "float",
                "min":     0.5,
                "max":     10.0,
                "step":    0.5,
                "presets": [1.0, 1.5, 2.0, 3.0, 5.0],
            },
            {
                "key":     "sell_threshold",
                "label":   "🛑 Sell threshold % (how big a drop before selling)",
                "desc":    "Sell if price drops by this %. More negative = gives more room before selling",
                "type":    "float",
                "min":     -10.0,
                "max":     -0.5,
                "step":    0.5,
                "presets": [-1.0, -1.5, -2.0, -3.0, -5.0],
            },
        ],
        "risk": "High",
        "best_for": "Breakouts & strong trends",
    },

    "bollinger_bands": {
        "name": "Bollinger Bands — Range Trader",
        "emoji": "〰️",
        "short_desc": "Buys when price is unusually low, sells when it's unusually high",

        "plain_english": (
            "🤔 *What is this strategy?*\n"
            "Imagine three lines around the price — a middle line \\(the average\\), "
            "an upper line, and a lower line\\. The upper and lower lines show "
            "where prices are considered \"unusual\"\\. "
            "When price touches the bottom line it's unusually cheap\\. "
            "When it touches the top line it's unusually expensive\\.\n\n"

            "📈 *When does it BUY?*\n"
            "When the current price touches or drops below the lower band\\. "
            "This means the price has stretched too far down and often bounces back up\\.\n\n"

            "📉 *When does it SELL?*\n"
            "When the price touches or rises above the upper band\\. "
            "The price has stretched too far up and often pulls back\\.\n\n"

            "💰 *How much does it spend per trade?*\n"
            "*{trade_amount} {native_symbol}* per trade\\.\n\n"

            "⚠️ *Risk level: Medium*\n"
            "Great in sideways, choppy markets\\. "
            "Can get caught if the price breaks out of the range and keeps going one direction\\."
        ),

        "params": {"period": 20, "trade_amount": 0.01},

        "editable_params": [
            {
                "key":     "trade_amount",
                "label":   "💰 Amount to spend per buy",
                "desc":    "How much to spend when the bot buys at the lower band",
                "type":    "float",
                "min":     0.001,
                "max":     100.0,
                "step":    0.005,
            },
            {
                "key":     "period",
                "label":   "📏 Band width period",
                "desc":    "How many price points to use when calculating bands. Higher = wider, more stable bands. Default: 20",
                "type":    "int",
                "min":     10,
                "max":     50,
                "step":    5,
                "presets": [10, 15, 20, 30, 50],
            },
        ],
        "risk": "Medium",
        "best_for": "Sideways/choppy markets",
    },

    "dca_auto": {
        "name": "Auto DCA — Regular Saver",
        "emoji": "🏦",
        "short_desc": "Buys a fixed amount on a regular schedule, no matter the price",

        "plain_english": (
            "🤔 *What is this strategy?*\n"
            "This is the simplest and lowest\\-risk strategy\\. "
            "It ignores charts, signals, and price action entirely\\. "
            "It just buys a fixed amount of a token at regular intervals "
            "— just like a savings plan\\.\n\n"

            "📈 *When does it BUY?*\n"
            "Every *{freq_minutes} minutes* \\(regardless of price\\)\\. "
            "No signal needed — just time\\.\n\n"

            "📉 *When does it SELL?*\n"
            "Never — this strategy is for long\\-term accumulation only\\. "
            "You decide when to sell manually\\.\n\n"

            "💰 *How much does it spend per trade?*\n"
            "*{trade_amount} {native_symbol}* every time the timer fires\\. "
            "Over time, you buy some at high prices and some at low prices, "
            "which averages out your cost\\.\n\n"

            "⚠️ *Risk level: Low*\n"
            "The safest automated strategy\\. Ideal for building a position in "
            "tokens you believe in long\\-term\\."
        ),

        "params": {"trade_amount": 0.01, "freq_minutes": 1440},

        "editable_params": [
            {
                "key":     "trade_amount",
                "label":   "💰 Amount to buy each time",
                "desc":    "How much to buy on every scheduled purchase",
                "type":    "float",
                "min":     0.001,
                "max":     100.0,
                "step":    0.005,
            },
            {
                "key":     "freq_minutes",
                "label":   "⏱ How often to buy (minutes)",
                "desc":    "60=hourly  1440=daily  10080=weekly  43200=monthly",
                "type":    "int",
                "min":     30,
                "max":     43200,
                "step":    60,
                "presets": [60, 360, 1440, 10080, 43200],
                "preset_labels": ["Hourly","6hr","Daily","Weekly","Monthly"],
            },
        ],
        "risk": "Low",
        "best_for": "Long-term accumulation",
    },

    "grid": {
        "name": "Grid — Volatility Farmer",
        "emoji": "🔲",
        "short_desc": "Profits from price going up and down by placing lots of small orders",

        "plain_english": (
            "🤔 *What is this strategy?*\n"
            "Imagine a ladder of buy and sell orders\\. "
            "The bot divides a price range into {grid_count} steps\\. "
            "It buys at every step going down, and sells at every step going up\\. "
            "Every up\\-and\\-down wiggle makes a small profit\\.\n\n"

            "📈 *When does it BUY?*\n"
            "When price drops to the next lower grid line\\. "
            "Each buy is for *{amount_per_grid} {native_symbol}*\\.\n\n"

            "📉 *When does it SELL?*\n"
            "When price rises back to the next upper grid line — "
            "selling what was just bought for a small profit\\.\n\n"

            "💰 *How much does it spend per trade?*\n"
            "*{amount_per_grid} {native_symbol}* per grid level\\. "
            "With {grid_count} grid levels, the total exposure is up to "
            "{grid_count}x that amount\\.\n\n"

            "⚠️ *Risk level: Medium*\n"
            "Makes money when price chops up and down\\. "
            "Can accumulate losing positions if price trends strongly in one direction\\."
        ),

        "params": {"grid_count": 5, "range_pct": 10.0, "amount_per_grid": 0.005},

        "editable_params": [
            {
                "key":     "amount_per_grid",
                "label":   "💰 Amount per grid level",
                "desc":    "How much to buy/sell at each grid step. Total exposure = this × number of grids",
                "type":    "float",
                "min":     0.001,
                "max":     50.0,
                "step":    0.001,
            },
            {
                "key":     "grid_count",
                "label":   "🔲 Number of grid levels",
                "desc":    "More levels = more trades but smaller profit per trade. Default: 5",
                "type":    "int",
                "min":     3,
                "max":     20,
                "step":    1,
                "presets": [3, 5, 8, 10, 15],
            },
            {
                "key":     "range_pct",
                "label":   "📏 Price range % (how wide the grid is)",
                "desc":    "The total % range the grid covers. Wider = fewer trades but handles bigger moves",
                "type":    "float",
                "min":     2.0,
                "max":     50.0,
                "step":    2.0,
                "presets": [5.0, 10.0, 15.0, 20.0, 30.0],
            },
        ],
        "risk": "Medium",
        "best_for": "Choppy/sideways markets",
    },
}


# ── Signal Generation ─────────────────────────────────────────────────────────

def get_signal(strategy_name: str, chain: str, token: str, params: dict) -> dict:
    price_data = get_token_price(chain, token)
    if not price_data:
        return {"signal": "hold", "reason": "No price data available", "indicators": {}}

    current_price = price_data.get("price")
    if not current_price or current_price <= 0:
        return {"signal": "hold", "reason": "Invalid price data", "indicators": {}}

    _record_price(chain, token, current_price)
    prices = _get_prices(chain, token, 100)

    if len(prices) < 3:
        return {"signal": "hold",
                "reason": f"Warming up — collecting data ({len(prices)}/3)",
                "indicators": {"current_price": current_price}}

    if len(set(prices)) < 2:
        return {"signal": "hold",
                "reason": "Waiting for real price movement",
                "indicators": {"current_price": current_price}}

    indicators = {"current_price": current_price}

    # ── RSI ───────────────────────────────────────────────────────────────────
    if strategy_name == "rsi_oversold":
        rsi = calc_rsi(prices, params.get("period", 14))
        indicators["rsi"] = rsi
        if rsi is None:
            return {"signal": "hold",
                    "reason": f"Building RSI history ({len(prices)}/15 points needed)",
                    "indicators": indicators}
        if rsi < params.get("rsi_buy", 30):
            return {"signal": "buy",
                    "reason": f"RSI={rsi:.1f} — price is very beaten down, looks like a dip",
                    "indicators": indicators}
        if rsi > params.get("rsi_sell", 70):
            return {"signal": "sell",
                    "reason": f"RSI={rsi:.1f} — price is very stretched up, taking profit",
                    "indicators": indicators}
        return {"signal": "hold",
                "reason": f"RSI={rsi:.1f} — no extreme yet, watching",
                "indicators": indicators}

    # ── MA Crossover ──────────────────────────────────────────────────────────
    elif strategy_name == "ma_crossover":
        fast = calc_sma(prices, params.get("fast_ma", 9))
        slow = calc_sma(prices, params.get("slow_ma", 21))
        indicators.update({"fast_ma": fast, "slow_ma": slow})
        if fast is None or slow is None:
            return {"signal": "hold",
                    "reason": f"Building average history ({len(prices)}/{params.get('slow_ma',21)} needed)",
                    "indicators": indicators}
        prev = prices[:-1]
        pf = calc_sma(prev, params.get("fast_ma", 9))
        ps = calc_sma(prev, params.get("slow_ma", 21))
        if pf and ps:
            if pf < ps and fast > slow:
                return {"signal": "buy",
                        "reason": "Golden cross — uptrend just started",
                        "indicators": indicators}
            if pf > ps and fast < slow:
                return {"signal": "sell",
                        "reason": "Death cross — downtrend just started",
                        "indicators": indicators}
        trend = "above (uptrend)" if fast > slow else "below (downtrend)"
        return {"signal": "hold",
                "reason": f"Fast MA {trend} slow MA — no crossover yet",
                "indicators": indicators}

    # ── Momentum ──────────────────────────────────────────────────────────────
    elif strategy_name == "momentum":
        lb = params.get("lookback", 12)
        if len(prices) < lb:
            return {"signal": "hold",
                    "reason": f"Collecting data ({len(prices)}/{lb} needed)",
                    "indicators": indicators}
        old_price = prices[-lb]
        change_pct = ((current_price - old_price) / old_price) * 100
        indicators["change_pct"] = change_pct
        if change_pct >= params.get("buy_threshold", 2.0):
            return {"signal": "buy",
                    "reason": f"Strong surge: +{change_pct:.2f}% — momentum detected",
                    "indicators": indicators}
        if change_pct <= params.get("sell_threshold", -2.0):
            return {"signal": "sell",
                    "reason": f"Sharp drop: {change_pct:.2f}% — cutting losses",
                    "indicators": indicators}
        return {"signal": "hold",
                "reason": f"Change: {change_pct:+.2f}% — not enough momentum yet",
                "indicators": indicators}

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    elif strategy_name == "bollinger_bands":
        bb = calc_bollinger(prices, params.get("period", 20))
        if bb is None:
            return {"signal": "hold",
                    "reason": f"Building band history ({len(prices)}/20 needed)",
                    "indicators": indicators}
        indicators.update({"bb_upper": bb["upper"], "bb_middle": bb["middle"], "bb_lower": bb["lower"]})
        if current_price <= bb["lower"]:
            return {"signal": "buy",
                    "reason": f"Price at lower band — unusually cheap, expecting bounce",
                    "indicators": indicators}
        if current_price >= bb["upper"]:
            return {"signal": "sell",
                    "reason": f"Price at upper band — unusually expensive, taking profit",
                    "indicators": indicators}
        pct = ((current_price - bb["lower"]) / (bb["upper"] - bb["lower"])) * 100
        return {"signal": "hold",
                "reason": f"Price in middle of bands ({pct:.0f}% up from lower) — watching",
                "indicators": indicators}

    return {"signal": "hold", "reason": "Unknown strategy", "indicators": {}}


def format_signal_message(strategy_name: str, signal: dict,
                           token_symbol: str, chain: str, mode: str) -> str:
    from config.chains import CHAINS
    sig  = signal["signal"]
    ind  = signal["indicators"]
    ci   = CHAINS.get(chain, {})
    mode_tag = "📝 PAPER" if mode == "paper" else "💰 LIVE"
    emoji_map = {"buy": "🟢 BUY", "sell": "🔴 SELL", "hold": "⚪ HOLD"}
    s_info = STRATEGIES.get(strategy_name, {})

    lines = [
        f"{'━'*28}",
        f"🤖 *Strategy Signal* \\[{mode_tag}\\]",
        f"{s_info.get('emoji','📊')} *{s_info.get('name', strategy_name)}*",
        f"🪙 *{token_symbol}* on {ci.get('emoji','')} {ci.get('name', chain)}",
        f"💵 Price: *{fmt_price(ind.get('current_price'))}*",
        f"",
        f"📡 Signal: *{emoji_map.get(sig, sig)}*",
        f"📝 {signal['reason']}",
    ]
    if ind.get("rsi") is not None:
        lines.append(f"📉 RSI: {ind['rsi']:.1f}/100")
    if ind.get("fast_ma") is not None:
        lines.append(f"📈 Fast avg: {fmt_price(ind['fast_ma'])}")
    if ind.get("slow_ma") is not None:
        lines.append(f"📈 Slow avg: {fmt_price(ind['slow_ma'])}")
    if ind.get("bb_upper") is not None:
        lines.append(
            f"〰️ Range: {fmt_price(ind['bb_lower'])} → "
            f"{fmt_price(ind['bb_middle'])} → {fmt_price(ind['bb_upper'])}"
        )
    if ind.get("change_pct") is not None:
        lines.append(f"🚀 Change: {ind['change_pct']:+.2f}%")
    lines.append(f"{'━'*28}")
    return "\n".join(lines)


def format_strategy_description(strategy_key: str, params: dict,
                                  native_symbol: str = "ETH") -> str:
    """Render the plain_english description with actual param values filled in."""
    s = STRATEGIES.get(strategy_key)
    if not s:
        return "Unknown strategy"
    template = s["plain_english"]
    merged = {**s["params"], **params, "native_symbol": native_symbol}
    try:
        return template.format(**merged)
    except KeyError:
        return template


def get_editable_params(strategy_key: str) -> list:
    return STRATEGIES.get(strategy_key, {}).get("editable_params", [])

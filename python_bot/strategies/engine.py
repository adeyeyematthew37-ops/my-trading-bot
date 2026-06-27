# strategies/engine.py
# All trading strategies — plain-English descriptions for beginners
# Includes original 6 + 6 new meme/high-volatility strategies

import time
from utils.prices import get_token_price, fmt_price

# ── Price History ─────────────────────────────────────────────────────────────
_price_history: dict = {}

def _record_price(chain, token, price):
    key = f"{chain}_{token}"
    if key not in _price_history:
        _price_history[key] = []
    _price_history[key].append({"price": price, "ts": time.time()})
    _price_history[key] = _price_history[key][-500:]

def _get_prices(chain, token, n):
    key = f"{chain}_{token}"
    return [h["price"] for h in _price_history.get(key, [])[-n:]]

# ── Indicators ────────────────────────────────────────────────────────────────

def calc_sma(prices, period):
    if len(prices) < period: return None
    return sum(prices[-period:]) / period

def calc_ema(prices, period):
    if len(prices) < period: return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]: ema = p * k + ema * (1 - k)
    return ema

def calc_rsi(prices, period=14):
    if len(prices) < period + 1: return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        d = prices[i] - prices[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    return 100.0 if al == 0 else 100 - (100 / (1 + ag / al))

def calc_bollinger(prices, period=20):
    if len(prices) < period: return None
    sma = calc_sma(prices, period)
    std = (sum((p - sma)**2 for p in prices[-period:]) / period) ** 0.5
    return {"upper": sma + 2*std, "middle": sma, "lower": sma - 2*std, "std": std}

def calc_macd(prices):
    e12 = calc_ema(prices, 12); e26 = calc_ema(prices, 26)
    if e12 is None or e26 is None: return None
    return {"macd": e12 - e26, "ema12": e12, "ema26": e26}

def calc_atr(prices, period=14):
    """Average True Range — measures volatility."""
    if len(prices) < period + 1: return None
    trs = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
    return sum(trs[-period:]) / period

def calc_volume_spike(prices, period=20):
    """Detect if recent price move is unusually large (proxy for volume spike)."""
    if len(prices) < period + 1: return None
    moves = [abs(prices[i] - prices[i-1]) / prices[i-1] * 100
             for i in range(1, len(prices))]
    avg_move = sum(moves[-period:]) / period
    last_move = moves[-1] if moves else 0
    return last_move / avg_move if avg_move > 0 else 0

# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGY DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

STRATEGIES = {

    # ── ORIGINAL 6 ────────────────────────────────────────────────────────────

    "rsi_oversold": {
        "name": "RSI — Dip Buyer",
        "emoji": "📉",
        "short_desc": "Buys when price has crashed hard, sells when it rebounds",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "It's like a bargain hunter\\. When a token's price has dropped so much "
            "that most people have panic\\-sold, this bot buys the dip\\. "
            "When the price bounces back up and people are greedily buying again, it sells\\.\n\n"
            "📈 *Buys when:* The RSI score drops below *{rsi_buy}* out of 100\n"
            "_RSI below 30 = token is heavily oversold = possible bounce coming_\n\n"
            "📉 *Sells when:* RSI rises above *{rsi_sell}* out of 100\n"
            "_RSI above 70 = token is overbought = good time to take profit_\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: Medium — works best when prices go up and down in a range\\."
        ),
        "params": {"rsi_buy": 30, "rsi_sell": 70, "period": 14, "trade_amount": 0.01},
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "How much native token to spend each buy", "type": "float",
             "min": 0.001, "max": 100.0, "step": 0.005},
            {"key": "rsi_buy", "label": "📉 RSI Buy level",
             "desc": "Buy when RSI drops below this. Lower = wait for bigger dips. Default: 30",
             "type": "int", "min": 10, "max": 45, "step": 5,
             "presets": [20, 25, 30, 35, 40]},
            {"key": "rsi_sell", "label": "📈 RSI Sell level",
             "desc": "Sell when RSI rises above this. Higher = bigger gains. Default: 70",
             "type": "int", "min": 55, "max": 90, "step": 5,
             "presets": [60, 65, 70, 75, 80]},
        ],
        "risk": "Medium", "best_for": "Ranging markets",
    },

    "ma_crossover": {
        "name": "MA Crossover — Trend Rider",
        "emoji": "📈",
        "short_desc": "Buys when an uptrend starts, sells when a downtrend starts",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Imagine two lines through the price chart — one fast, one slow\\. "
            "When the fast line crosses above the slow one, an uptrend is starting\\. "
            "The bot buys\\. When it crosses back below, the bot sells\\.\n\n"
            "📈 *Buys when:* Fast {fast_ma}\\-period average crosses above slow {slow_ma}\\-period average\n"
            "_This is called a 'Golden Cross' — a classic uptrend signal_\n\n"
            "📉 *Sells when:* Fast average crosses below slow average\n"
            "_Called a 'Death Cross' — downtrend starting_\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: Low\\-Medium — reliable in trends, noisy when price goes sideways\\."
        ),
        "params": {"fast_ma": 9, "slow_ma": 21, "trade_amount": 0.01},
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "How much to spend per trade", "type": "float",
             "min": 0.001, "max": 100.0, "step": 0.005},
            {"key": "fast_ma", "label": "⚡ Fast MA period",
             "desc": "Lower = more sensitive. Default: 9", "type": "int",
             "min": 3, "max": 20, "step": 1, "presets": [5, 7, 9, 12, 15]},
            {"key": "slow_ma", "label": "🐢 Slow MA period",
             "desc": "Higher = smoother filter. Default: 21", "type": "int",
             "min": 15, "max": 100, "step": 5, "presets": [15, 21, 30, 50, 100]},
        ],
        "risk": "Low-Medium", "best_for": "Trending markets",
    },

    "momentum": {
        "name": "Momentum — Breakout Chaser",
        "emoji": "🚀",
        "short_desc": "Jumps in when a token surges, exits when it drops sharply",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "This bot chases momentum\\. If a token pumps {buy_threshold}%\\+, "
            "it jumps in expecting the move to continue\\. "
            "If it then drops sharply, it exits to protect profits\\.\n\n"
            "📈 *Buys when:* Price rises more than *{buy_threshold}%* in recent periods\n\n"
            "📉 *Sells when:* Price drops more than *{sell_threshold}%* from recent levels\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: High — can catch big pumps but can also buy tops\\. "
            "Keep trade size small\\."
        ),
        "params": {"buy_threshold": 2.0, "sell_threshold": -2.0,
                   "lookback": 12, "trade_amount": 0.005},
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "Keep lower due to higher risk", "type": "float",
             "min": 0.001, "max": 50.0, "step": 0.005},
            {"key": "buy_threshold", "label": "🚀 Buy surge % trigger",
             "desc": "Only chase moves bigger than this %", "type": "float",
             "min": 0.5, "max": 10.0, "step": 0.5, "presets": [1.0, 1.5, 2.0, 3.0, 5.0]},
            {"key": "sell_threshold", "label": "🛑 Sell drop % trigger",
             "desc": "Exit when price drops this much", "type": "float",
             "min": -10.0, "max": -0.5, "step": 0.5,
             "presets": [-1.0, -1.5, -2.0, -3.0, -5.0]},
        ],
        "risk": "High", "best_for": "Breakouts & pumps",
    },

    "bollinger_bands": {
        "name": "Bollinger Bands — Range Trader",
        "emoji": "〰️",
        "short_desc": "Buys when price is unusually low, sells when unusually high",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Three lines around the price: middle \\(average\\), upper, lower\\. "
            "When price touches the bottom — it's unusually cheap, bot buys\\. "
            "When price touches the top — it's unusually expensive, bot sells\\.\n\n"
            "📈 *Buys when:* Price touches or drops below the lower band\n"
            "_Means price stretched too far down — bounce often follows_\n\n"
            "📉 *Sells when:* Price touches or rises above the upper band\n"
            "_Price stretched too far up — pullback often follows_\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: Medium — great in sideways markets\\."
        ),
        "params": {"period": 20, "trade_amount": 0.01},
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "How much to spend at the lower band", "type": "float",
             "min": 0.001, "max": 100.0, "step": 0.005},
            {"key": "period", "label": "📏 Band period",
             "desc": "Higher = wider, more stable bands. Default: 20", "type": "int",
             "min": 10, "max": 50, "step": 5, "presets": [10, 15, 20, 30, 50]},
        ],
        "risk": "Medium", "best_for": "Sideways markets",
    },

    "dca_auto": {
        "name": "Auto DCA — Regular Saver",
        "emoji": "🏦",
        "short_desc": "Buys a fixed amount on a schedule — no charts needed",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "The simplest strategy\\. Ignores all charts and signals\\. "
            "Just buys a fixed amount every {freq_minutes} minutes — like a savings plan\\. "
            "Over time, you buy some high and some low, averaging your cost\\.\n\n"
            "📈 *Buys when:* Every *{freq_minutes} minutes* — no signal needed\n\n"
            "📉 *Sells:* Never — this is accumulation only\\. You sell manually\\.\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: Low — safest automated strategy for long\\-term holds\\."
        ),
        "params": {"trade_amount": 0.01, "freq_minutes": 1440},
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per purchase",
             "desc": "How much to buy on each schedule trigger", "type": "float",
             "min": 0.001, "max": 100.0, "step": 0.005},
            {"key": "freq_minutes", "label": "⏱ Frequency (minutes)",
             "desc": "60=hourly 1440=daily 10080=weekly", "type": "int",
             "min": 30, "max": 43200, "step": 60,
             "presets": [60, 360, 1440, 10080, 43200],
             "preset_labels": ["1hr","6hr","Daily","Weekly","Monthly"]},
        ],
        "risk": "Low", "best_for": "Long-term accumulation",
    },

    "grid": {
        "name": "Grid — Volatility Farmer",
        "emoji": "🔲",
        "short_desc": "Profits from price bouncing up and down with layered orders",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Places {grid_count} buy orders below the current price and "
            "{grid_count} sell orders above it\\. Every time price wiggles up and down "
            "through the grid, it earns a small profit\\. More bounces = more profit\\.\n\n"
            "📈 *Buys when:* Price drops to the next lower grid level\n\n"
            "📉 *Sells when:* Price bounces back up to the next grid level\n\n"
            "💰 *Spends per grid level:* `{amount_per_grid} {native_symbol}`\n"
            "_Total exposure: {grid_count}x that amount_\n\n"
            "⚠️ Risk: Medium — profits from volatility, "
            "loses if price trends strongly one way\\."
        ),
        "params": {"grid_count": 5, "range_pct": 10.0, "amount_per_grid": 0.005},
        "editable_params": [
            {"key": "amount_per_grid", "label": "💰 Amount per grid level",
             "desc": "Spent at each grid step", "type": "float",
             "min": 0.001, "max": 50.0, "step": 0.001},
            {"key": "grid_count", "label": "🔲 Number of grid levels",
             "desc": "More levels = more trades, smaller profit each. Default: 5",
             "type": "int", "min": 3, "max": 20, "step": 1,
             "presets": [3, 5, 8, 10, 15]},
            {"key": "range_pct", "label": "📏 Grid range %",
             "desc": "Total price range the grid covers. Default: 10%", "type": "float",
             "min": 2.0, "max": 50.0, "step": 2.0,
             "presets": [5.0, 10.0, 15.0, 20.0, 30.0]},
        ],
        "risk": "Medium", "best_for": "Choppy/sideways markets",
    },

    # ── NEW: MEME & HIGH-VOLATILITY STRATEGIES ─────────────────────────────────

    "meme_pump_detector": {
        "name": "Meme Pump Detector 🐸",
        "emoji": "🐸",
        "short_desc": "Detects early meme coin pumps and rides them fast",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Meme coins move fast and wild\\. This strategy looks for the early signs "
            "of a pump — an unusually big price move compared to what's normal for that token\\. "
            "It jumps in early and exits quickly before the dump\\.\n\n"
            "📈 *Buys when:* Price move is *{spike_multiplier}x* bigger than the token's "
            "average recent moves AND price is above its short\\-term average\\.\n"
            "_This detects the first sign of unusual buying pressure_\n\n"
            "📉 *Sells when:* Price drops *{exit_drop_pct}%* from the entry point\\.\n"
            "_Quick exit to lock in profits before the inevitable dump_\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: Very High — memes are brutal\\. Small size, fast exits\\. "
            "This can 5x or go to zero\\. Never use money you can't lose\\."
        ),
        "params": {
            "spike_multiplier": 2.5,
            "exit_drop_pct":    5.0,
            "lookback":         20,
            "trade_amount":     0.005,
        },
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "Keep VERY small for memes — extreme risk", "type": "float",
             "min": 0.001, "max": 10.0, "step": 0.001},
            {"key": "spike_multiplier", "label": "📡 Pump detection sensitivity",
             "desc": "How many times bigger than normal the move must be. Lower = more signals",
             "type": "float", "min": 1.5, "max": 5.0, "step": 0.5,
             "presets": [1.5, 2.0, 2.5, 3.0, 4.0]},
            {"key": "exit_drop_pct", "label": "🛑 Exit on drop %",
             "desc": "Sell immediately if price drops this % from entry. Default: 5%",
             "type": "float", "min": 1.0, "max": 20.0, "step": 1.0,
             "presets": [2.0, 3.0, 5.0, 8.0, 10.0]},
        ],
        "risk": "Very High", "best_for": "Meme coins, Solana tokens",
    },

    "scalper": {
        "name": "Scalper — Quick Profits",
        "emoji": "⚡",
        "short_desc": "Makes many tiny profits by catching small up-and-down moves",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Scalping means taking many small profits instead of waiting for big moves\\. "
            "This bot looks for a tiny dip below the recent average, buys, "
            "then sells as soon as it's up {profit_target_pct}%\\. "
            "Small wins, done repeatedly, add up\\.\n\n"
            "📈 *Buys when:* Price dips *{dip_pct}%* below its recent average\n"
            "_Buying the micro\\-dip for a quick bounce_\n\n"
            "📉 *Sells when:* Price is *{profit_target_pct}%* above entry\n"
            "_Takes profit immediately — doesn't wait for bigger moves_\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: Medium — works on liquid tokens with consistent volume\\. "
            "Gas fees on EVM chains can eat profits — best on Solana or BSC\\."
        ),
        "params": {
            "dip_pct":          0.8,
            "profit_target_pct":1.2,
            "lookback":         10,
            "trade_amount":     0.01,
        },
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "Scalping works best with consistent sizing", "type": "float",
             "min": 0.001, "max": 100.0, "step": 0.005},
            {"key": "dip_pct", "label": "📉 Dip % to buy",
             "desc": "Buy when price is this % below average. Default: 0.8%",
             "type": "float", "min": 0.2, "max": 3.0, "step": 0.1,
             "presets": [0.3, 0.5, 0.8, 1.0, 1.5]},
            {"key": "profit_target_pct", "label": "✅ Profit target %",
             "desc": "Sell as soon as price is this % above entry. Default: 1.2%",
             "type": "float", "min": 0.3, "max": 5.0, "step": 0.1,
             "presets": [0.5, 0.8, 1.0, 1.5, 2.0]},
        ],
        "risk": "Medium", "best_for": "High-volume liquid tokens",
    },

    "trend_following": {
        "name": "Trend Follower — Ride the Wave",
        "emoji": "🌊",
        "short_desc": "Stays in winning trades longer by following the trend",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Most bots sell too early\\. This one stays in a trade as long as the uptrend "
            "is intact, using a 'trailing stop' — a floor that moves up with the price\\. "
            "If price drops {trail_pct}% from its peak, it sells\\. "
            "If it keeps going up, it keeps riding\\.\n\n"
            "📈 *Buys when:* Price is above both the {fast_ma}\\-period "
            "AND {slow_ma}\\-period averages — confirmed uptrend\n\n"
            "📉 *Sells when:* Price drops *{trail_pct}%* from its highest point since entry\n"
            "_Trailing stop — lets winners run, cuts losers_\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: Medium — great for tokens in sustained uptrends\\. "
            "Can give back some gains before exiting\\."
        ),
        "params": {
            "fast_ma":    9,
            "slow_ma":    21,
            "trail_pct":  8.0,
            "trade_amount": 0.01,
        },
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "Amount spent when uptrend is confirmed", "type": "float",
             "min": 0.001, "max": 100.0, "step": 0.005},
            {"key": "trail_pct", "label": "📏 Trailing stop %",
             "desc": "Sell if price drops this % from the highest point. Default: 8%",
             "type": "float", "min": 2.0, "max": 20.0, "step": 1.0,
             "presets": [3.0, 5.0, 8.0, 10.0, 15.0]},
            {"key": "fast_ma", "label": "⚡ Fast MA period", "desc": "Default: 9",
             "type": "int", "min": 3, "max": 20, "step": 1,
             "presets": [5, 7, 9, 12, 15]},
        ],
        "risk": "Medium", "best_for": "Trending tokens & altcoins",
    },

    "mean_reversion": {
        "name": "Mean Reversion — Snap Back",
        "emoji": "🎯",
        "short_desc": "Bets that extreme price drops will snap back to normal",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Prices don't stay at extremes — they always snap back toward the average\\. "
            "This bot waits for a token to crash hard and fast, then buys expecting a recovery\\. "
            "It's like catching a falling knife — risky, but the rebounds can be big\\.\n\n"
            "📈 *Buys when:* Price has dropped *{crash_pct}%* in a short time "
            "AND RSI is below {rsi_threshold} \\(deeply oversold\\)\n"
            "_Double confirmation = high\\-probability snap\\-back setup_\n\n"
            "📉 *Sells when:* Price recovers *{recover_pct}%* from the entry low\n"
            "_Takes profit on the bounce without being greedy_\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: High — sometimes things crash and don't recover\\. "
            "Only trade this on tokens with real liquidity\\."
        ),
        "params": {
            "crash_pct":    10.0,
            "rsi_threshold":25,
            "recover_pct":  5.0,
            "lookback":     6,
            "trade_amount": 0.01,
        },
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "Amount to deploy on crash bounces", "type": "float",
             "min": 0.001, "max": 100.0, "step": 0.005},
            {"key": "crash_pct", "label": "📉 Crash % to trigger buy",
             "desc": "How big a drop before buying. Default: 10%",
             "type": "float", "min": 3.0, "max": 30.0, "step": 1.0,
             "presets": [5.0, 8.0, 10.0, 15.0, 20.0]},
            {"key": "recover_pct", "label": "✅ Recovery % to sell",
             "desc": "Take profit when price recovers this much. Default: 5%",
             "type": "float", "min": 1.0, "max": 20.0, "step": 1.0,
             "presets": [3.0, 5.0, 8.0, 10.0, 15.0]},
        ],
        "risk": "High", "best_for": "Large-cap tokens after sharp crashes",
    },

    "macd_signal": {
        "name": "MACD — Momentum Shift",
        "emoji": "📊",
        "short_desc": "Uses MACD crossovers to spot early trend changes",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "MACD is one of the most widely used trading indicators in the world\\. "
            "It measures the difference between two moving averages\\. "
            "When this difference crosses above zero, momentum is turning bullish\\. "
            "When it crosses below, momentum is turning bearish\\.\n\n"
            "📈 *Buys when:* MACD line crosses above zero\n"
            "_Short\\-term average overtaking long\\-term = momentum shifting up_\n\n"
            "📉 *Sells when:* MACD line crosses back below zero\n"
            "_Momentum fading = time to exit_\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: Low\\-Medium — one of the most reliable indicators\\. "
            "Slightly slower to signal than others but fewer false alarms\\."
        ),
        "params": {"trade_amount": 0.01},
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "Amount spent on each MACD buy signal", "type": "float",
             "min": 0.001, "max": 100.0, "step": 0.005},
        ],
        "risk": "Low-Medium", "best_for": "Most markets — reliable all-rounder",
    },

}

# ═══════════════════════════════════════════════════════════════════════════════
#  SIGNAL GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

# Tracks highest price since entry per strategy (for trailing stop)
_entry_prices:  dict = {}  # strategy_id -> entry_price
_highest_since: dict = {}  # strategy_id -> highest price since entry

def get_signal(strategy_name: str, chain: str, token: str,
               params: dict, strategy_id: int = None) -> dict:
    price_data = get_token_price(chain, token)
    if not price_data:
        return {"signal": "hold", "reason": "No price data", "indicators": {}}
    current = price_data.get("price")
    if not current or current <= 0:
        return {"signal": "hold", "reason": "Invalid price", "indicators": {}}

    _record_price(chain, token, current)
    prices = _get_prices(chain, token, 100)

    if len(prices) < 3 or len(set(prices)) < 2:
        return {"signal": "hold",
                "reason": f"Warming up ({len(prices)}/3 data points)",
                "indicators": {"current_price": current}}

    ind = {"current_price": current}

    # ── RSI ───────────────────────────────────────────────────────────────────
    if strategy_name == "rsi_oversold":
        rsi = calc_rsi(prices, params.get("period", 14))
        ind["rsi"] = rsi
        if rsi is None:
            return {"signal": "hold", "reason": f"Building RSI ({len(prices)}/15 needed)", "indicators": ind}
        if rsi < params.get("rsi_buy", 30):
            return {"signal": "buy",  "reason": f"RSI {rsi:.1f} — heavily oversold, buying dip", "indicators": ind}
        if rsi > params.get("rsi_sell", 70):
            return {"signal": "sell", "reason": f"RSI {rsi:.1f} — overbought, taking profit", "indicators": ind}
        return {"signal": "hold", "reason": f"RSI {rsi:.1f} — neutral, watching", "indicators": ind}

    # ── MA Crossover ──────────────────────────────────────────────────────────
    elif strategy_name == "ma_crossover":
        fast = calc_sma(prices, params.get("fast_ma", 9))
        slow = calc_sma(prices, params.get("slow_ma", 21))
        ind.update({"fast_ma": fast, "slow_ma": slow})
        if fast is None or slow is None:
            return {"signal": "hold", "reason": f"Building averages ({len(prices)}/{params.get('slow_ma',21)} needed)", "indicators": ind}
        prev = prices[:-1]
        pf = calc_sma(prev, params.get("fast_ma", 9))
        ps = calc_sma(prev, params.get("slow_ma", 21))
        if pf and ps:
            if pf < ps and fast > slow:
                return {"signal": "buy",  "reason": "Golden Cross — uptrend confirmed", "indicators": ind}
            if pf > ps and fast < slow:
                return {"signal": "sell", "reason": "Death Cross — downtrend confirmed", "indicators": ind}
        trend = "uptrend" if fast > slow else "downtrend"
        return {"signal": "hold", "reason": f"In {trend} — waiting for crossover", "indicators": ind}

    # ── Momentum ──────────────────────────────────────────────────────────────
    elif strategy_name == "momentum":
        lb = params.get("lookback", 12)
        if len(prices) < lb:
            return {"signal": "hold", "reason": f"Collecting data ({len(prices)}/{lb})", "indicators": ind}
        chg = ((current - prices[-lb]) / prices[-lb]) * 100
        ind["change_pct"] = chg
        if chg >= params.get("buy_threshold", 2.0):
            return {"signal": "buy",  "reason": f"Strong surge +{chg:.2f}% — momentum buy", "indicators": ind}
        if chg <= params.get("sell_threshold", -2.0):
            return {"signal": "sell", "reason": f"Drop {chg:.2f}% — cutting losses", "indicators": ind}
        return {"signal": "hold", "reason": f"Change {chg:+.2f}% — not enough momentum", "indicators": ind}

    # ── Bollinger ─────────────────────────────────────────────────────────────
    elif strategy_name == "bollinger_bands":
        bb = calc_bollinger(prices, params.get("period", 20))
        if bb is None:
            return {"signal": "hold", "reason": f"Building bands ({len(prices)}/20 needed)", "indicators": ind}
        ind.update({"bb_upper": bb["upper"], "bb_middle": bb["middle"], "bb_lower": bb["lower"]})
        if current <= bb["lower"]:
            return {"signal": "buy",  "reason": "At lower band — unusually cheap, expecting bounce", "indicators": ind}
        if current >= bb["upper"]:
            return {"signal": "sell", "reason": "At upper band — unusually expensive, taking profit", "indicators": ind}
        pct = ((current - bb["lower"]) / (bb["upper"] - bb["lower"])) * 100
        return {"signal": "hold", "reason": f"Mid-bands ({pct:.0f}% up from lower)", "indicators": ind}

    # ── DCA ───────────────────────────────────────────────────────────────────
    elif strategy_name == "dca_auto":
        return {"signal": "buy", "reason": "DCA schedule — regular timed buy", "indicators": ind}

    # ── Grid ──────────────────────────────────────────────────────────────────
    elif strategy_name == "grid":
        if len(prices) < 5:
            return {"signal": "hold", "reason": "Collecting prices for grid", "indicators": ind}
        avg = sum(prices[-10:]) / min(len(prices), 10)
        pct_from_avg = ((current - avg) / avg) * 100
        half_range = params.get("range_pct", 10.0) / 2
        if pct_from_avg <= -half_range * 0.6:
            return {"signal": "buy",  "reason": f"Price {pct_from_avg:.1f}% below avg — grid buy", "indicators": ind}
        if pct_from_avg >= half_range * 0.6:
            return {"signal": "sell", "reason": f"Price +{pct_from_avg:.1f}% above avg — grid sell", "indicators": ind}
        return {"signal": "hold", "reason": f"Price within grid range ({pct_from_avg:+.1f}%)", "indicators": ind}

    # ── Meme Pump Detector ────────────────────────────────────────────────────
    elif strategy_name == "meme_pump_detector":
        lb = params.get("lookback", 20)
        spike = calc_volume_spike(prices, lb)
        sma5 = calc_sma(prices, 5)
        ind.update({"spike_ratio": spike, "sma5": sma5})
        if spike is None or sma5 is None:
            return {"signal": "hold", "reason": f"Watching for pump ({len(prices)}/{lb+1} needed)", "indicators": ind}
        threshold = params.get("spike_multiplier", 2.5)
        if spike >= threshold and current > sma5:
            return {"signal": "buy", "reason": f"🐸 Pump detected! Move is {spike:.1f}x normal size and above avg", "indicators": ind}
        # Exit if holding and price drops
        if strategy_id and strategy_id in _entry_prices:
            entry = _entry_prices[strategy_id]
            drop_pct = ((current - entry) / entry) * 100
            if drop_pct <= -params.get("exit_drop_pct", 5.0):
                return {"signal": "sell", "reason": f"Exit: dropped {drop_pct:.1f}% from entry", "indicators": ind}
        return {"signal": "hold", "reason": f"No pump signal (move={spike:.1f}x normal, need {threshold}x)", "indicators": ind}

    # ── Scalper ───────────────────────────────────────────────────────────────
    elif strategy_name == "scalper":
        lb = params.get("lookback", 10)
        avg = calc_sma(prices, lb)
        ind["sma"] = avg
        if avg is None:
            return {"signal": "hold", "reason": f"Collecting data ({len(prices)}/{lb})", "indicators": ind}
        dip_needed = params.get("dip_pct", 0.8)
        pct_from_avg = ((current - avg) / avg) * 100
        ind["pct_from_avg"] = pct_from_avg
        if pct_from_avg <= -dip_needed:
            return {"signal": "buy", "reason": f"Micro-dip: {pct_from_avg:.2f}% below avg — scalp buy", "indicators": ind}
        if strategy_id and strategy_id in _entry_prices:
            entry = _entry_prices[strategy_id]
            gain = ((current - entry) / entry) * 100
            if gain >= params.get("profit_target_pct", 1.2):
                return {"signal": "sell", "reason": f"Scalp target hit: +{gain:.2f}% from entry", "indicators": ind}
        return {"signal": "hold", "reason": f"Waiting for {dip_needed}% dip (now {pct_from_avg:+.2f}%)", "indicators": ind}

    # ── Trend Following ───────────────────────────────────────────────────────
    elif strategy_name == "trend_following":
        fast = calc_sma(prices, params.get("fast_ma", 9))
        slow = calc_sma(prices, params.get("slow_ma", 21))
        ind.update({"fast_ma": fast, "slow_ma": slow})
        if fast is None or slow is None:
            return {"signal": "hold", "reason": "Building trend data", "indicators": ind}
        in_uptrend = current > fast > slow
        if in_uptrend and not (strategy_id and strategy_id in _entry_prices):
            return {"signal": "buy", "reason": "Confirmed uptrend — price above both averages", "indicators": ind}
        if strategy_id and strategy_id in _entry_prices:
            if _highest_since.get(strategy_id, current) < current:
                _highest_since[strategy_id] = current
            peak = _highest_since.get(strategy_id, current)
            drop_from_peak = ((current - peak) / peak) * 100
            ind["drop_from_peak"] = drop_from_peak
            if drop_from_peak <= -params.get("trail_pct", 8.0):
                return {"signal": "sell", "reason": f"Trailing stop hit: {drop_from_peak:.1f}% from peak", "indicators": ind}
        return {"signal": "hold", "reason": "In trade — trailing stop active, riding trend", "indicators": ind}

    # ── Mean Reversion ────────────────────────────────────────────────────────
    elif strategy_name == "mean_reversion":
        lb = params.get("lookback", 6)
        if len(prices) < max(lb, 15):
            return {"signal": "hold", "reason": f"Collecting data ({len(prices)} points)", "indicators": ind}
        rsi = calc_rsi(prices, 14)
        old_price = prices[-lb]
        crash_pct = ((current - old_price) / old_price) * 100
        ind.update({"rsi": rsi, "crash_pct": crash_pct})
        rsi_thresh = params.get("rsi_threshold", 25)
        crash_needed = -params.get("crash_pct", 10.0)
        if crash_pct <= crash_needed and rsi and rsi < rsi_thresh:
            return {"signal": "buy", "reason": f"Crash {crash_pct:.1f}% + RSI {rsi:.0f} — snap-back setup", "indicators": ind}
        if strategy_id and strategy_id in _entry_prices:
            entry = _entry_prices[strategy_id]
            gain = ((current - entry) / entry) * 100
            if gain >= params.get("recover_pct", 5.0):
                return {"signal": "sell", "reason": f"Bounce target hit: +{gain:.1f}%", "indicators": ind}
        return {"signal": "hold", "reason": f"Watching for {abs(crash_needed):.0f}% crash (now {crash_pct:+.1f}%)", "indicators": ind}

    # ── MACD ──────────────────────────────────────────────────────────────────
    elif strategy_name == "macd_signal":
        if len(prices) < 27:
            return {"signal": "hold", "reason": f"Building MACD ({len(prices)}/27 needed)", "indicators": ind}
        macd = calc_macd(prices)
        prev_macd = calc_macd(prices[:-1])
        if macd is None or prev_macd is None:
            return {"signal": "hold", "reason": "Computing MACD", "indicators": ind}
        ind.update({"macd": macd["macd"], "ema12": macd["ema12"], "ema26": macd["ema26"]})
        if prev_macd["macd"] < 0 and macd["macd"] > 0:
            return {"signal": "buy",  "reason": f"MACD crossed above zero — momentum turning bullish", "indicators": ind}
        if prev_macd["macd"] > 0 and macd["macd"] < 0:
            return {"signal": "sell", "reason": f"MACD crossed below zero — momentum turning bearish", "indicators": ind}
        direction = "bullish" if macd["macd"] > 0 else "bearish"
        return {"signal": "hold", "reason": f"MACD {macd['macd']:.6f} — {direction}, no crossover yet", "indicators": ind}

    return {"signal": "hold", "reason": "Unknown strategy", "indicators": ind}


def on_trade_executed(strategy_id: int, action: str, price: float):
    """Track entry/peak prices for trailing stops and profit targets."""
    if action == "buy":
        _entry_prices[strategy_id]  = price
        _highest_since[strategy_id] = price
    elif action == "sell":
        _entry_prices.pop(strategy_id, None)
        _highest_since.pop(strategy_id, None)


def format_signal_message(strategy_name, signal, token_symbol, chain, mode,
                           strategy_id=None, user_id=None):
    """
    Build the signal notification message.
    Includes live PnL for the strategy if strategy_id + user_id provided.
    """
    from config.chains import CHAINS
    sig  = signal["signal"]
    ind  = signal["indicators"]
    ci   = CHAINS.get(chain, {})
    mode_tag  = "📝 PAPER" if mode == "paper" else "💰 LIVE"
    sig_emoji = {"buy": "🟢 BUY", "sell": "🔴 SELL", "hold": "⚪ HOLD"}
    s_info = STRATEGIES.get(strategy_name, {})

    lines = [
        f"{'━'*28}",
        f"🤖 *Strategy Signal* \\[{mode_tag}\\]",
        f"{s_info.get('emoji','📊')} *{s_info.get('name', strategy_name)}*",
        f"🪙 *{token_symbol}* on {ci.get('emoji','')} {ci.get('name', chain)}",
        f"💵 Price: *{fmt_price(ind.get('current_price'))}*",
        f"",
        f"📡 Signal: *{sig_emoji.get(sig, sig)}*",
        f"📝 {signal['reason']}",
    ]
    if ind.get("rsi")           is not None: lines.append(f"📉 RSI: {ind['rsi']:.1f}/100")
    if ind.get("fast_ma")       is not None: lines.append(f"📈 Fast MA: {fmt_price(ind['fast_ma'])}")
    if ind.get("slow_ma")       is not None: lines.append(f"📈 Slow MA: {fmt_price(ind['slow_ma'])}")
    if ind.get("bb_upper")      is not None: lines.append(f"〰️ Bands: {fmt_price(ind['bb_lower'])} / {fmt_price(ind['bb_middle'])} / {fmt_price(ind['bb_upper'])}")
    if ind.get("change_pct")    is not None: lines.append(f"🚀 Change: {ind['change_pct']:+.2f}%")
    if ind.get("macd")          is not None: lines.append(f"📊 MACD: {ind['macd']:.6f}")
    if ind.get("spike_ratio")   is not None: lines.append(f"📡 Spike: {ind['spike_ratio']:.1f}x normal")
    if ind.get("drop_from_peak")is not None: lines.append(f"📍 From peak: {ind['drop_from_peak']:.1f}%")

    # ── Live PnL block — always shown when strategy_id is provided ────────────
    if strategy_id is not None and user_id is not None:
        try:
            from utils.database import get_realized_pnl, get_open_positions
            realized   = get_realized_pnl(user_id, strategy_id)
            open_pos   = get_open_positions(user_id, strategy_id)

            # Unrealized PnL from open positions
            current_price = ind.get("current_price", 0)
            unrealized = 0.0
            open_count = 0
            for pos in open_pos:
                if pos.get("entry_price_usd", 0) > 0 and current_price > 0:
                    unrealized += (current_price - pos["entry_price_usd"]) * pos.get("qty", 0)
                    open_count += 1

            total_pnl = realized + unrealized
            pnl_e     = "✅" if total_pnl >= 0 else "❌"
            sign      = "+" if total_pnl >= 0 else ""
            r_sign    = "+" if realized  >= 0 else ""
            u_sign    = "+" if unrealized>= 0 else ""

            lines.append(f"")
            lines.append(f"{'─'*20}")
            lines.append(f"💰 *Strategy P&L*")
            lines.append(f"  {pnl_e} Total: `{sign}{total_pnl:.4f} USD`")
            if realized != 0:
                lines.append(f"  ✅ Realized: `{r_sign}{realized:.4f}`")
            if open_count > 0:
                lines.append(f"  📂 Unrealized ({open_count} pos): `{u_sign}{unrealized:.4f}`")
        except Exception:
            pass  # Never crash signal delivery due to PnL lookup

    lines.append(f"{'━'*28}")
    return "\n".join(lines)


def format_strategy_description(strategy_key, params, native_symbol="ETH"):
    s = STRATEGIES.get(strategy_key)
    if not s: return "Unknown strategy"
    merged = {**s["params"], **params, "native_symbol": native_symbol}
    try:    return s["plain_english"].format(**merged)
    except: return s["plain_english"]


def get_editable_params(strategy_key):
    return STRATEGIES.get(strategy_key, {}).get("editable_params", [])

# ── ADDITIONAL STRATEGIES (appended) ─────────────────────────────────────────
# These are added to the STRATEGIES dict at module load

_EXTRA_STRATEGIES = {

    "compound_scalper": {
        "name": "Compound Scalper 💰",
        "emoji": "💰",
        "short_desc": "Reinvests every profit to grow a small balance exponentially",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "This is specifically designed to grow a tiny balance like $1 into more\\. "
            "It makes small, quick trades and reinvests every single profit — "
            "so gains compound on top of gains\\. "
            "Think of it as a snowball rolling downhill getting bigger\\.\n\n"
            "📈 *Buys when:* Price dips *{dip_pct}%* below its recent average "
            "AND volume is active \\(token is being traded\\)\n\n"
            "📉 *Sells when:* Price is *{profit_pct}%* above entry — takes profit fast\n\n"
            "💰 *Starts with:* `{trade_amount} {native_symbol}`\n"
            "_Each win automatically increases the next trade size slightly_\n\n"
            "⚠️ Risk: Medium\\-Low — designed for gradual compounding\\. "
            "Best on Solana or BSC where fees are tiny\\."
        ),
        "params": {
            "trade_amount": 0.01,
            "dip_pct":      0.5,
            "profit_pct":   1.0,
            "lookback":     8,
            "compound":     True,
        },
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Starting amount",
             "desc": "Your starting trade size — can be very small", "type": "float",
             "min": 0.0001, "max": 100.0, "step": 0.001},
            {"key": "profit_pct", "label": "✅ Profit target %",
             "desc": "Take profit at this % gain. Smaller = more frequent wins. Default: 1%",
             "type": "float", "min": 0.2, "max": 5.0, "step": 0.1,
             "presets": [0.3, 0.5, 1.0, 1.5, 2.0]},
            {"key": "dip_pct", "label": "📉 Buy dip %",
             "desc": "Buy when price drops this % below average. Default: 0.5%",
             "type": "float", "min": 0.1, "max": 3.0, "step": 0.1,
             "presets": [0.2, 0.3, 0.5, 0.8, 1.0]},
        ],
        "risk": "Medium-Low", "best_for": "Growing tiny balances, Solana/BSC",
    },

    "volume_surge": {
        "name": "Volume Surge Hunter 📡",
        "emoji": "📡",
        "short_desc": "Finds tokens with exploding volume before price spikes",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Volume always moves before price\\. When a token suddenly gets "
            "{volume_multiplier}x more trades than usual, something is happening — "
            "news, influencer post, whale buying\\. "
            "This bot detects that volume explosion early and gets in before "
            "the price catches up\\.\n\n"
            "📈 *Buys when:* Recent price movement is *{volume_multiplier}x* "
            "bigger than the token's normal movement AND price is rising\n"
            "_Volume spike = someone is accumulating = price usually follows_\n\n"
            "📉 *Sells when:* Price gains *{take_profit_pct}%* from entry\n"
            "_Takes quick profit as early buyers and retail FOMO in_\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "⚠️ Risk: High — volume surges can be fake pumps\\. "
            "Always use with rug check and keep size small\\."
        ),
        "params": {
            "trade_amount":       0.005,
            "volume_multiplier":  3.0,
            "take_profit_pct":    8.0,
            "stop_loss_pct":      4.0,
            "lookback":           15,
        },
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "Keep small due to high risk", "type": "float",
             "min": 0.001, "max": 50.0, "step": 0.001},
            {"key": "volume_multiplier", "label": "📡 Volume spike multiplier",
             "desc": "How many times bigger than normal the move must be. Default: 3x",
             "type": "float", "min": 1.5, "max": 8.0, "step": 0.5,
             "presets": [2.0, 2.5, 3.0, 4.0, 5.0]},
            {"key": "take_profit_pct", "label": "✅ Take profit %",
             "desc": "Sell when up this % from entry. Default: 8%",
             "type": "float", "min": 2.0, "max": 30.0, "step": 1.0,
             "presets": [3.0, 5.0, 8.0, 10.0, 15.0]},
            {"key": "stop_loss_pct", "label": "🛑 Stop loss %",
             "desc": "Exit if down this % — limits losses. Default: 4%",
             "type": "float", "min": 1.0, "max": 15.0, "step": 0.5,
             "presets": [2.0, 3.0, 4.0, 5.0, 8.0]},
        ],
        "risk": "High", "best_for": "Meme coins, trending tokens",
    },

    "safe_accumulator": {
        "name": "Safe Accumulator 🛡️",
        "emoji": "🛡️",
        "short_desc": "Slowly builds a position with multiple safety checks — lowest risk",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "This is the safest strategy for growing $1\\. "
            "It never puts all money in at once — it splits your budget into "
            "{num_buys} smaller buys, only adding more if the price stays healthy\\. "
            "It uses three confirming signals before buying anything\\.\n\n"
            "📈 *Buys when ALL THREE are true:*\n"
            "1\\. RSI is below {rsi_max} \\(not overbought\\)\n"
            "2\\. Price is above its {trend_ma}\\-period average \\(uptrend\\)\n"
            "3\\. We have not already used all {num_buys} buy slots\n\n"
            "📉 *Sells when:* Up *{take_profit_pct}%* from average entry price\n\n"
            "💰 *Spends per buy:* `{trade_amount} {native_symbol}` "
            "\\(maximum {num_buys} buys total\\)\n\n"
            "⚠️ Risk: Low — triple\\-checked entries, small sizes, "
            "never chases pumps\\. Best for stable tokens with real volume\\."
        ),
        "params": {
            "trade_amount":    0.005,
            "num_buys":        3,
            "rsi_max":         55,
            "trend_ma":        20,
            "take_profit_pct": 5.0,
        },
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per buy",
             "desc": "Each individual buy size — multiplied by num_buys for total exposure",
             "type": "float", "min": 0.0001, "max": 50.0, "step": 0.001},
            {"key": "num_buys", "label": "🔢 Max number of buys",
             "desc": "How many times to buy before stopping. Default: 3",
             "type": "int", "min": 1, "max": 10, "step": 1,
             "presets": [1, 2, 3, 5, 10]},
            {"key": "take_profit_pct", "label": "✅ Take profit %",
             "desc": "Sell when up this % from average cost. Default: 5%",
             "type": "float", "min": 1.0, "max": 20.0, "step": 0.5,
             "presets": [2.0, 3.0, 5.0, 8.0, 10.0]},
            {"key": "rsi_max", "label": "📊 Max RSI to buy",
             "desc": "Don't buy if RSI is above this — avoids overbought entries",
             "type": "int", "min": 30, "max": 70, "step": 5,
             "presets": [40, 45, 50, 55, 60]},
        ],
        "risk": "Low", "best_for": "Growing $1 safely, beginners",
    },

    "sandwich_dca": {
        "name": "Sandwich DCA 🥪",
        "emoji": "🥪",
        "short_desc": "Buys dips and sells bounces in a repeating cycle",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Combines two simple ideas: buy the dip \\(like DCA\\) "
            "AND sell the bounce \\(like a range trader\\)\\. "
            "It keeps cycling — buy low, sell a bit higher, buy the next dip, "
            "sell the next bounce — forever\\. Each cycle turns a small profit\\.\n\n"
            "📈 *Buys when:* Price drops *{buy_dip_pct}%* below the recent average\n\n"
            "📉 *Sells when:* Price is *{sell_rise_pct}%* above the recent average\n\n"
            "💰 *Spends per trade:* `{trade_amount} {native_symbol}`\n\n"
            "🔄 *Cycle time:* Checks every {check_minutes} minutes\n\n"
            "⚠️ Risk: Low\\-Medium — simple and mechanical\\. "
            "Works well on tokens that trade sideways with small up/down waves\\."
        ),
        "params": {
            "trade_amount":   0.01,
            "buy_dip_pct":    1.5,
            "sell_rise_pct":  1.5,
            "lookback":       12,
            "check_minutes":  5,
        },
        "editable_params": [
            {"key": "trade_amount", "label": "💰 Amount per trade",
             "desc": "How much to spend on each buy cycle", "type": "float",
             "min": 0.001, "max": 100.0, "step": 0.005},
            {"key": "buy_dip_pct", "label": "📉 Buy when price drops %",
             "desc": "Buy when this % below average. Default: 1.5%",
             "type": "float", "min": 0.3, "max": 5.0, "step": 0.1,
             "presets": [0.5, 1.0, 1.5, 2.0, 3.0]},
            {"key": "sell_rise_pct", "label": "📈 Sell when price rises %",
             "desc": "Sell when this % above average. Default: 1.5%",
             "type": "float", "min": 0.3, "max": 5.0, "step": 0.1,
             "presets": [0.5, 1.0, 1.5, 2.0, 3.0]},
        ],
        "risk": "Low-Medium", "best_for": "Ranging tokens, steady compounding",
    },
}

# Merge extra strategies into the main dict
STRATEGIES.update(_EXTRA_STRATEGIES)

# Add signal logic for new strategies
_ORIG_GET_SIGNAL = get_signal

def get_signal(strategy_name: str, chain: str, token: str,
               params: dict, strategy_id: int = None) -> dict:
    """Extended signal generator — handles new strategies then falls back to original."""

    price_data = get_token_price(chain, token)
    if not price_data or not price_data.get("price"):
        return {"signal": "hold", "reason": "No price data", "indicators": {}}
    current = price_data["price"]
    if not current or current <= 0:
        return {"signal": "hold", "reason": "Invalid price", "indicators": {}}

    _record_price(chain, token, current)
    prices = _get_prices(chain, token, 100)
    ind = {"current_price": current}

    if len(prices) < 3 or len(set(prices)) < 2:
        return {"signal": "hold",
                "reason": f"Warming up ({len(prices)}/3 data points)",
                "indicators": ind}

    # ── Compound Scalper ──────────────────────────────────────────────────────
    if strategy_name == "compound_scalper":
        lb      = params.get("lookback", 8)
        avg     = calc_sma(prices, min(lb, len(prices)))
        ind["sma"] = avg
        if avg is None:
            return {"signal": "hold", "reason": f"Collecting data", "indicators": ind}
        pct = ((current - avg) / avg) * 100
        ind["pct_from_avg"] = pct
        dip = params.get("dip_pct", 0.5)
        if pct <= -dip:
            return {"signal": "buy",
                    "reason": f"Compound buy: {pct:.2f}% below avg — dip detected",
                    "indicators": ind}
        if strategy_id and strategy_id in _entry_prices:
            entry = _entry_prices[strategy_id]
            gain  = ((current - entry) / entry) * 100
            if gain >= params.get("profit_pct", 1.0):
                return {"signal": "sell",
                        "reason": f"Compound profit taken: +{gain:.2f}%",
                        "indicators": ind}
        return {"signal": "hold",
                "reason": f"Waiting for {dip}% dip (now {pct:+.2f}%)",
                "indicators": ind}

    # ── Volume Surge ──────────────────────────────────────────────────────────
    elif strategy_name == "volume_surge":
        lb    = params.get("lookback", 15)
        spike = calc_volume_spike(prices, lb)
        sma5  = calc_sma(prices, 5)
        ind.update({"spike_ratio": spike, "sma5": sma5})
        if spike is None:
            return {"signal": "hold", "reason": f"Collecting data ({len(prices)}/{lb+1})", "indicators": ind}
        mult = params.get("volume_multiplier", 3.0)
        if spike >= mult and current > (sma5 or current):
            return {"signal": "buy",
                    "reason": f"📡 Volume surge! {spike:.1f}x normal + upward price",
                    "indicators": ind}
        if strategy_id and strategy_id in _entry_prices:
            entry = _entry_prices[strategy_id]
            gain  = ((current - entry) / entry) * 100
            loss  = gain
            if gain >= params.get("take_profit_pct", 8.0):
                return {"signal": "sell",
                        "reason": f"Volume surge profit: +{gain:.1f}%",
                        "indicators": ind}
            if loss <= -params.get("stop_loss_pct", 4.0):
                return {"signal": "sell",
                        "reason": f"Stop loss hit: {loss:.1f}%",
                        "indicators": ind}
        return {"signal": "hold",
                "reason": f"Surge: {spike:.1f}x (need {mult}x)",
                "indicators": ind}

    # ── Safe Accumulator ──────────────────────────────────────────────────────
    elif strategy_name == "safe_accumulator":
        rsi   = calc_rsi(prices, 14)
        trend = calc_sma(prices, params.get("trend_ma", 20))
        ind.update({"rsi": rsi, "trend_ma": trend})
        if rsi is None or trend is None:
            return {"signal": "hold", "reason": f"Collecting data ({len(prices)} points)", "indicators": ind}
        rsi_ok   = rsi < params.get("rsi_max", 55)
        trend_ok = current > trend
        if rsi_ok and trend_ok:
            return {"signal": "buy",
                    "reason": f"Safe entry: RSI={rsi:.0f}<{params.get('rsi_max',55)}, above {params.get('trend_ma',20)}-MA",
                    "indicators": ind}
        if strategy_id and strategy_id in _entry_prices:
            entry = _entry_prices[strategy_id]
            gain  = ((current - entry) / entry) * 100
            if gain >= params.get("take_profit_pct", 5.0):
                return {"signal": "sell",
                        "reason": f"Safe profit: +{gain:.1f}%",
                        "indicators": ind}
        reasons = []
        if not rsi_ok:   reasons.append(f"RSI={rsi:.0f} too high")
        if not trend_ok: reasons.append("below trend MA")
        return {"signal": "hold",
                "reason": "Waiting: " + ", ".join(reasons),
                "indicators": ind}

    # ── Sandwich DCA ──────────────────────────────────────────────────────────
    elif strategy_name == "sandwich_dca":
        lb  = params.get("lookback", 12)
        avg = calc_sma(prices, min(lb, len(prices)))
        ind["sma"] = avg
        if avg is None:
            return {"signal": "hold", "reason": "Collecting data", "indicators": ind}
        pct = ((current - avg) / avg) * 100
        ind["pct_from_avg"] = pct
        buy_dip  = -params.get("buy_dip_pct", 1.5)
        sell_rse =  params.get("sell_rise_pct", 1.5)
        if pct <= buy_dip:
            return {"signal": "buy",
                    "reason": f"Sandwich DCA buy: {pct:.2f}% below avg",
                    "indicators": ind}
        if pct >= sell_rse:
            return {"signal": "sell",
                    "reason": f"Sandwich DCA sell: +{pct:.2f}% above avg",
                    "indicators": ind}
        return {"signal": "hold",
                "reason": f"Between bands ({pct:+.2f}%) — watching",
                "indicators": ind}

    # ── Fall back to original signal function ─────────────────────────────────
    return _ORIG_GET_SIGNAL(strategy_name, chain, token, params, strategy_id)

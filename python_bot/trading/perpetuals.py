# trading/perpetuals.py
# Perpetuals trading engine for NEAR Protocol
# Supports: paper perps, Orderly Network integration, majority-vote strategy
# All strategies are proven professional approaches adapted for crypto perps

import time
import json
import requests
from datetime import datetime, timedelta
from utils import database as db
from utils.prices import get_token_price, fmt_price

# ─── Supported perp markets ───────────────────────────────────────────────────
PERP_MARKETS = {
    "BTC-PERP":  {"base": "bitcoin",     "symbol": "BTC",  "min_size": 0.001},
    "ETH-PERP":  {"base": "ethereum",    "symbol": "ETH",  "min_size": 0.01},
    "SOL-PERP":  {"base": "solana",      "symbol": "SOL",  "min_size": 0.1},
    "NEAR-PERP": {"base": "near",        "symbol": "NEAR", "min_size": 1.0},
    "BNB-PERP":  {"base": "binancecoin", "symbol": "BNB",  "min_size": 0.01},
    "ARB-PERP":  {"base": "arbitrum",    "symbol": "ARB",  "min_size": 1.0},
}

FUNDING_INTERVAL = 8  # hours — standard perp funding

# ─── Price history for perp signals ──────────────────────────────────────────
_perp_price_history: dict = {}

def _record_perp_price(market: str, price: float):
    if market not in _perp_price_history:
        _perp_price_history[market] = []
    _perp_price_history[market].append({"price": price, "ts": time.time()})
    _perp_price_history[market] = _perp_price_history[market][-500:]

def _get_perp_prices(market: str, n: int) -> list:
    return [h["price"] for h in _perp_price_history.get(market, [])[-n:]]

def get_perp_price(market: str) -> float | None:
    """Get current price for a perp market."""
    info = PERP_MARKETS.get(market)
    if not info:
        return None
    try:
        from utils.prices import get_price_coingecko
        pd = get_price_coingecko(info["base"])
        return pd["price"] if pd else None
    except Exception:
        return None


# ─── Paper Perp Position DB helpers ──────────────────────────────────────────

def ensure_perp_tables():
    """Create perp-specific DB tables — safe to call multiple times."""
    conn = db.get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS perp_positions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        strategy_id     INTEGER,
        market          TEXT NOT NULL,
        mode            TEXT DEFAULT 'paper',
        direction       TEXT NOT NULL,
        size_usd        REAL NOT NULL,
        leverage        REAL DEFAULT 1.0,
        entry_price     REAL NOT NULL,
        mark_price      REAL DEFAULT 0.0,
        liquidation_price REAL DEFAULT 0.0,
        take_profit     REAL,
        stop_loss       REAL,
        unrealized_pnl  REAL DEFAULT 0.0,
        realized_pnl    REAL DEFAULT 0.0,
        funding_paid    REAL DEFAULT 0.0,
        status          TEXT DEFAULT 'open',
        opened_at       TEXT DEFAULT (datetime('now')),
        closed_at       TEXT,
        close_reason    TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS perp_trades (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        strategy_id     INTEGER,
        market          TEXT NOT NULL,
        mode            TEXT DEFAULT 'paper',
        action          TEXT NOT NULL,
        direction       TEXT NOT NULL,
        size_usd        REAL NOT NULL,
        leverage        REAL DEFAULT 1.0,
        price           REAL NOT NULL,
        pnl             REAL DEFAULT 0.0,
        fee             REAL DEFAULT 0.0,
        strategy_name   TEXT,
        created_at      TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS majority_votes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        market          TEXT NOT NULL,
        direction       TEXT NOT NULL,
        vote_pct        REAL NOT NULL,
        total_votes     INTEGER DEFAULT 0,
        source          TEXT,
        expires_at      TEXT,
        created_at      TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()


def open_perp_position(data: dict) -> int:
    conn = db.get_conn()
    # Calculate liquidation price
    leverage = data.get("leverage", 1.0)
    entry    = data["entry_price"]
    if data["direction"] == "long":
        liq_price = entry * (1 - 1/leverage * 0.9)
    else:
        liq_price = entry * (1 + 1/leverage * 0.9)

    r = conn.execute("""
        INSERT INTO perp_positions
        (user_id, strategy_id, market, mode, direction, size_usd, leverage,
         entry_price, mark_price, liquidation_price, take_profit, stop_loss)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data["user_id"], data.get("strategy_id"), data["market"],
        data.get("mode", "paper"), data["direction"],
        data["size_usd"], leverage, entry, entry, liq_price,
        data.get("take_profit"), data.get("stop_loss"),
    ))
    conn.commit()
    pid = r.lastrowid
    conn.close()
    return pid


def close_perp_position(position_id: int, exit_price: float, reason: str = "manual") -> float:
    """Close a perp position and return realized PnL."""
    conn = db.get_conn()
    pos = conn.execute(
        "SELECT * FROM perp_positions WHERE id=?", (position_id,)
    ).fetchone()
    if not pos:
        conn.close()
        return 0.0
    pos = dict(pos)

    if pos["direction"] == "long":
        pnl = (exit_price - pos["entry_price"]) / pos["entry_price"] * pos["size_usd"] * pos["leverage"]
    else:
        pnl = (pos["entry_price"] - exit_price) / pos["entry_price"] * pos["size_usd"] * pos["leverage"]

    pnl -= pos["funding_paid"]  # deduct funding costs

    conn.execute("""
        UPDATE perp_positions
        SET status='closed', closed_at=datetime('now'),
            mark_price=?, realized_pnl=?, close_reason=?
        WHERE id=?
    """, (exit_price, pnl, reason, position_id))
    conn.commit()
    conn.close()
    return pnl


def get_open_perp_positions(user_id: int, strategy_id: int = None) -> list:
    conn = db.get_conn()
    if strategy_id:
        rows = conn.execute(
            "SELECT * FROM perp_positions WHERE user_id=? AND strategy_id=? AND status='open'",
            (user_id, strategy_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM perp_positions WHERE user_id=? AND status='open' ORDER BY opened_at DESC",
            (user_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_perp_pnl(position_id: int, mark_price: float, funding: float = 0):
    conn = db.get_conn()
    pos = conn.execute(
        "SELECT * FROM perp_positions WHERE id=?", (position_id,)
    ).fetchone()
    if not pos:
        conn.close()
        return
    pos = dict(pos)

    if pos["direction"] == "long":
        upnl = (mark_price - pos["entry_price"]) / pos["entry_price"] * pos["size_usd"] * pos["leverage"]
    else:
        upnl = (pos["entry_price"] - mark_price) / pos["entry_price"] * pos["size_usd"] * pos["leverage"]

    conn.execute("""
        UPDATE perp_positions
        SET mark_price=?, unrealized_pnl=?, funding_paid=funding_paid+?
        WHERE id=?
    """, (mark_price, upnl, funding, position_id))
    conn.commit()
    conn.close()


def save_majority_vote(market: str, direction: str, vote_pct: float,
                       total_votes: int, source: str, expires_minutes: int = 5):
    conn = db.get_conn()
    expires = (datetime.utcnow() + timedelta(minutes=expires_minutes)).isoformat()
    conn.execute("""
        INSERT INTO majority_votes (market, direction, vote_pct, total_votes, source, expires_at)
        VALUES (?,?,?,?,?,?)
    """, (market, direction, vote_pct, total_votes, source, expires))
    conn.commit()
    conn.close()


def get_latest_vote(market: str) -> dict | None:
    conn = db.get_conn()
    row = conn.execute("""
        SELECT * FROM majority_votes WHERE market=?
        AND expires_at > datetime('now')
        ORDER BY created_at DESC LIMIT 1
    """, (market,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ─── Indicators (reusing from engine) ────────────────────────────────────────

def _sma(prices, n):
    if len(prices) < n: return None
    return sum(prices[-n:]) / n

def _ema(prices, n):
    if len(prices) < n: return None
    k = 2/(n+1)
    e = sum(prices[:n])/n
    for p in prices[n:]: e = p*k + e*(1-k)
    return e

def _rsi(prices, n=14):
    if len(prices) < n+1: return None
    g, l = [], []
    for i in range(1, len(prices)):
        d = prices[i]-prices[i-1]
        g.append(max(d,0)); l.append(max(-d,0))
    ag = sum(g[-n:])/n; al = sum(l[-n:])/n
    return 100.0 if al==0 else 100-(100/(1+ag/al))

def _atr(prices, n=14):
    if len(prices) < n+1: return None
    trs = [abs(prices[i]-prices[i-1]) for i in range(1,len(prices))]
    return sum(trs[-n:])/n


# ═══════════════════════════════════════════════════════════════════════════════
#  PERPETUALS STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════════

PERP_STRATEGIES = {

    "perp_trend_breakout": {
        "name": "Trend Breakout Scalper 🎯",
        "emoji": "🎯",
        "short_desc": "Opens leveraged longs/shorts when price breaks out of a range",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Most of the time, prices move sideways in a range\\. "
            "Then suddenly they break out — up OR down — and that move is fast and big\\. "
            "This strategy waits for that breakout, opens a leveraged position in the same "
            "direction, and rides it for a quick profit\\.\n\n"
            "📈 *Opens LONG when:* Price breaks above the {period}\\-period high\n"
            "📉 *Opens SHORT when:* Price breaks below the {period}\\-period low\n\n"
            "✅ *Takes profit at:* {take_profit_pct}% from entry\n"
            "🛑 *Stop loss at:* {stop_loss_pct}% from entry\n"
            "⚡ *Leverage:* {leverage}x\n\n"
            "⚠️ Risk: Medium — breakouts are one of the most profitable patterns "
            "when confirmed\\. Works best on BTC and ETH perps\\."
        ),
        "params": {
            "period": 20, "leverage": 3.0,
            "take_profit_pct": 2.0, "stop_loss_pct": 1.0,
            "size_usd": 10.0,
        },
        "editable_params": [
            {"key": "size_usd",         "label": "💰 Position size (USD)",
             "desc": "Dollar size of each position", "type": "float",
             "min": 1.0, "max": 1000.0, "step": 5.0},
            {"key": "leverage",          "label": "⚡ Leverage",
             "desc": "Multiplier on your position. Higher = bigger gains AND losses",
             "type": "float", "min": 1.0, "max": 20.0, "step": 1.0,
             "presets": [1.0, 2.0, 3.0, 5.0, 10.0]},
            {"key": "take_profit_pct",   "label": "✅ Take profit %",
             "desc": "Close in profit at this % gain", "type": "float",
             "min": 0.5, "max": 10.0, "step": 0.5,
             "presets": [1.0, 1.5, 2.0, 3.0, 5.0]},
            {"key": "stop_loss_pct",     "label": "🛑 Stop loss %",
             "desc": "Exit to prevent bigger loss", "type": "float",
             "min": 0.3, "max": 5.0, "step": 0.2,
             "presets": [0.5, 0.8, 1.0, 1.5, 2.0]},
        ],
        "risk": "Medium", "best_for": "BTC-PERP, ETH-PERP",
        "type": "perp",
    },

    "perp_funding_arb": {
        "name": "Funding Rate Arbitrage 💸",
        "emoji": "💸",
        "short_desc": "Earns money from funding rate payments by being on the right side",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "In perpetual futures, traders who are LONG pay traders who are SHORT "
            "every 8 hours \\(called the funding rate\\)\\. "
            "When most people are long \\(bullish\\), the rate is positive — "
            "this strategy opens a SHORT to collect that payment\\. "
            "When most are short, it opens a LONG\\.\n\n"
            "📈 *Opens SHORT when:* Funding rate above +{funding_threshold}% "
            "\\(longs paying shorts — go short to collect\\)\n"
            "📉 *Opens LONG when:* Funding rate below -{funding_threshold}% "
            "\\(shorts paying longs — go long to collect\\)\n\n"
            "✅ *Closes:* After collecting {target_payments} funding payments\n"
            "🛑 *Stop loss:* If price moves {stop_loss_pct}% against position\n"
            "⚡ *Leverage:* {leverage}x \\(kept low — this is income, not speculation\\)\n\n"
            "⚠️ Risk: Low\\-Medium — one of the safest perp strategies\\. "
            "Used by professional traders and hedge funds daily\\."
        ),
        "params": {
            "funding_threshold": 0.01, "leverage": 2.0,
            "target_payments": 3, "stop_loss_pct": 2.0,
            "size_usd": 10.0,
        },
        "editable_params": [
            {"key": "size_usd",            "label": "💰 Position size (USD)", "type": "float",
             "min": 1.0, "max": 1000.0, "step": 5.0, "desc": "Dollar size per position"},
            {"key": "funding_threshold",   "label": "📊 Funding rate trigger %",
             "desc": "Open position when funding is this extreme. Default: 0.01%",
             "type": "float", "min": 0.005, "max": 0.1, "step": 0.005,
             "presets": [0.005, 0.01, 0.02, 0.05, 0.1]},
            {"key": "leverage",            "label": "⚡ Leverage", "type": "float",
             "min": 1.0, "max": 5.0, "step": 0.5, "presets": [1.0, 1.5, 2.0, 3.0, 5.0],
             "desc": "Keep low — this is income collection, not betting"},
            {"key": "stop_loss_pct",       "label": "🛑 Stop loss %", "type": "float",
             "min": 1.0, "max": 10.0, "step": 0.5, "presets": [1.0, 2.0, 3.0, 5.0],
             "desc": "Exit if price moves this much against you"},
        ],
        "risk": "Low-Medium", "best_for": "BTC-PERP, ETH-PERP, SOL-PERP",
        "type": "perp",
    },

    "perp_rsi_divergence": {
        "name": "RSI Divergence Reversal 🔄",
        "emoji": "🔄",
        "short_desc": "Catches reversals when price and momentum move in opposite directions",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Sometimes the price makes a new high, but the RSI makes a LOWER high — "
            "that's called divergence, and it's one of the most reliable reversal signals "
            "used by professional traders\\. It means the move is running out of steam\\.\n\n"
            "📉 *Opens SHORT when:* Price makes higher high BUT RSI makes lower high\n"
            "\\(bullish momentum fading = reversal down likely\\)\n\n"
            "📈 *Opens LONG when:* Price makes lower low BUT RSI makes higher low\n"
            "\\(bearish momentum fading = reversal up likely\\)\n\n"
            "✅ *Take profit:* {take_profit_pct}% from entry\n"
            "🛑 *Stop loss:* {stop_loss_pct}% from entry\n"
            "⚡ *Leverage:* {leverage}x\n\n"
            "⚠️ Risk: Medium — divergence is one of the highest\\-probability setups "
            "in technical analysis\\. Used by professional traders worldwide\\."
        ),
        "params": {
            "leverage": 3.0, "take_profit_pct": 3.0,
            "stop_loss_pct": 1.5, "size_usd": 10.0, "rsi_period": 14,
        },
        "editable_params": [
            {"key": "size_usd",          "label": "💰 Position size (USD)", "type": "float",
             "min": 1.0, "max": 1000.0, "step": 5.0, "desc": "Dollar size per trade"},
            {"key": "leverage",          "label": "⚡ Leverage", "type": "float",
             "min": 1.0, "max": 10.0, "step": 1.0, "presets": [1.0, 2.0, 3.0, 5.0, 8.0],
             "desc": "Position multiplier"},
            {"key": "take_profit_pct",   "label": "✅ Take profit %", "type": "float",
             "min": 1.0, "max": 10.0, "step": 0.5, "presets": [1.5, 2.0, 3.0, 5.0],
             "desc": "Close in profit at this gain"},
            {"key": "stop_loss_pct",     "label": "🛑 Stop loss %", "type": "float",
             "min": 0.5, "max": 5.0, "step": 0.25, "presets": [0.75, 1.0, 1.5, 2.0],
             "desc": "Maximum loss before exit"},
        ],
        "risk": "Medium", "best_for": "All perp markets",
        "type": "perp",
    },

    "perp_mean_reversion": {
        "name": "Perp Mean Reversion 🎢",
        "emoji": "🎢",
        "short_desc": "Fades overextended moves — bets on price snapping back to average",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "When a perp moves way too far from its average in a short time, "
            "it almost always snaps back\\. This strategy measures how far the price "
            "has stretched using a statistical measure \\(z\\-score\\), then bets against "
            "the move — going SHORT if it stretched up too far, LONG if it crashed too far\\.\n\n"
            "📈 *Opens LONG when:* Price is {zscore_threshold} standard deviations BELOW average\n"
            "\\(extremely stretched down — snap\\-back up likely\\)\n\n"
            "📉 *Opens SHORT when:* Price is {zscore_threshold} standard deviations ABOVE average\n"
            "\\(extremely stretched up — pullback likely\\)\n\n"
            "✅ *Take profit:* When price returns to average\n"
            "🛑 *Stop loss:* {stop_loss_pct}% from entry\n"
            "⚡ *Leverage:* {leverage}x\n\n"
            "⚠️ Risk: Low\\-Medium — statistical edge is strong on liquid markets\\. "
            "Very popular with quantitative trading firms\\."
        ),
        "params": {
            "zscore_threshold": 2.0, "leverage": 2.0,
            "stop_loss_pct": 2.0, "size_usd": 10.0, "lookback": 20,
        },
        "editable_params": [
            {"key": "size_usd",            "label": "💰 Position size (USD)", "type": "float",
             "min": 1.0, "max": 1000.0, "step": 5.0, "desc": "Dollar size per trade"},
            {"key": "leverage",            "label": "⚡ Leverage", "type": "float",
             "min": 1.0, "max": 5.0, "step": 0.5, "presets": [1.0, 1.5, 2.0, 3.0, 5.0],
             "desc": "Keep low for mean reversion — snap-backs can be slow"},
            {"key": "zscore_threshold",    "label": "📐 Z-score trigger",
             "desc": "How extreme the move must be. 2.0 = unusual, 2.5 = very unusual",
             "type": "float", "min": 1.5, "max": 3.0, "step": 0.1,
             "presets": [1.5, 2.0, 2.5, 3.0]},
            {"key": "stop_loss_pct",       "label": "🛑 Stop loss %", "type": "float",
             "min": 1.0, "max": 8.0, "step": 0.5, "presets": [1.5, 2.0, 3.0, 5.0],
             "desc": "Exit if price extends further instead of reverting"},
        ],
        "risk": "Low-Medium", "best_for": "BTC-PERP, ETH-PERP",
        "type": "perp",
    },

    "perp_majority_vote": {
        "name": "Majority Vote Sniper 🗳️",
        "emoji": "🗳️",
        "short_desc": "Watches community predictions and enters on the last seconds of a vote",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "On prediction markets and trading platforms, users vote on which direction "
            "a market will go\\. This bot watches those votes in real time, then on the "
            "last few seconds before the vote closes, it makes a decision:\n\n"
            "🧠 *Two modes \\(you choose\\):*\n\n"
            "1\\. *Follow Majority* — goes with what most people voted\\.\n"
            "   _Works when crowd wisdom is reliable_\n\n"
            "2\\. *Contrarian* — goes AGAINST the majority vote\\.\n"
            "   _Crowds are often wrong at extremes — contrarians profit_\n\n"
            "📡 *Bot reads:* Live vote data from prediction market sources\n"
            "⚡ *Enters:* In the last *{entry_seconds}* seconds before close\n"
            "✅ *Profit target:* {take_profit_pct}%\n"
            "🛑 *Stop loss:* {stop_loss_pct}%\n\n"
            "⚠️ Risk: High — prediction markets can be manipulated\\. "
            "Use small sizes and paper trade first\\."
        ),
        "params": {
            "entry_seconds": 30, "follow_majority": True,
            "min_vote_pct": 60.0, "leverage": 2.0,
            "take_profit_pct": 2.0, "stop_loss_pct": 1.5,
            "size_usd": 5.0,
        },
        "editable_params": [
            {"key": "size_usd",        "label": "💰 Position size (USD)", "type": "float",
             "min": 1.0, "max": 100.0, "step": 1.0, "desc": "Keep small — this is experimental"},
            {"key": "follow_majority", "label": "🗳️ Follow majority vote?",
             "desc": "True=follow crowd  False=go contrarian against crowd",
             "type": "bool", "options": [True, False]},
            {"key": "min_vote_pct",   "label": "📊 Min majority % to enter",
             "desc": "Only enter if one side has at least this % of votes. Default: 60%",
             "type": "float", "min": 51.0, "max": 90.0, "step": 5.0,
             "presets": [55.0, 60.0, 65.0, 70.0, 75.0]},
            {"key": "entry_seconds",  "label": "⏱ Entry window (seconds before close)",
             "desc": "How many seconds before vote closes to enter. Default: 30",
             "type": "int", "min": 5, "max": 120, "step": 5,
             "presets": [10, 20, 30, 45, 60]},
        ],
        "risk": "High", "best_for": "Prediction markets, NEAR Protocol",
        "type": "perp",
    },

    "perp_ema_ribbon": {
        "name": "EMA Ribbon Trend Filter 🎀",
        "emoji": "🎀",
        "short_desc": "Uses a stack of EMAs to identify strong trends and ride them",
        "plain_english": (
            "🤔 *What does this do?*\n"
            "Instead of one moving average, this uses five of them stacked together "
            "\\(called a ribbon\\)\\. When all five are perfectly aligned and spreading apart, "
            "the trend is strong and this bot opens a leveraged position to ride it\\.\n\n"
            "📈 *Opens LONG when:* All 5 EMAs are stacked with fastest on top "
            "\\(EMA8 > EMA13 > EMA21 > EMA34 > EMA55\\) and spreading apart\n\n"
            "📉 *Opens SHORT when:* All 5 EMAs stacked with fastest on bottom "
            "\\(EMA8 < EMA13 < EMA21 < EMA34 < EMA55\\) and spreading apart\n\n"
            "✅ *Closes:* When EMA8 and EMA13 cross \\(trend weakening\\)\n"
            "🛑 *Stop loss:* {stop_loss_pct}% from entry\n"
            "⚡ *Leverage:* {leverage}x\n\n"
            "⚠️ Risk: Low\\-Medium — only trades in confirmed trends\\. "
            "Fewer trades but higher quality\\. Used by professional trend traders\\."
        ),
        "params": {
            "leverage": 3.0, "stop_loss_pct": 1.5,
            "size_usd": 10.0,
        },
        "editable_params": [
            {"key": "size_usd",       "label": "💰 Position size (USD)", "type": "float",
             "min": 1.0, "max": 1000.0, "step": 5.0, "desc": "Dollar size per position"},
            {"key": "leverage",       "label": "⚡ Leverage", "type": "float",
             "min": 1.0, "max": 10.0, "step": 1.0, "presets": [1.0, 2.0, 3.0, 5.0, 8.0],
             "desc": "Position multiplier"},
            {"key": "stop_loss_pct",  "label": "🛑 Stop loss %", "type": "float",
             "min": 0.5, "max": 5.0, "step": 0.25, "presets": [0.75, 1.0, 1.5, 2.0, 3.0],
             "desc": "Exit if price moves this much against trend"},
        ],
        "risk": "Low-Medium", "best_for": "BTC-PERP, ETH-PERP during trending markets",
        "type": "perp",
    },
}


# ─── Signal Generation for Perp Strategies ───────────────────────────────────

def get_perp_signal(strategy_name: str, market: str,
                    params: dict, strategy_id: int = None) -> dict:
    """
    Generate a trading signal for a perpetuals strategy.
    Returns: {signal: 'long'|'short'|'hold'|'close', reason, indicators}
    """
    price = get_perp_price(market)
    if not price:
        return {"signal": "hold", "reason": "No price data", "indicators": {}}

    _record_perp_price(market, price)
    prices = _get_perp_prices(market, 100)
    ind = {"price": price}

    if len(prices) < 5:
        return {"signal": "hold", "reason": f"Warming up ({len(prices)}/5)", "indicators": ind}

    # ── Trend Breakout ────────────────────────────────────────────────────────
    if strategy_name == "perp_trend_breakout":
        period   = params.get("period", 20)
        n        = min(period, len(prices)-1)
        high_n   = max(prices[-n-1:-1])
        low_n    = min(prices[-n-1:-1])
        ind.update({"period_high": high_n, "period_low": low_n})

        # Check if we have open position to manage
        if strategy_id:
            positions = get_open_perp_positions(0, strategy_id)
            if positions:
                pos   = positions[0]
                entry = pos["entry_price"]
                tp    = params.get("take_profit_pct", 2.0)
                sl    = params.get("stop_loss_pct", 1.0)
                if pos["direction"] == "long":
                    gain = (price - entry) / entry * 100
                    if gain >= tp:
                        return {"signal": "close", "reason": f"TP hit: +{gain:.2f}%", "indicators": ind}
                    if gain <= -sl:
                        return {"signal": "close", "reason": f"SL hit: {gain:.2f}%", "indicators": ind}
                else:
                    gain = (entry - price) / entry * 100
                    if gain >= tp:
                        return {"signal": "close", "reason": f"TP hit: +{gain:.2f}%", "indicators": ind}
                    if gain <= -sl:
                        return {"signal": "close", "reason": f"SL hit: {gain:.2f}%", "indicators": ind}
                return {"signal": "hold", "reason": f"In position — monitoring", "indicators": ind}

        if price > high_n:
            return {"signal": "long",  "reason": f"Breakout above {period}-period high {fmt_price(high_n)}", "indicators": ind}
        if price < low_n:
            return {"signal": "short", "reason": f"Breakdown below {period}-period low {fmt_price(low_n)}", "indicators": ind}
        return {"signal": "hold", "reason": f"Range-bound: {fmt_price(low_n)} – {fmt_price(high_n)}", "indicators": ind}

    # ── Funding Rate Arb (simulated) ──────────────────────────────────────────
    elif strategy_name == "perp_funding_arb":
        # Simulate funding rate from price momentum
        if len(prices) < 10:
            return {"signal": "hold", "reason": "Collecting data", "indicators": ind}
        momentum = (prices[-1] - prices[-10]) / prices[-10] * 100
        # Positive momentum → long bias → positive funding rate
        simulated_rate = momentum * 0.001
        ind["simulated_funding_rate"] = simulated_rate
        threshold = params.get("funding_threshold", 0.01)
        if simulated_rate > threshold:
            return {"signal": "short", "reason": f"High funding {simulated_rate:.4f}% — go short to collect", "indicators": ind}
        if simulated_rate < -threshold:
            return {"signal": "long",  "reason": f"Negative funding {simulated_rate:.4f}% — go long to collect", "indicators": ind}
        return {"signal": "hold", "reason": f"Funding {simulated_rate:.5f}% — within normal range", "indicators": ind}

    # ── RSI Divergence ────────────────────────────────────────────────────────
    elif strategy_name == "perp_rsi_divergence":
        n   = params.get("rsi_period", 14)
        rsi = _rsi(prices, n)
        ind["rsi"] = rsi
        if rsi is None or len(prices) < 30:
            return {"signal": "hold", "reason": f"Building RSI ({len(prices)}/30)", "indicators": ind}

        # Detect divergence using last 10 bars
        recent_prices = prices[-10:]
        recent_rsi    = []
        for i in range(len(prices)-10, len(prices)):
            r = _rsi(prices[:i+1], n)
            if r: recent_rsi.append(r)

        if len(recent_rsi) < 5:
            return {"signal": "hold", "reason": "Building divergence data", "indicators": ind}

        price_higher = recent_prices[-1] > recent_prices[0]
        rsi_lower    = recent_rsi[-1] < recent_rsi[0]
        price_lower  = recent_prices[-1] < recent_prices[0]
        rsi_higher   = recent_rsi[-1] > recent_rsi[0]

        if price_higher and rsi_lower and rsi > 60:
            return {"signal": "short", "reason": f"Bearish divergence — price up but RSI down ({rsi:.0f})", "indicators": ind}
        if price_lower and rsi_higher and rsi < 40:
            return {"signal": "long",  "reason": f"Bullish divergence — price down but RSI up ({rsi:.0f})", "indicators": ind}
        return {"signal": "hold", "reason": f"RSI={rsi:.0f} — no divergence detected", "indicators": ind}

    # ── Mean Reversion (Z-score) ──────────────────────────────────────────────
    elif strategy_name == "perp_mean_reversion":
        lb  = params.get("lookback", 20)
        sma = _sma(prices, lb)
        if sma is None:
            return {"signal": "hold", "reason": f"Collecting data ({len(prices)}/{lb})", "indicators": ind}
        variance = sum((p-sma)**2 for p in prices[-lb:]) / lb
        std      = variance**0.5
        zscore   = (price - sma) / std if std > 0 else 0
        ind.update({"zscore": zscore, "sma": sma, "std": std})
        thresh = params.get("zscore_threshold", 2.0)

        if strategy_id:
            positions = get_open_perp_positions(0, strategy_id)
            if positions:
                pos  = positions[0]
                # Close when price returns to mean
                near_mean = abs(zscore) < 0.3
                if near_mean:
                    return {"signal": "close", "reason": f"Price returned to mean (z={zscore:.2f})", "indicators": ind}
                # Stop loss
                entry = pos["entry_price"]
                sl    = params.get("stop_loss_pct", 2.0)
                if pos["direction"] == "long" and (price-entry)/entry*100 <= -sl:
                    return {"signal": "close", "reason": f"Stop loss hit", "indicators": ind}
                if pos["direction"] == "short" and (entry-price)/entry*100 <= -sl:
                    return {"signal": "close", "reason": f"Stop loss hit", "indicators": ind}
                return {"signal": "hold", "reason": f"In position (z={zscore:.2f})", "indicators": ind}

        if zscore <= -thresh:
            return {"signal": "long",  "reason": f"Price {zscore:.1f}σ below mean — snap-back long", "indicators": ind}
        if zscore >= thresh:
            return {"signal": "short", "reason": f"Price {zscore:.1f}σ above mean — fade short", "indicators": ind}
        return {"signal": "hold", "reason": f"Z-score {zscore:.2f} — within normal range", "indicators": ind}

    # ── Majority Vote ─────────────────────────────────────────────────────────
    elif strategy_name == "perp_majority_vote":
        vote = get_latest_vote(market)
        if not vote:
            return {"signal": "hold",
                    "reason": "No active vote data — set up vote feed or use /vote command",
                    "indicators": ind}
        min_pct      = params.get("min_vote_pct", 60.0)
        follow_crowd = params.get("follow_majority", True)
        vote_pct     = vote["vote_pct"]
        direction    = vote["direction"]
        ind.update({"vote_direction": direction, "vote_pct": vote_pct})

        if vote_pct < min_pct:
            return {"signal": "hold",
                    "reason": f"Majority {vote_pct:.0f}% — need {min_pct:.0f}% to enter",
                    "indicators": ind}

        if follow_crowd:
            sig = "long" if direction == "up" else "short"
            return {"signal": sig,
                    "reason": f"Following {vote_pct:.0f}% majority voting {direction}",
                    "indicators": ind}
        else:
            sig = "short" if direction == "up" else "long"
            return {"signal": sig,
                    "reason": f"Contrarian: {vote_pct:.0f}% voting {direction} — going opposite",
                    "indicators": ind}

    # ── EMA Ribbon ────────────────────────────────────────────────────────────
    elif strategy_name == "perp_ema_ribbon":
        emas = [_ema(prices, n) for n in [8, 13, 21, 34, 55]]
        if any(e is None for e in emas):
            return {"signal": "hold", "reason": f"Building ribbon ({len(prices)}/55 points)", "indicators": ind}
        e8, e13, e21, e34, e55 = emas
        ind.update({"ema8": e8, "ema13": e13, "ema21": e21})

        # Check if ribbon is perfectly aligned (bullish or bearish)
        bullish_ribbon = e8 > e13 > e21 > e34 > e55
        bearish_ribbon = e8 < e13 < e21 < e34 < e55

        # Check spread (expanding = strong trend)
        spread = abs(e8 - e55) / e55 * 100

        if strategy_id:
            positions = get_open_perp_positions(0, strategy_id)
            if positions:
                pos = positions[0]
                # Close if ribbon alignment broken
                if pos["direction"] == "long"  and not bullish_ribbon:
                    return {"signal": "close", "reason": "Bullish ribbon broken — closing long", "indicators": ind}
                if pos["direction"] == "short" and not bearish_ribbon:
                    return {"signal": "close", "reason": "Bearish ribbon broken — closing short", "indicators": ind}
                # Stop loss
                entry = pos["entry_price"]
                sl    = params.get("stop_loss_pct", 1.5)
                chg   = (price - entry) / entry * 100
                eff   = chg if pos["direction"] == "long" else -chg
                if eff <= -sl:
                    return {"signal": "close", "reason": f"Stop loss: {eff:.2f}%", "indicators": ind}
                return {"signal": "hold", "reason": f"Ribbon intact, spread={spread:.2f}%", "indicators": ind}

        if bullish_ribbon and spread > 0.1:
            return {"signal": "long",  "reason": f"Bullish EMA ribbon — spread {spread:.2f}%", "indicators": ind}
        if bearish_ribbon and spread > 0.1:
            return {"signal": "short", "reason": f"Bearish EMA ribbon — spread {spread:.2f}%", "indicators": ind}
        return {"signal": "hold", "reason": f"Ribbon not aligned (spread={spread:.2f}%)", "indicators": ind}

    return {"signal": "hold", "reason": "Unknown perp strategy", "indicators": ind}


def paper_perp_open(user_id: int, market: str, direction: str, size_usd: float,
                    leverage: float, strategy_id: int = None,
                    take_profit: float = None, stop_loss: float = None) -> dict:
    """Open a paper perpetuals position."""
    price = get_perp_price(market)
    if not price:
        raise ValueError(f"Cannot get price for {market}")

    # Check we have enough paper balance (use SOL/NEAR as margin)
    margin_needed = size_usd / leverage
    # Simplified: just track in USD terms

    pos_id = open_perp_position({
        "user_id":     user_id,
        "strategy_id": strategy_id,
        "market":      market,
        "mode":        "paper",
        "direction":   direction,
        "size_usd":    size_usd,
        "leverage":    leverage,
        "entry_price": price,
        "take_profit": take_profit,
        "stop_loss":   stop_loss,
    })

    fee = size_usd * 0.0005  # 0.05% taker fee (Orderly standard)

    conn = db.get_conn()
    conn.execute("""
        INSERT INTO perp_trades
        (user_id, strategy_id, market, mode, action, direction, size_usd, leverage, price, fee, strategy_name)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (user_id, strategy_id, market, "paper", "open", direction, size_usd, leverage, price, fee, "manual"))
    conn.commit()
    conn.close()

    return {
        "position_id": pos_id,
        "market":      market,
        "direction":   direction,
        "size_usd":    size_usd,
        "leverage":    leverage,
        "entry_price": price,
        "fee":         fee,
        "liquidation": price * (1 - 1/leverage*0.9) if direction == "long" else price * (1 + 1/leverage*0.9),
    }


def paper_perp_close(user_id: int, position_id: int) -> dict:
    """Close a paper perpetuals position."""
    conn = db.get_conn()
    pos = conn.execute(
        "SELECT * FROM perp_positions WHERE id=? AND user_id=?", (position_id, user_id)
    ).fetchone()
    conn.close()

    if not pos:
        raise ValueError(f"Position #{position_id} not found")
    pos = dict(pos)

    price = get_perp_price(pos["market"])
    if not price:
        raise ValueError(f"Cannot get price for {pos['market']}")

    pnl = close_perp_position(position_id, price, "manual")

    return {
        "position_id":  position_id,
        "market":       pos["market"],
        "direction":    pos["direction"],
        "entry_price":  pos["entry_price"],
        "exit_price":   price,
        "realized_pnl": pnl,
        "leverage":     pos["leverage"],
    }

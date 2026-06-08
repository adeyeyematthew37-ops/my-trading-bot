# strategies/learning.py
# The bot's brain — tracks every trade outcome, learns what works,
# and automatically adjusts strategy parameters over time.

import json
import math
from datetime import datetime, timedelta
from utils import database as db

# ── How learning works ────────────────────────────────────────────────────────
#
# Every time a strategy makes a trade, we record:
#   - entry price, exit price, profit/loss
#   - which signal triggered it (RSI level, MA gap size etc)
#   - market conditions at the time
#
# After enough trades we analyse:
#   - Which RSI levels actually led to profitable buys?
#   - Is the strategy making or losing money overall?
#   - Should it use more or less capital per trade?
#
# Then we nudge the params in the direction that made more money.
# ─────────────────────────────────────────────────────────────────────────────


def record_trade_outcome(strategy_id: int, trade_id: int, entry_price: float,
                          exit_price: float, amount: float, signal_data: dict):
    """
    Called after every completed trade to record what happened.
    This is the raw data the learning engine uses.
    """
    if entry_price <= 0 or exit_price <= 0:
        return

    pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    pnl_abs = (exit_price - entry_price) * amount
    won = pnl_pct > 0

    db.save_trade_outcome({
        "strategy_id":  strategy_id,
        "trade_id":     trade_id,
        "entry_price":  entry_price,
        "exit_price":   exit_price,
        "amount":       amount,
        "pnl_pct":      pnl_pct,
        "pnl_abs":      pnl_abs,
        "won":          1 if won else 0,
        "signal_data":  json.dumps(signal_data),
    })

    # Update strategy cumulative PnL
    db.update_strategy_pnl(strategy_id, pnl_abs)

    # Trigger learning after every 5 trades
    outcomes = db.get_strategy_outcomes(strategy_id)
    if len(outcomes) >= 5 and len(outcomes) % 5 == 0:
        _learn_and_adjust(strategy_id, outcomes)


def _learn_and_adjust(strategy_id: int, outcomes: list):
    """
    Analyse recent trade history and nudge strategy params
    toward what's been working.
    """
    strategies = db.get_user_strategies_by_id(strategy_id)
    if not strategies:
        return
    strategy = strategies[0]
    params = json.loads(strategy.get("params") or "{}")
    strategy_name = strategy["name"]

    recent = outcomes[-20:]  # Use last 20 trades
    wins = [o for o in recent if o["won"]]
    losses = [o for o in recent if not o["won"]]
    win_rate = len(wins) / len(recent) if recent else 0
    avg_win_pct = sum(o["pnl_pct"] for o in wins) / len(wins) if wins else 0
    avg_loss_pct = sum(o["pnl_pct"] for o in losses) / len(losses) if losses else 0

    adjustments = []
    new_params = dict(params)

    # ── RSI strategy learning ─────────────────────────────────────────────────
    if strategy_name == "rsi_oversold":
        # If we're losing more than 60% of trades, tighten the RSI thresholds
        if win_rate < 0.40:
            old_buy = new_params.get("rsi_buy", 30)
            old_sell = new_params.get("rsi_sell", 70)
            # Tighten: require more oversold to buy, more overbought to sell
            new_buy = max(20, old_buy - 3)
            new_sell = min(80, old_sell + 3)
            if new_buy != old_buy or new_sell != old_sell:
                new_params["rsi_buy"] = new_buy
                new_params["rsi_sell"] = new_sell
                adjustments.append(
                    f"Win rate low ({win_rate*100:.0f}%) → tightened RSI thresholds: "
                    f"buy<{new_buy} sell>{new_sell}"
                )
        # If winning well, slightly relax to catch more opportunities
        elif win_rate > 0.65:
            old_buy = new_params.get("rsi_buy", 30)
            old_sell = new_params.get("rsi_sell", 70)
            new_buy = min(35, old_buy + 2)
            new_sell = max(65, old_sell - 2)
            if new_buy != old_buy or new_sell != old_sell:
                new_params["rsi_buy"] = new_buy
                new_params["rsi_sell"] = new_sell
                adjustments.append(
                    f"Win rate good ({win_rate*100:.0f}%) → relaxed RSI slightly: "
                    f"buy<{new_buy} sell>{new_sell}"
                )

    # ── MA Crossover learning ─────────────────────────────────────────────────
    elif strategy_name == "ma_crossover":
        if win_rate < 0.40:
            # Increase the slow MA period to filter out noise
            old_slow = new_params.get("slow_ma", 21)
            new_slow = min(50, old_slow + 5)
            new_params["slow_ma"] = new_slow
            adjustments.append(
                f"Too many false crossovers → increased slow MA from {old_slow} to {new_slow}"
            )

    # ── Momentum learning ─────────────────────────────────────────────────────
    elif strategy_name == "momentum":
        if win_rate < 0.40:
            # Require bigger moves before entering
            old_buy = new_params.get("buy_threshold", 2.0)
            new_buy = min(5.0, old_buy + 0.5)
            new_params["buy_threshold"] = new_buy
            adjustments.append(
                f"Too many bad entries → raised momentum threshold to {new_buy}%"
            )

    # ── Universal: position size adjustment ──────────────────────────────────
    # If we're on a losing streak (last 5 all losses), reduce size
    last_5 = recent[-5:] if len(recent) >= 5 else recent
    if all(not o["won"] for o in last_5) and len(last_5) == 5:
        old_amt = new_params.get("trade_amount", 0.01)
        new_amt = round(old_amt * 0.75, 6)  # Reduce by 25%
        new_amt = max(0.001, new_amt)        # Never go below 0.001
        new_params["trade_amount"] = new_amt
        adjustments.append(
            f"5 losses in a row → reduced trade size from {old_amt} to {new_amt}"
        )

    # If we're on a winning streak (last 5 all wins), increase size slightly
    elif all(o["won"] for o in last_5) and len(last_5) == 5:
        old_amt = new_params.get("trade_amount", 0.01)
        new_amt = round(old_amt * 1.15, 6)  # Increase by 15%
        new_params["trade_amount"] = new_amt
        adjustments.append(
            f"5 wins in a row → increased trade size from {old_amt} to {new_amt}"
        )

    # Save updated params if anything changed
    if adjustments:
        db.update_strategy_params(strategy_id, new_params)
        db.save_learning_log({
            "strategy_id": strategy_id,
            "win_rate":    win_rate,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
            "adjustments": json.dumps(adjustments),
            "params_before": strategy.get("params", "{}"),
            "params_after":  json.dumps(new_params),
        })
        return adjustments

    return []


def get_strategy_stats(strategy_id: int) -> dict:
    """Full performance stats for a strategy."""
    outcomes = db.get_strategy_outcomes(strategy_id)
    if not outcomes:
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "total_pnl": 0,
            "avg_win": 0, "avg_loss": 0,
            "best_trade": 0, "worst_trade": 0,
            "profit_factor": 0, "expectancy": 0,
        }

    wins   = [o for o in outcomes if o["won"]]
    losses = [o for o in outcomes if not o["won"]]
    total_pnl  = sum(o["pnl_abs"] for o in outcomes)
    win_rate   = len(wins) / len(outcomes) if outcomes else 0
    avg_win    = sum(o["pnl_pct"] for o in wins)   / len(wins)   if wins   else 0
    avg_loss   = sum(o["pnl_pct"] for o in losses) / len(losses) if losses else 0
    gross_win  = sum(o["pnl_abs"] for o in wins)   if wins   else 0
    gross_loss = abs(sum(o["pnl_abs"] for o in losses)) if losses else 0
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    expectancy    = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    return {
        "total_trades":  len(outcomes),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      win_rate,
        "total_pnl":     total_pnl,
        "avg_win":       avg_win,
        "avg_loss":      avg_loss,
        "best_trade":    max((o["pnl_pct"] for o in outcomes), default=0),
        "worst_trade":   min((o["pnl_pct"] for o in outcomes), default=0),
        "profit_factor": profit_factor,
        "expectancy":    expectancy,
    }


def get_learning_log(strategy_id: int) -> list:
    """Get history of all parameter adjustments the bot made."""
    return db.get_learning_logs(strategy_id)


def get_weekly_report(user_id: int) -> str:
    """
    Build a full weekly performance report for a user.
    Covers all strategies, DCA orders, and paper trades from the last 7 days.
    """
    from utils.prices import fmt_price
    from config.chains import CHAINS
    from strategies.engine import STRATEGIES

    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()

    all_trades   = db.get_trades_since(user_id, week_ago)
    strategies   = db.get_user_strategies(user_id)
    dca_orders   = db.get_user_dca(user_id)

    paper_trades = [t for t in all_trades if t["mode"] == "paper"]
    live_trades  = [t for t in all_trades if t["mode"] == "live"]

    total_paper_pnl = sum(t.get("pnl_abs", 0) or 0 for t in paper_trades)
    total_live_pnl  = sum(t.get("pnl_abs", 0) or 0 for t in live_trades)

    paper_wins  = sum(1 for t in paper_trades if (t.get("pnl_abs") or 0) > 0)
    paper_loss  = sum(1 for t in paper_trades if (t.get("pnl_abs") or 0) < 0)
    live_wins   = sum(1 for t in live_trades  if (t.get("pnl_abs") or 0) > 0)
    live_loss   = sum(1 for t in live_trades  if (t.get("pnl_abs") or 0) < 0)

    now_str = datetime.utcnow().strftime("%d %b %Y")
    week_str = (datetime.utcnow() - timedelta(days=7)).strftime("%d %b")

    lines = [
        f"📊 *Weekly Trading Report*",
        f"_{week_str} → {now_str}_",
        f"{'━'*28}",
        f"",
    ]

    # ── Paper trading summary ─────────────────────────────────────────────────
    lines += [
        f"📝 *Paper Trading*",
        f"  Trades: {len(paper_trades)} "
        f"({'✅' if total_paper_pnl >= 0 else '❌'} "
        f"{paper_wins}W / {paper_loss}L)",
        f"  Net P&L: {'+'if total_paper_pnl>=0 else ''}{total_paper_pnl:.4f}",
        f"",
    ]

    # ── Live trading summary ──────────────────────────────────────────────────
    if live_trades:
        lines += [
            f"💎 *Live Trading*",
            f"  Trades: {len(live_trades)} "
            f"({'✅' if total_live_pnl >= 0 else '❌'} "
            f"{live_wins}W / {live_loss}L)",
            f"  Net P&L: {'+'if total_live_pnl>=0 else ''}{total_live_pnl:.6f}",
            f"",
        ]

    # ── Strategy-by-strategy breakdown ───────────────────────────────────────
    active_strats = [s for s in strategies if s["status"] == "active"]
    if active_strats:
        lines.append(f"🤖 *Strategy Performance*")
        for s in active_strats:
            stats    = get_strategy_stats(s["id"])
            s_name   = STRATEGIES.get(s["name"], {}).get("name", s["name"])
            ci       = CHAINS.get(s["chain"], {})
            pnl_str  = f"+{stats['total_pnl']:.4f}" if stats["total_pnl"] >= 0 \
                       else f"{stats['total_pnl']:.4f}"
            wr_str   = f"{stats['win_rate']*100:.0f}%" if stats["total_trades"] > 0 else "N/A"

            lines += [
                f"  {ci.get('emoji','')} *{s_name}* — {s.get('token_symbol','?')}",
                f"    {stats['total_trades']} trades | WR: {wr_str} | P&L: {pnl_str}",
            ]

            # Show what the bot learned this week
            logs = get_learning_log(s["id"])
            week_logs = [
                l for l in logs
                if l.get("created_at","") >= week_ago
            ]
            if week_logs:
                lines.append(f"    🧠 _Auto-adjusted {len(week_logs)}x this week_")
        lines.append("")

    # ── DCA summary ───────────────────────────────────────────────────────────
    active_dca = [d for d in dca_orders if d["status"] == "active"]
    if active_dca:
        lines.append(f"📊 *DCA Bots Running*")
        for d in active_dca:
            ci = CHAINS.get(d["chain"], {})
            lines.append(
                f"  {ci.get('emoji','')} {d.get('symbol_in','?')}→{d.get('symbol_out','?')} "
                f"| {d['done_orders']} orders done"
            )
        lines.append("")

    # ── Top trades of the week ────────────────────────────────────────────────
    sorted_trades = sorted(
        all_trades, key=lambda t: abs(t.get("pnl_abs") or 0), reverse=True
    )[:3]

    if sorted_trades:
        lines.append(f"🏆 *Top Trades This Week*")
        for t in sorted_trades:
            pnl = t.get("pnl_abs") or 0
            emoji = "✅" if pnl >= 0 else "❌"
            ci = CHAINS.get(t["chain"], {})
            lines.append(
                f"  {emoji} {t.get('symbol_in','?')}→{t.get('symbol_out','?')} "
                f"{ci.get('emoji','')} "
                f"{'+'if pnl>=0 else ''}{pnl:.4f}"
            )
        lines.append("")

    lines += [
        f"{'━'*28}",
        f"_Next report in 7 days_",
        f"_Use /mystrats to see live stats_",
    ]

    return "\n".join(lines)

# bot/perp_handlers.py
# All perpetuals Telegram handlers — imported by bot.py at the bottom

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler, CommandHandler, ConversationHandler,
    ContextTypes, MessageHandler, filters
)

from trading.perpetuals import (
    PERP_STRATEGIES, PERP_MARKETS, get_perp_signal, get_perp_price,
    paper_perp_open, paper_perp_close, get_open_perp_positions,
    ensure_perp_tables, save_majority_vote, update_perp_pnl,
    close_perp_position, get_market_links, get_rhea_trade_url,
    get_aster_trade_url, get_aster_predict_url,
    RHEA_MARKETS, ASTER_MARKETS, ORDERLY_MARKETS
)
from utils.prices import fmt_price
from utils import database as db
from config.chains import CHAINS

# Conversation states (use high numbers to avoid conflicts)
AWAIT_PERP_MARKET = 100
AWAIT_PERP_SIZE   = 101
AWAIT_PERP_LEV    = 102
AWAIT_VOTE_MARKET = 103
AWAIT_VOTE_DIR    = 104
AWAIT_VOTE_PCT    = 105


def _perp_pnl_str(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.4f}"


async def send_perp(update: Update, text: str, kb=None, edit: bool = False):
    kwargs = {"text": text, "parse_mode": ParseMode.MARKDOWN,
              "disable_web_page_preview": True}
    if kb:
        kwargs["reply_markup"] = kb
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(**kwargs)
    elif update.callback_query:
        await update.callback_query.message.reply_text(**kwargs)
    else:
        await update.message.reply_text(**kwargs)


# ─── Main perp menu ───────────────────────────────────────────────────────────

async def perp_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Shared perp menu used by both /perp command and menu:perp callback."""
    from utils import database as db2
    if hasattr(update, 'effective_user') and update.effective_user:
        from bot_helpers import ensure_user
        user = ensure_user(update)
    else:
        user = {"id": 0}

    positions = get_open_perp_positions(user["id"])
    total_upnl = 0.0
    for pos in positions:
        price = get_perp_price(pos["market"])
        if price:
            if pos["direction"] == "long":
                upnl = (price - pos["entry_price"]) / pos["entry_price"] * pos["size_usd"] * pos["leverage"]
            else:
                upnl = (pos["entry_price"] - price) / pos["entry_price"] * pos["size_usd"] * pos["leverage"]
            total_upnl += upnl

    pnl_e = "✅" if total_upnl >= 0 else "❌"
    pnl_s = _perp_pnl_str(total_upnl)

    market_lines = ""
    for market in list(PERP_MARKETS.keys())[:5]:
        price = get_perp_price(market)
        market_lines += f"  • *{market}*: {fmt_price(price) if price else 'N/A'}\n"

    text = (
        f"📊 *Perpetuals Trading*\n\n"
        f"Leveraged long/short on BTC, ETH, SOL, NEAR & more\\.\n\n"
        f"*Open Positions:* {len(positions)}\n"
        f"{pnl_e} *Unrealized P&L:* `{pnl_s} USD`\n\n"
        f"*Markets:*\n{market_lines}\n"
        f"_Start with paper trading first\\!_"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Long",         callback_data="perp_open:long"),
         InlineKeyboardButton("📉 Short",        callback_data="perp_open:short")],
        [InlineKeyboardButton("📋 Positions",    callback_data="perp_positions"),
         InlineKeyboardButton("🤖 Strategies",   callback_data="perp_strategies")],
        [InlineKeyboardButton("🔥 Rhea Finance", callback_data="perp_rhea_menu"),
         InlineKeyboardButton("⭐ Aster",         callback_data="perp_aster_menu")],
        [InlineKeyboardButton("📊 Orderly",       callback_data="perp_orderly_menu")],
        [InlineKeyboardButton("🗳️ Vote",          callback_data="perp_vote_start"),
         InlineKeyboardButton("📜 History",      callback_data="perp_history")],
        [InlineKeyboardButton("💳 Import NEAR/HOT Wallet", callback_data="perp_import_wallet")],
        [InlineKeyboardButton("« Back", callback_data="back:main")],
    ])
    await send_perp(update, text, kb, edit=bool(update.callback_query))


async def perp_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/perp command."""
    await perp_menu(update, ctx)


# ─── Positions ────────────────────────────────────────────────────────────────

async def perp_positions_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    from bot_helpers import ensure_user
    user = ensure_user(update)
    positions = get_open_perp_positions(user["id"])

    if not positions:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Open Position", callback_data="perp_open:long")],
            [InlineKeyboardButton("« Back", callback_data="menu:perp")],
        ])
        await send_perp(update, "📋 *No open positions\\.* Open a long or short first\\!", kb, edit=True)
        return

    text = "📋 *Open Perp Positions*\n\n"
    buttons = []
    for pos in positions:
        price = get_perp_price(pos["market"]) or pos["entry_price"]
        update_perp_pnl(pos["id"], price)
        if pos["direction"] == "long":
            upnl = (price - pos["entry_price"]) / pos["entry_price"] * pos["size_usd"] * pos["leverage"]
        else:
            upnl = (pos["entry_price"] - price) / pos["entry_price"] * pos["size_usd"] * pos["leverage"]
        upnl_pct = upnl / (pos["size_usd"] or 1) * 100
        dir_e = "📈 LONG" if pos["direction"] == "long" else "📉 SHORT"
        pnl_e = "✅" if upnl >= 0 else "❌"
        mode_tag = "📝" if pos["mode"] == "paper" else "💎"
        text += (
            f"{mode_tag} *{pos['market']}* — {dir_e} \\[\\#{pos['id']}\\]\n"
            f"  ${pos['size_usd']:.0f} × {pos['leverage']:.0f}x "
            f"| Entry: {fmt_price(pos['entry_price'])} → {fmt_price(price)}\n"
            f"  {pnl_e} P&L: `{_perp_pnl_str(upnl)}` \\({upnl_pct:+.1f}%\\)\n"
            f"  Liq: {fmt_price(pos['liquidation_price'])}\n\n"
        )
        buttons.append([InlineKeyboardButton(
            f"❌ Close #{pos['id']} ({_perp_pnl_str(upnl)})",
            callback_data=f"perp_close:{pos['id']}"
        )])

    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="perp_positions")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="menu:perp")])
    await send_perp(update, text, InlineKeyboardMarkup(buttons), edit=True)


# ─── Open position flow ───────────────────────────────────────────────────────

async def perp_open_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    direction = update.callback_query.data.split(":")[1]
    ctx.user_data["perp_dir"] = direction
    dir_e = "📈 LONG" if direction == "long" else "📉 SHORT"

    rows = []
    for market in PERP_MARKETS:
        price = get_perp_price(market)
        label = f"{market} — {fmt_price(price)}" if price else market
        rows.append([InlineKeyboardButton(label, callback_data=f"pm:{market}")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="menu:perp")])

    await send_perp(update,
        f"{dir_e}\n\nSelect a market:", InlineKeyboardMarkup(rows), edit=True)
    return AWAIT_PERP_MARKET


async def perp_market_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    market = update.callback_query.data.split(":")[1]
    ctx.user_data["perp_market"] = market
    direction = ctx.user_data.get("perp_dir", "long")
    price = get_perp_price(market)
    dir_label = "📈 LONG" if direction == "long" else "📉 SHORT"
    price_str = fmt_price(price) if price else "N/A"

    rows = [
        [InlineKeyboardButton("$1",  callback_data="ps:1"),
         InlineKeyboardButton("$5",  callback_data="ps:5"),
         InlineKeyboardButton("$10", callback_data="ps:10")],
        [InlineKeyboardButton("$25", callback_data="ps:25"),
         InlineKeyboardButton("$50", callback_data="ps:50"),
         InlineKeyboardButton("Custom", callback_data="ps:custom")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:perp")],
    ]
    await send_perp(update,
        f"💰 *{market}* — {dir_label}\nPrice: {price_str}\n\nPosition size \\(USD\\)?",
        InlineKeyboardMarkup(rows), edit=True)
    return AWAIT_PERP_SIZE


async def perp_size_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    val = update.callback_query.data.split(":")[1]
    if val == "custom":
        await send_perp(update, "✏️ Enter size in USD \\(e\\.g\\. `15`\\):", edit=True)
        return AWAIT_PERP_SIZE
    ctx.user_data["perp_size"] = float(val)
    return await _ask_leverage(update, ctx)


async def perp_size_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["perp_size"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid\\. Enter a number like `10`",
                                        parse_mode=ParseMode.MARKDOWN)
        return AWAIT_PERP_SIZE
    return await _ask_leverage(update, ctx)


async def _ask_leverage(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    size = ctx.user_data.get("perp_size", 10)
    rows = [
        [InlineKeyboardButton("1x", callback_data="pl:1"),
         InlineKeyboardButton("2x", callback_data="pl:2"),
         InlineKeyboardButton("3x", callback_data="pl:3")],
        [InlineKeyboardButton("5x", callback_data="pl:5"),
         InlineKeyboardButton("10x", callback_data="pl:10"),
         InlineKeyboardButton("20x", callback_data="pl:20")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:perp")],
    ]
    msg = f"⚡ *Select Leverage*\n\nSize: ${size}\n⚠️ Start low — 1x\\-3x for beginners\\!"
    if update.callback_query:
        await send_perp(update, msg, InlineKeyboardMarkup(rows), edit=True)
    else:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN,
                                        reply_markup=InlineKeyboardMarkup(rows))
    return AWAIT_PERP_LEV


async def perp_lev_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    leverage  = float(update.callback_query.data.split(":")[1])
    from bot_helpers import ensure_user
    user      = ensure_user(update)
    market    = ctx.user_data.get("perp_market", "BTC-PERP")
    direction = ctx.user_data.get("perp_dir", "long")
    size      = ctx.user_data.get("perp_size", 10.0)

    try:
        result = paper_perp_open(user["id"], market, direction, size, leverage)
        dir_e  = "📈 LONG" if direction == "long" else "📉 SHORT"
        text = (
            f"✅ *Perp Opened\\!* \\[📝 Paper\\]\n\n"
            f"📊 *{market}* — {dir_e}\n"
            f"💰 ${size:.0f} × {leverage:.0f}x = ${size*leverage:.0f} notional\n"
            f"📍 Entry: {fmt_price(result['entry_price'])}\n"
            f"💧 Liq: {fmt_price(result['liquidation'])}\n"
            f"💸 Fee: ${result['fee']:.4f}\n\n"
            f"_Position \\#{result['position_id']} — /perp to manage_"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Positions", callback_data="perp_positions"),
             InlineKeyboardButton("« Menu", callback_data="menu:perp")]
        ])
        await send_perp(update, text, kb, edit=True)
    except Exception as e:
        await send_perp(update, f"❌ Failed: {e}", edit=True)
    return ConversationHandler.END


async def perp_close_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pos_id = int(update.callback_query.data.split(":")[1])
    from bot_helpers import ensure_user
    user = ensure_user(update)
    try:
        result = paper_perp_close(user["id"], pos_id)
        pnl    = result["realized_pnl"]
        pnl_e  = "✅" if pnl >= 0 else "❌"
        dir_e  = "📈 LONG" if result["direction"] == "long" else "📉 SHORT"
        text = (
            f"{pnl_e} *Closed \\#{pos_id}*\n\n"
            f"📊 {result['market']} — {dir_e}\n"
            f"Entry: {fmt_price(result['entry_price'])} → {fmt_price(result['exit_price'])}\n"
            f"{pnl_e} *P&L: `{_perp_pnl_str(pnl)} USD`*"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Positions", callback_data="perp_positions"),
             InlineKeyboardButton("« Menu", callback_data="menu:perp")]
        ])
        await send_perp(update, text, kb, edit=True)
    except Exception as e:
        await send_perp(update, f"❌ {e}", edit=True)


# ─── Strategies ───────────────────────────────────────────────────────────────

async def perp_strategies_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    keys = list(PERP_STRATEGIES.keys())
    rows = []
    for i in range(0, len(keys), 2):
        row = []
        for key in keys[i:i+2]:
            s = PERP_STRATEGIES[key]
            row.append(InlineKeyboardButton(
                f"{s['emoji']} {s['name'][:16]}", callback_data=f"psi:{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("« Back", callback_data="menu:perp")])
    await send_perp(update,
        "🤖 *Perp Strategies*\n\nTap to see full description:",
        InlineKeyboardMarkup(rows), edit=True)


async def perp_strat_info_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    key = update.callback_query.data.split(":")[1]
    s   = PERP_STRATEGIES.get(key)
    if not s:
        return
    desc = s["plain_english"]
    try:
        desc = desc.format(**s["params"])
    except Exception:
        pass
    text = (
        f"{s['emoji']} *{s['name']}*\n"
        f"_Risk: {s['risk']} · {s['best_for']}_\n\n"
        f"{desc}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"▶️ Start Strategy", callback_data=f"pss:{key}")],
        [InlineKeyboardButton("« Back", callback_data="perp_strategies")],
    ])
    await send_perp(update, text, kb, edit=True)


async def perp_strat_start_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    key = update.callback_query.data.split(":")[1]
    ctx.user_data["perp_strat_key"] = key
    rows = [[InlineKeyboardButton(m, callback_data=f"psm:{m}")] for m in PERP_MARKETS]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="perp_strategies")])
    s = PERP_STRATEGIES.get(key, {})
    await send_perp(update,
        f"🤖 *{s.get('name','Strategy')}*\n\nSelect market:",
        InlineKeyboardMarkup(rows), edit=True)


async def perp_strat_market_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    market = update.callback_query.data.split(":")[1]
    key    = ctx.user_data.get("perp_strat_key")
    s      = PERP_STRATEGIES.get(key, {})
    from bot_helpers import ensure_user
    user   = ensure_user(update)

    params = dict(s.get("params", {}))
    params["perp_market"]   = market
    params["strategy_type"] = "perp"

    sid = db.create_strategy({
        "user_id":       user["id"],
        "name":          key,
        "chain":         "near",
        "token_address": market,
        "token_symbol":  market,
        "mode":          "paper",
        "params":        params,
    })
    await send_perp(update,
        f"✅ *Perp Strategy Started\\!* \\[\\#{sid}\\]\n\n"
        f"{s.get('emoji','')} *{s.get('name',key)}*\n"
        f"Market: *{market}*\n\n"
        f"_Use /mystrats to track performance\\._",
        InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu:perp")]]),
        edit=True)


# ─── Vote flow ────────────────────────────────────────────────────────────────

async def perp_vote_start_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    rows = [[InlineKeyboardButton(m, callback_data=f"vm:{m}")] for m in PERP_MARKETS]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="menu:perp")])
    await send_perp(update, "🗳️ *Vote — Select Market:*", InlineKeyboardMarkup(rows), edit=True)
    return AWAIT_VOTE_DIR


async def vote_market_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    market = update.callback_query.data.split(":")[1]
    ctx.user_data["vote_market"] = market
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 UP / Long",    callback_data="vd:up"),
         InlineKeyboardButton("📉 DOWN / Short", callback_data="vd:down")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:perp")],
    ])
    await send_perp(update, f"🗳️ *{market}* — Which direction?", kb, edit=True)
    return AWAIT_VOTE_PCT


async def vote_dir_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data["vote_dir"] = update.callback_query.data.split(":")[1]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("55%", callback_data="vp:55"),
         InlineKeyboardButton("65%", callback_data="vp:65")],
        [InlineKeyboardButton("75%", callback_data="vp:75"),
         InlineKeyboardButton("90%", callback_data="vp:90")],
    ])
    dir_e = "📈 UP" if ctx.user_data["vote_dir"] == "up" else "📉 DOWN"
    await send_perp(update, f"Voted {dir_e} — Confidence?", kb, edit=True)
    return AWAIT_VOTE_PCT


async def vote_pct_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    pct       = float(update.callback_query.data.split(":")[1])
    market    = ctx.user_data.get("vote_market", "BTC-PERP")
    direction = ctx.user_data.get("vote_dir", "up")
    save_majority_vote(market, direction, pct, 1, "user", expires_minutes=10)
    dir_e = "📈 UP" if direction == "up" else "📉 DOWN"
    await send_perp(update,
        f"✅ *Vote Recorded\\!*\n\n{market}: {dir_e} @ {pct:.0f}% confidence\n\n"
        f"_Majority Vote Sniper strategy will use this\\._",
        InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu:perp")]]),
        edit=True)
    return ConversationHandler.END


# ─── History ──────────────────────────────────────────────────────────────────

async def perp_history_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    from bot_helpers import ensure_user
    user = ensure_user(update)
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM perp_positions WHERE user_id=? AND status='closed' ORDER BY closed_at DESC LIMIT 15",
        (user["id"],)
    ).fetchall()
    conn.close()

    if not rows:
        await send_perp(update, "📜 No closed perp positions yet\\.",
                        InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu:perp")]]),
                        edit=True)
        return

    text = "📜 *Perp History*\n\n"
    total = 0.0
    for pos in [dict(r) for r in rows]:
        pnl   = pos.get("realized_pnl", 0) or 0
        total += pnl
        pnl_e = "✅" if pnl >= 0 else "❌"
        dir_e = "📈" if pos["direction"] == "long" else "📉"
        text += (
            f"{pnl_e}{dir_e} *{pos['market']}* × {pos['leverage']:.0f}x"
            f" | P&L: `{_perp_pnl_str(pnl)}`\n"
        )
    total_e = "✅" if total >= 0 else "❌"
    text += f"\n{total_e} *Total: `{_perp_pnl_str(total)} USD`*"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu:perp")]])
    await send_perp(update, text, kb, edit=True)


# ─── Background perp strategy runner ─────────────────────────────────────────

async def process_perp_strategy(s: dict, params: dict, app) -> None:
    """Called by the main background loop for perp strategies."""
    market  = params.get("perp_market", "BTC-PERP")
    user_id = s["user_id"]
    signal  = get_perp_signal(s["name"], market, params, strategy_id=s["id"])

    if signal["signal"] in ("long", "short"):
        existing = get_open_perp_positions(user_id, s["id"])
        if not existing:
            size     = params.get("size_usd", 10.0)
            leverage = params.get("leverage", 2.0)
            result   = paper_perp_open(user_id, market, signal["signal"],
                                       size, leverage, strategy_id=s["id"])
            dir_e = "📈 LONG" if signal["signal"] == "long" else "📉 SHORT"
            s_info = PERP_STRATEGIES.get(s["name"], {})
            msg = (
                f"{'━'*26}\n"
                f"🤖 *Perp Signal* \\[📝 PAPER\\]\n"
                f"{s_info.get('emoji','📊')} *{s_info.get('name', s['name'])}*\n"
                f"📊 {market} — {dir_e}\n"
                f"💰 ${size:.0f} × {leverage:.0f}x\n"
                f"📍 Entry: {fmt_price(result['entry_price'])}\n"
                f"📝 {signal['reason']}\n"
                f"{'━'*26}"
            )
            try:
                await app.bot.send_message(
                    chat_id=s["tg_id"], text=msg, parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

    elif signal["signal"] == "close":
        for pos in get_open_perp_positions(user_id, s["id"]):
            price = get_perp_price(market) or pos["entry_price"]
            pnl   = close_perp_position(pos["id"], price, "strategy_signal")
            pnl_e = "✅" if pnl >= 0 else "❌"
            try:
                await app.bot.send_message(
                    chat_id=s["tg_id"],
                    text=f"{pnl_e} *Perp Closed*\n{market} | {signal['reason']}\nP&L: `{_perp_pnl_str(pnl)} USD`",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass


# ─── Rhea Finance Menu ───────────────────────────────────────────────────────

async def perp_rhea_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show Rhea Finance market links."""
    await update.callback_query.answer()
    text = (
        "🔥 *Rhea Finance — NEAR Perps DEX*\n\n"
        "Rhea is the leading perpetuals DEX on NEAR Protocol\. "
        "Connect your NEAR or HOT wallet to trade live\.\n\n"
        "*Available Markets:*\n"
    )
    rows = []
    for market, info in RHEA_MARKETS.items():
        price = get_perp_price(market)
        price_str = fmt_price(price) if price else "N/A"
        text += f"  • *{market}*: {price_str} \(max {info['leverage_max']}x\)\n"
        rows.append([
            InlineKeyboardButton(
                f"📈 Trade {market} on Rhea",
                url=info["trade_url"]
            )
        ])
    text += (
        "\n*How to connect your wallet:*\n"
        "1\. Open Rhea Finance link above\n"
        "2\. Click *Connect Wallet*\n"
        "3\. Select *NEAR Wallet*, *HOT Wallet*, or *MyNearWallet*\n"
        "4\. Approve the connection\n\n"
        "_Paper trade here first to test your strategy, then go live on Rhea\!_"
    )
    rows.append([InlineKeyboardButton("📝 Paper Trade Instead", callback_data="perp_open:long")])
    rows.append([InlineKeyboardButton("« Back", callback_data="menu:perp")])
    await send_perp(update, text, InlineKeyboardMarkup(rows), edit=True)


async def perp_orderly_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show Orderly Network market links."""
    await update.callback_query.answer()
    from trading.perpetuals import ORDERLY_MARKETS
    text = (
        "📊 *Orderly Network — Institutional Perps*\n\n"
        "Orderly powers professional perp trading on NEAR with "
        "deep liquidity and tight spreads\.\n\n"
        "*Markets:*\n"
    )
    rows = []
    for market, info in ORDERLY_MARKETS.items():
        price = get_perp_price(market)
        price_str = fmt_price(price) if price else "N/A"
        text += f"  • *{market}*: {price_str}\n"
        rows.append([InlineKeyboardButton(
            f"📊 {market} on Orderly", url=info["trade_url"]
        )])
    rows.append([InlineKeyboardButton("📝 Paper Trade Instead", callback_data="perp_open:long")])
    rows.append([InlineKeyboardButton("« Back", callback_data="menu:perp")])
    await send_perp(update, text, InlineKeyboardMarkup(rows), edit=True)


async def perp_import_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Guide user to import NEAR/HOT wallet for live trading."""
    await update.callback_query.answer()
    text = (
        "💳 *Import NEAR / HOT Wallet*\n\n"
        "To trade live perps on Rhea or Orderly, import your wallet:\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Ⓝ *NEAR Wallet*\n"
        "Go to: Menu → Wallets → Import\n"
        "Select chain: *NEAR*\n"
        "Paste your NEAR private key or 12\-word seed phrase\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 *HOT Wallet \(HOT Chain\)*\n"
        "Go to: Menu → Wallets → Import\n"
        "Select chain: *HOT*\n"
        "HOT Wallet uses the same key as your NEAR account\n"
        "Find it in: HOT Wallet app → Settings → Export Key\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Tip:* After importing, use paper trading first\. "
        "When ready for live trading, your imported wallet "
        "will be used automatically on Rhea\.\n\n"
        "_Your key is encrypted with AES\-256 and never sent anywhere\._"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👛 Go to Wallets → Import", callback_data="wallet:import")],
        [InlineKeyboardButton("🔥 Rhea Finance", url="https://rhea.finance")],
        [InlineKeyboardButton("« Back", callback_data="menu:perp")],
    ])
    await send_perp(update, text, kb, edit=True)


# ─── Market info panel (shown when opening position) ─────────────────────────

async def perp_market_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show full market info with Rhea link when a market is selected."""
    await update.callback_query.answer()
    market = update.callback_query.data.split(":")[1]
    ctx.user_data["perp_market"] = market
    direction = ctx.user_data.get("perp_dir", "long")

    price     = get_perp_price(market)
    links     = get_market_links(market)
    dir_label = "📈 LONG" if direction == "long" else "📉 SHORT"
    price_str = fmt_price(price) if price else "N/A"
    max_lev   = links.get("max_leverage_rhea", 20)

    # Market stats
    from utils.prices import get_price_coingecko
    from trading.perpetuals import PERP_MARKETS as PM
    cg_id = PM.get(market, {}).get("base")
    pd = get_price_coingecko(cg_id) if cg_id else None
    change_str = ""
    if pd and pd.get("change24h") is not None:
        c = pd["change24h"]
        change_str = f" \({'+'if c>=0 else ''}{c:.1f}%\)"

    text = (
        f"📊 *{market}*\n\n"
        f"💵 Price: *{price_str}*{change_str}\n"
        f"⚡ Max Leverage on Rhea: *{max_lev}x*\n"
        f"Direction: {dir_label}\n\n"
        f"_Choose position size:_"
    )
    rows = [
        [InlineKeyboardButton("$1",  callback_data="ps:1"),
         InlineKeyboardButton("$5",  callback_data="ps:5"),
         InlineKeyboardButton("$10", callback_data="ps:10")],
        [InlineKeyboardButton("$25", callback_data="ps:25"),
         InlineKeyboardButton("$50", callback_data="ps:50"),
         InlineKeyboardButton("Custom", callback_data="ps:custom")],
        [InlineKeyboardButton(
            f"🔥 Trade Live on Rhea",
            url=get_rhea_trade_url(market)
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:perp")],
    ]
    await send_perp(update, text, InlineKeyboardMarkup(rows), edit=True)
    return AWAIT_PERP_SIZE



# ─── Aster Marketplace Menu ───────────────────────────────────────────────────

async def perp_aster_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show Aster marketplace — perps + prediction markets on NEAR."""
    await update.callback_query.answer()

    text = (
        "⭐ *Aster Marketplace — NEAR Perps & Predictions*\n\n"
        "Aster is a next\-gen hybrid platform combining perpetual futures "
        "with prediction markets on NEAR Protocol\.\n"
        "Connect your NEAR or HOT wallet and trade up to *100x* leverage\.\n\n"
        "*Available Markets:*\n"
    )

    rows = []
    for market, info in ASTER_MARKETS.items():
        price     = get_perp_price(market)
        price_str = fmt_price(price) if price else "N/A"
        max_lev   = info.get("leverage_max", 50)
        text += f"  • *{market}*: {price_str} \(max {max_lev}x\)\n"
        rows.append([
            InlineKeyboardButton(
                f"📈 Trade {market}", url=info["trade_url"]
            ),
            InlineKeyboardButton(
                f"🗳️ Predict {market.split('-')[0]}", url=info["predict_url"]
            ),
        ])

    text += (
        "\n*Two ways to use Aster:*\n"
        "1\. 📈 *Trade* — Open long/short positions with leverage\n"
        "2\. 🗳️ *Predict* — Vote on price direction in short rounds "
        "\(works with the Majority Vote Sniper strategy\)\n\n"
        "*How to connect:*\n"
        "1\. Tap any market link above\n"
        "2\. Click *Connect Wallet* on Aster\n"
        "3\. Choose *NEAR Wallet* or *HOT Wallet*\n"
        "4\. Sign the connection\n\n"
        "_Paper trade here first to practice, then go live on Aster\!_"
    )

    rows.append([InlineKeyboardButton(
        "🤖 Majority Vote Sniper Strategy",
        callback_data="psi:perp_majority_vote"
    )])
    rows.append([InlineKeyboardButton("📝 Paper Trade", callback_data="perp_open:long")])
    rows.append([InlineKeyboardButton("« Back", callback_data="menu:perp")])

    await send_perp(update, text, InlineKeyboardMarkup(rows), edit=True)


# ─── Enhanced market info panel with all 3 exchange links ────────────────────

async def perp_market_info_v2(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Full market info panel — shows Rhea, Aster and Orderly links."""
    await update.callback_query.answer()
    market    = update.callback_query.data.split(":")[1]
    ctx.user_data["perp_market"] = market
    direction = ctx.user_data.get("perp_dir", "long")

    price     = get_perp_price(market)
    links     = get_market_links(market)
    dir_label = "📈 LONG" if direction == "long" else "📉 SHORT"
    price_str = fmt_price(price) if price else "N/A"
    max_lev_r = links.get("max_leverage_rhea", 20)
    max_lev_a = links.get("max_leverage_aster", 50)

    from utils.prices import get_price_coingecko
    from trading.perpetuals import PERP_MARKETS as PM
    cg_id = PM.get(market, {}).get("base")
    pd    = get_price_coingecko(cg_id) if cg_id else None
    change_str = ""
    if pd and pd.get("change24h") is not None:
        c = pd["change24h"]
        sign = "+" if c >= 0 else ""
        change_str = f" \({sign}{c:.1f}%\)"

    text = (
        f"📊 *{market}*\n\n"
        f"💵 Price: *{price_str}*{change_str}\n"
        f"Direction: {dir_label}\n\n"
        f"*Live Trading Options:*\n"
        f"  🔥 Rhea Finance — up to {max_lev_r}x\n"
        f"  ⭐ Aster — up to {max_lev_a}x\n\n"
        f"_Select paper position size below, or tap a live link:_"
    )

    rows = [
        [InlineKeyboardButton("$1",   callback_data="ps:1"),
         InlineKeyboardButton("$5",   callback_data="ps:5"),
         InlineKeyboardButton("$10",  callback_data="ps:10")],
        [InlineKeyboardButton("$25",  callback_data="ps:25"),
         InlineKeyboardButton("$50",  callback_data="ps:50"),
         InlineKeyboardButton("Custom", callback_data="ps:custom")],
    ]

    # Live exchange buttons
    live_row = []
    if links.get("rhea_url"):
        live_row.append(InlineKeyboardButton(
            "🔥 Live on Rhea", url=links["rhea_url"]
        ))
    if links.get("aster_url"):
        live_row.append(InlineKeyboardButton(
            "⭐ Live on Aster", url=links["aster_url"]
        ))
    if live_row:
        rows.append(live_row)

    if links.get("orderly_url"):
        rows.append([InlineKeyboardButton(
            "📊 Live on Orderly", url=links["orderly_url"]
        )])

    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="menu:perp")])
    await send_perp(update, text, InlineKeyboardMarkup(rows), edit=True)
    return AWAIT_PERP_SIZE


# ─── Handler registration ─────────────────────────────────────────────────────

def register_perp_handlers(app):
    """Call this from main() to register all perp handlers."""
    from telegram.ext import ConversationHandler as CH

    open_conv = CH(
        entry_points=[CallbackQueryHandler(perp_open_callback, pattern="^perp_open:")],
        states={
            AWAIT_PERP_MARKET: [CallbackQueryHandler(perp_market_info_v2, pattern="^pm:")],
            AWAIT_PERP_SIZE:   [
                CallbackQueryHandler(perp_size_cb, pattern="^ps:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, perp_size_text),
            ],
            AWAIT_PERP_LEV:    [CallbackQueryHandler(perp_lev_cb, pattern="^pl:")],
        },
        fallbacks=[CallbackQueryHandler(lambda u,c: None, pattern="^menu:perp$")],
        per_message=False,
    )

    vote_conv = CH(
        entry_points=[CallbackQueryHandler(perp_vote_start_callback, pattern="^perp_vote_start$")],
        states={
            AWAIT_VOTE_DIR: [CallbackQueryHandler(vote_market_cb, pattern="^vm:")],
            AWAIT_VOTE_PCT: [
                CallbackQueryHandler(vote_dir_cb, pattern="^vd:"),
                CallbackQueryHandler(vote_pct_cb, pattern="^vp:"),
            ],
        },
        fallbacks=[CallbackQueryHandler(lambda u,c: None, pattern="^menu:perp$")],
        per_message=False,
    )

    app.add_handler(open_conv)
    app.add_handler(vote_conv)
    app.add_handler(CommandHandler("perp", perp_cmd))
    app.add_handler(CallbackQueryHandler(perp_menu,               pattern="^menu:perp$"))
    app.add_handler(CallbackQueryHandler(perp_positions_callback, pattern="^perp_positions$"))
    app.add_handler(CallbackQueryHandler(perp_close_callback,     pattern="^perp_close:"))
    app.add_handler(CallbackQueryHandler(perp_strategies_callback,pattern="^perp_strategies$"))
    app.add_handler(CallbackQueryHandler(perp_strat_info_callback,pattern="^psi:"))
    app.add_handler(CallbackQueryHandler(perp_strat_start_callback,pattern="^pss:"))
    app.add_handler(CallbackQueryHandler(perp_strat_market_callback,pattern="^psm:"))
    app.add_handler(CallbackQueryHandler(perp_history_callback,   pattern="^perp_history$"))
    app.add_handler(CallbackQueryHandler(perp_rhea_menu,           pattern="^perp_rhea_menu$"))
    app.add_handler(CallbackQueryHandler(perp_aster_menu,          pattern="^perp_aster_menu$"))
    app.add_handler(CallbackQueryHandler(perp_orderly_menu,        pattern="^perp_orderly_menu$"))
    app.add_handler(CallbackQueryHandler(perp_import_wallet,       pattern="^perp_import_wallet$"))
    app.add_handler(CallbackQueryHandler(perp_market_info_v2,      pattern="^pm:"))

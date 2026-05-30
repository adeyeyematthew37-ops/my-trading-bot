#!/usr/bin/env python3
# bot.py  —  Full Telegram trading bot
# Local:   edit config/secrets.py and set BOT_TOKEN
# Railway: set BOT_TOKEN as an environment variable in the dashboard

import asyncio
import json
import sys
import os
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

from config.secrets import BOT_TOKEN
from config.chains import CHAINS, get_chain, all_chains
from utils import database as db
from utils.encryption import encrypt, decrypt
from utils.prices import (
    get_native_prices, get_token_price, get_price_coingecko,
    get_price_dexscreener, search_token, fmt_price, fmt_change
)
from wallet.generator import (
    generate_evm_wallet, generate_solana_wallet,
    evm_from_private_key, solana_from_private_key, short_addr
)
from wallet.balances import get_native_balance, get_solana_balance
from trading.paper_trade import paper_buy, paper_sell, get_paper_portfolio
from strategies.engine import (
    STRATEGIES, get_signal, format_signal_message
)

# ── Conversation States ───────────────────────────────────────────────────────
(
    AWAIT_TOPUP_AMOUNT, AWAIT_TOPUP_ASSET, AWAIT_TOPUP_CHAIN,
    AWAIT_IMPORT_KEY, AWAIT_IMPORT_CHAIN,
    AWAIT_BUY_TOKEN, AWAIT_BUY_AMOUNT,
    AWAIT_SELL_TOKEN, AWAIT_SELL_AMOUNT,
    AWAIT_DCA_CHAIN, AWAIT_DCA_TOKEN, AWAIT_DCA_AMOUNT, AWAIT_DCA_FREQ, AWAIT_DCA_TOTAL,
    AWAIT_STRATEGY_CHAIN, AWAIT_STRATEGY_TOKEN, AWAIT_STRATEGY_NAME, AWAIT_STRATEGY_MODE,
    AWAIT_ALERT_CHAIN, AWAIT_ALERT_TOKEN, AWAIT_ALERT_COND, AWAIT_ALERT_PRICE,
    AWAIT_SEND_CHAIN, AWAIT_SEND_TO, AWAIT_SEND_AMOUNT,
) = range(25)

# ── Helpers ───────────────────────────────────────────────────────────────────

def chain_keyboard(prefix: str, extra_row: list = None) -> InlineKeyboardMarkup:
    chains = all_chains()
    rows = []
    for i in range(0, len(chains), 3):
        row = []
        for key, info in chains[i:i+3]:
            row.append(InlineKeyboardButton(
                f"{info['emoji']} {info['name']}", callback_data=f"{prefix}:{key}"
            ))
        rows.append(row)
    if extra_row:
        rows.append(extra_row)
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👛 Wallets", callback_data="menu:wallets"),
         InlineKeyboardButton("💰 Balances", callback_data="menu:balances")],
        [InlineKeyboardButton("📝 Paper Trade", callback_data="menu:paper"),
         InlineKeyboardButton("💎 Live Trade", callback_data="menu:live")],
        [InlineKeyboardButton("🤖 Strategies", callback_data="menu:strategies"),
         InlineKeyboardButton("📊 DCA Bots", callback_data="menu:dca")],
        [InlineKeyboardButton("💵 Prices", callback_data="menu:prices"),
         InlineKeyboardButton("🔔 Alerts", callback_data="menu:alerts")],
        [InlineKeyboardButton("📜 History", callback_data="menu:history"),
         InlineKeyboardButton("❓ Help", callback_data="menu:help")],
    ])

def ensure_user(update: Update) -> dict:
    u = update.effective_user
    return db.upsert_user(u.id, u.username, u.first_name)

async def send(update: Update, text: str, keyboard=None, edit=False):
    kwargs = {"text": text, "parse_mode": ParseMode.MARKDOWN, "disable_web_page_preview": True}
    if keyboard:
        kwargs["reply_markup"] = keyboard
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(**kwargs)
    elif update.callback_query:
        await update.callback_query.message.reply_text(**kwargs)
    else:
        await update.message.reply_text(**kwargs)

# ═══════════════════════════════════════════════════════════════════════════════
#  /start  —  Main menu
# ═══════════════════════════════════════════════════════════════════════════════

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    name = update.effective_user.first_name or "Trader"
    text = (
        f"🤖 *CryptoBot — Multi-Chain Trading*\n\n"
        f"Welcome, *{name}*! 🚀\n\n"
        f"Supported chains:\n"
        f"⟠ Ethereum  🔶 BNB Chain  🟣 Polygon\n"
        f"🔵 Arbitrum  🔷 Base  🔺 Avalanche  ◎ Solana\n\n"
        f"Choose an option below:"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                                       reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                        reply_markup=main_menu_keyboard())

# ═══════════════════════════════════════════════════════════════════════════════
#  MENU CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════════

async def menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    action = update.callback_query.data.split(":")[1]

    if action == "wallets":   await show_wallets(update, ctx)
    elif action == "balances": await show_balances(update, ctx)
    elif action == "paper":    await paper_menu(update, ctx)
    elif action == "live":     await live_menu(update, ctx)
    elif action == "strategies": await strategies_menu(update, ctx)
    elif action == "dca":      await dca_menu(update, ctx)
    elif action == "prices":   await prices_menu(update, ctx)
    elif action == "alerts":   await alerts_menu(update, ctx)
    elif action == "history":  await history_menu(update, ctx)
    elif action == "help":     await help_cmd(update, ctx)

async def cancel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await start(update, ctx)
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════════════════════════
#  WALLETS
# ═══════════════════════════════════════════════════════════════════════════════

async def show_wallets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    wallets = db.get_wallets(user["id"])

    if not wallets:
        text = "👛 *No wallets yet.*\n\nGenerate or import a wallet to get started."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🆕 Generate Wallet", callback_data="wallet:gen"),
             InlineKeyboardButton("📥 Import Key", callback_data="wallet:import")],
            [InlineKeyboardButton("« Back", callback_data="back:main")],
        ])
        await send(update, text, kb, edit=True)
        return

    # Group by chain
    grouped: dict = {}
    for w in wallets:
        grouped.setdefault(w["chain"], []).append(w)

    text = "👛 *Your Wallets*\n\n"
    for chain_key, ws in grouped.items():
        ci = CHAINS.get(chain_key, {})
        text += f"{ci.get('emoji','🔗')} *{ci.get('name', chain_key)}*\n"
        for w in ws:
            tag = "✅" if w["is_default"] else "  "
            wtype = "📝" if w["wallet_type"] == "paper" else "💎"
            text += f"  {tag}{wtype} `{short_addr(w['address'])}` — {w['label']} \\[#{w['id']}\\]\n"
        text += "\n"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 Generate", callback_data="wallet:gen"),
         InlineKeyboardButton("📥 Import", callback_data="wallet:import")],
        [InlineKeyboardButton("« Back", callback_data="back:main")],
    ])
    await send(update, text, kb, edit=True)

async def wallet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    action = update.callback_query.data.split(":")[1]

    if action == "gen":
        kb = chain_keyboard("gen_wallet")
        await send(update, "🔗 *Select a chain to generate a wallet for:*", kb, edit=True)
    elif action == "import":
        ctx.user_data["import_step"] = "chain"
        kb = chain_keyboard("import_chain")
        await send(update, "📥 *Import Wallet — Select chain:*", kb, edit=True)

async def gen_wallet_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    chain_key = update.callback_query.data.split(":")[1]
    chain_info = CHAINS.get(chain_key)
    if not chain_info:
        await send(update, "❌ Unknown chain.", edit=True)
        return

    user = ensure_user(update)
    existing = db.get_wallets(user["id"], chain=chain_key)
    if len(existing) >= 5:
        await send(update, "⚠️ Max 5 wallets per chain. Delete one first.", edit=True)
        return

    if chain_info["type"] == "solana":
        w = generate_solana_wallet()
    else:
        w = generate_evm_wallet()

    enc_key = encrypt(w["private_key"])
    wtype = "paper"
    db.save_wallet(user["id"], chain_key, w["address"], enc_key,
                   label=f"{chain_info['name']} Wallet", wallet_type=wtype)

    # Give paper wallets a starter balance
    if wtype == "paper":
        native_sym = chain_info["symbol"]
        current = db.get_paper_balance(user["id"], native_sym, chain_key)
        if current == 0:
            db.set_paper_balance(user["id"], native_sym, chain_key, 1.0)

    mnemonic_line = f"\n\n🔑 *Seed Phrase:*\n`{w['mnemonic']}`" if w.get("mnemonic") else ""
    text = (
        f"✅ *New {chain_info['emoji']} {chain_info['name']} Wallet Created!*\n\n"
        f"📍 *Address:*\n`{w['address']}`"
        f"{mnemonic_line}\n\n"
        f"⚠️ *NEVER share your seed phrase or private key!*\n"
        f"📝 This is a *paper wallet* — topped up with 1 {chain_info['symbol']} to start.\n"
        f"Use /topup to add more paper balance, or /fund to deposit real crypto."
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Wallets", callback_data="menu:wallets")]])
    await send(update, text, kb, edit=True)

async def import_chain_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    chain_key = update.callback_query.data.split(":")[1]
    ctx.user_data["import_chain"] = chain_key
    chain_info = CHAINS.get(chain_key, {})
    await send(update,
        f"📥 *Import {chain_info.get('emoji','')} {chain_info.get('name', chain_key)} Wallet*\n\n"
        f"Send your private key now.\n⚠️ Delete that message after sending!",
        edit=True)
    return AWAIT_IMPORT_KEY

async def import_key_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    chain_key = ctx.user_data.get("import_chain", "ethereum")
    pk = update.message.text.strip()
    chain_info = CHAINS.get(chain_key, {})

    # Delete user message for security
    try:
        await update.message.delete()
    except Exception:
        pass

    try:
        if chain_info.get("type") == "solana":
            w = solana_from_private_key(pk)
        else:
            w = evm_from_private_key(pk)
        enc_key = encrypt(w["private_key"])
        db.save_wallet(user["id"], chain_key, w["address"], enc_key,
                       label=f"Imported {chain_info.get('name', chain_key)}", wallet_type="live")
        await update.message.reply_text(
            f"✅ *Wallet Imported as LIVE wallet!*\n\n"
            f"{chain_info.get('emoji','')} Chain: {chain_info.get('name', chain_key)}\n"
            f"📍 Address: `{w['address']}`\n\n"
            f"This is a *live wallet* — trades will use real funds.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Import failed: {e}", parse_mode=ParseMode.MARKDOWN)

    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════════════════════════
#  BALANCES
# ═══════════════════════════════════════════════════════════════════════════════

async def show_balances(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    await send(update, "⏳ Fetching balances...", edit=True)

    # Paper balances
    paper_balances = db.get_all_paper_balances(user["id"])
    # Live wallets
    live_wallets = db.get_wallets(user["id"], wallet_type="live")

    text = "💰 *Your Balances*\n\n"

    if paper_balances:
        text += "📝 *Paper Portfolio*\n"
        for bal in paper_balances:
            ci = CHAINS.get(bal["chain"], {})
            text += f"  {ci.get('emoji','🔗')} {bal['asset']}: `{bal['balance']:.6f}`\n"
        text += "\n"

    if live_wallets:
        text += "💎 *Live Wallets*\n"
        for w in live_wallets:
            ci = CHAINS.get(w["chain"], {})
            try:
                if ci.get("type") == "solana":
                    bal = get_solana_balance(w["address"])
                else:
                    bal = get_native_balance(w["address"], w["chain"])
                text += f"  {ci.get('emoji','🔗')} `{short_addr(w['address'])}`: `{bal:.6f}` {ci.get('symbol','')}\n"
            except Exception:
                text += f"  {ci.get('emoji','🔗')} `{short_addr(w['address'])}`: _(error fetching)_\n"
    elif not paper_balances:
        text += "_No wallets yet. Use /start → Wallets to create one._"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Top Up Paper", callback_data="topup:start"),
         InlineKeyboardButton("💎 Fund Live", callback_data="fund:start")],
        [InlineKeyboardButton("« Back", callback_data="back:main")],
    ])
    await send(update, text, kb, edit=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  TOP-UP PAPER BALANCE
# ═══════════════════════════════════════════════════════════════════════════════

async def topup_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = chain_keyboard("topup_chain")
    await send(update, "➕ *Top Up Paper Balance*\n\nSelect a chain:", kb, edit=True)
    return AWAIT_TOPUP_CHAIN

async def topup_chain_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    chain_key = update.callback_query.data.split(":")[1]
    ctx.user_data["topup_chain"] = chain_key
    ci = CHAINS.get(chain_key, {})

    # Show asset options
    native = ci.get("symbol", "ETH")
    buttons = [
        [InlineKeyboardButton(f"{native} (native)", callback_data=f"topup_asset:{native}"),
         InlineKeyboardButton("USDT", callback_data="topup_asset:USDT"),
         InlineKeyboardButton("USDC", callback_data="topup_asset:USDC")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    await send(update,
        f"➕ *Top Up — {ci.get('emoji','')} {ci.get('name', chain_key)}*\n\nSelect asset to top up:",
        InlineKeyboardMarkup(buttons), edit=True)
    return AWAIT_TOPUP_ASSET

async def topup_asset_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    asset = update.callback_query.data.split(":")[1]
    ctx.user_data["topup_asset"] = asset
    chain_key = ctx.user_data.get("topup_chain", "ethereum")
    ci = CHAINS.get(chain_key, {})

    # Quick amount buttons
    buttons = [
        [InlineKeyboardButton("0.1", callback_data="topup_amt:0.1"),
         InlineKeyboardButton("0.5", callback_data="topup_amt:0.5"),
         InlineKeyboardButton("1", callback_data="topup_amt:1")],
        [InlineKeyboardButton("5", callback_data="topup_amt:5"),
         InlineKeyboardButton("10", callback_data="topup_amt:10"),
         InlineKeyboardButton("100", callback_data="topup_amt:100")],
        [InlineKeyboardButton("1000", callback_data="topup_amt:1000"),
         InlineKeyboardButton("Custom...", callback_data="topup_amt:custom")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    current = db.get_paper_balance(
        db.get_user(update.effective_user.id)["id"], asset, chain_key
    )
    await send(update,
        f"➕ *Top Up {asset} on {ci.get('name', chain_key)}*\n\n"
        f"Current balance: `{current:.6f} {asset}`\n\n"
        f"How much to add?",
        InlineKeyboardMarkup(buttons), edit=True)
    return AWAIT_TOPUP_AMOUNT

async def topup_amount_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    amt_str = update.callback_query.data.split(":")[1]
    if amt_str == "custom":
        await send(update, "✏️ Send the custom amount (e.g. `2.5`):", edit=True)
        return AWAIT_TOPUP_AMOUNT

    await _do_topup(update, ctx, float(amt_str))
    return ConversationHandler.END

async def topup_custom_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Send a number like `1.5`",
                                        parse_mode=ParseMode.MARKDOWN)
        return AWAIT_TOPUP_AMOUNT
    await _do_topup(update, ctx, amount)
    return ConversationHandler.END

async def _do_topup(update: Update, ctx: ContextTypes.DEFAULT_TYPE, amount: float):
    user = ensure_user(update)
    chain_key = ctx.user_data.get("topup_chain", "ethereum")
    asset = ctx.user_data.get("topup_asset", "ETH")
    ci = CHAINS.get(chain_key, {})

    db.add_paper_balance(user["id"], asset, chain_key, amount)
    new_bal = db.get_paper_balance(user["id"], asset, chain_key)

    text = (
        f"✅ *Paper Balance Topped Up!*\n\n"
        f"{ci.get('emoji','')} Chain: *{ci.get('name', chain_key)}*\n"
        f"💰 Added: `{amount} {asset}`\n"
        f"📊 New Balance: `{new_bal:.6f} {asset}`\n\n"
        f"_Use /start → Paper Trade to start trading!_"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="back:main")]])
    if update.callback_query:
        await send(update, text, kb, edit=True)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

# ═══════════════════════════════════════════════════════════════════════════════
#  FUND LIVE WALLET
# ═══════════════════════════════════════════════════════════════════════════════

async def fund_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user = ensure_user(update)
    live_wallets = db.get_wallets(user["id"], wallet_type="live")

    if not live_wallets:
        text = (
            "💎 *Fund Live Wallet*\n\n"
            "You don't have a live wallet yet.\n\n"
            "Import your existing wallet using the Wallets menu "
            "to enable live trading with real funds."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Import Wallet", callback_data="wallet:import")],
            [InlineKeyboardButton("« Back", callback_data="back:main")],
        ])
    else:
        lines = ["💎 *Fund Your Live Wallet*\n\n", "Send crypto directly to one of your addresses:\n"]
        for w in live_wallets:
            ci = CHAINS.get(w["chain"], {})
            lines.append(f"\n{ci.get('emoji','')} *{ci.get('name', w['chain'])}*")
            lines.append(f"`{w['address']}`")
        lines.append(
            "\n\n⚠️ *Only send the correct asset for each chain!*\n"
            "After sending, your balance will update automatically."
        )
        text = "\n".join(lines)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="back:main")]])

    await send(update, text, kb, edit=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  PAPER TRADE MENU
# ═══════════════════════════════════════════════════════════════════════════════

async def paper_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    portfolio = get_paper_portfolio(user["id"])
    total = portfolio["total_usd"]

    text = (
        f"📝 *Paper Trading*\n\n"
        f"Portfolio Value: *${total:.2f}*\n\n"
        f"Paper trading uses virtual money — perfect for testing strategies risk-free!\n\n"
        f"Commands:\n"
        f"• /pbuy \\[chain\\] \\[token\\] \\[amount\\] — Paper buy\n"
        f"• /psell \\[chain\\] \\[token\\] \\[amount\\] — Paper sell\n"
        f"• /portfolio — View paper portfolio\n"
        f"• /topup — Add paper balance"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Buy", callback_data="ptrade:buy"),
         InlineKeyboardButton("📉 Sell", callback_data="ptrade:sell")],
        [InlineKeyboardButton("📊 Portfolio", callback_data="ptrade:portfolio"),
         InlineKeyboardButton("➕ Top Up", callback_data="topup:start")],
        [InlineKeyboardButton("« Back", callback_data="back:main")],
    ])
    await send(update, text, kb, edit=True)

async def paper_trade_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    action = update.callback_query.data.split(":")[1]

    if action == "portfolio":
        user = ensure_user(update)
        portfolio = get_paper_portfolio(user["id"])
        text = "📊 *Paper Portfolio*\n\n"
        if not portfolio["items"]:
            text += "_No balances yet. Use /topup to add paper funds._"
        else:
            for item in portfolio["items"]:
                ci = CHAINS.get(item["chain"], {})
                usd = f" (≈${item['usd_value']:.2f})" if item["usd_value"] > 0 else ""
                text += f"{ci.get('emoji','🔗')} *{item['symbol']}*: `{item['balance']:.6f}`{usd}\n"
            text += f"\n💵 *Total: ${portfolio['total_usd']:.2f}*"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu:paper")]])
        await send(update, text, kb, edit=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  /pbuy and /psell commands
# ═══════════════════════════════════════════════════════════════════════════════

async def pbuy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 3:
        await update.message.reply_text(
            "📝 *Paper Buy*\n\nUsage: `/pbuy [chain] [token_address] [amount_native]`\n\n"
            "Example: `/pbuy ethereum 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 0.01`\n"
            "_Buys with 0.01 ETH of paper money_",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    chain_key = args[0].lower()
    token = args[1]
    try:
        amount = float(args[2])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount."); return

    _, chain_info = get_chain(chain_key)
    if not chain_info:
        await update.message.reply_text(f"❌ Unknown chain: {chain_key}"); return

    user = ensure_user(update)
    await update.message.reply_text("⏳ Fetching price and executing paper trade...")

    try:
        # Try to get token symbol from DexScreener
        price_data = get_price_dexscreener(chain_key, token)
        symbol = "TOKEN"
        if price_data and price_data.get("base_token"):
            symbol = price_data["base_token"].get("symbol", "TOKEN")

        result = paper_buy(user["id"], chain_key, token, symbol, amount)
        await update.message.reply_text(
            f"✅ *Paper Buy Executed!*\n\n"
            f"{chain_info['emoji']} Chain: *{chain_info['name']}*\n"
            f"💸 Spent: `{result['spent']:.6f} {result['spent_symbol']}`\n"
            f"🪙 Received: `{result['received']:.6f} {result['received_symbol']}`\n"
            f"💵 Price: *{fmt_price(result['price'])}*\n"
            f"💰 USD Value: *${result['usd_value']:.2f}*\n\n"
            f"_Trade ID: #{result['trade_id']}_",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Paper buy failed: {e}", parse_mode=ParseMode.MARKDOWN)

async def psell_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 3:
        await update.message.reply_text(
            "📝 *Paper Sell*\n\nUsage: `/psell [chain] [token_address] [amount_tokens]`\n\n"
            "Example: `/psell ethereum 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 100`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    chain_key = args[0].lower()
    token = args[1]
    try:
        amount = float(args[2])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount."); return

    _, chain_info = get_chain(chain_key)
    if not chain_info:
        await update.message.reply_text(f"❌ Unknown chain: {chain_key}"); return

    user = ensure_user(update)
    await update.message.reply_text("⏳ Executing paper sell...")

    try:
        price_data = get_price_dexscreener(chain_key, token)
        symbol = "TOKEN"
        if price_data and price_data.get("base_token"):
            symbol = price_data["base_token"].get("symbol", "TOKEN")

        result = paper_sell(user["id"], chain_key, token, symbol, amount)
        await update.message.reply_text(
            f"✅ *Paper Sell Executed!*\n\n"
            f"{chain_info['emoji']} Chain: *{chain_info['name']}*\n"
            f"🪙 Sold: `{result['spent']:.6f} {result['spent_symbol']}`\n"
            f"💸 Received: `{result['received']:.6f} {result['received_symbol']}`\n"
            f"💵 Price: *{fmt_price(result['price'])}*\n"
            f"💰 USD Value: *${result['usd_value']:.2f}*",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Paper sell failed: {e}", parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════════════════
#  LIVE TRADE MENU
# ═══════════════════════════════════════════════════════════════════════════════

async def live_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    live_wallets = db.get_wallets(user["id"], wallet_type="live")

    if not live_wallets:
        text = (
            "💎 *Live Trading*\n\n"
            "⚠️ Live trading uses *real cryptocurrency*.\n\n"
            "You need to import a funded wallet first.\n\n"
            "Steps:\n"
            "1. Import your wallet (Wallets → Import)\n"
            "2. Fund it by sending crypto to your address\n"
            "3. Use /buy or /sell to trade\n\n"
            "💡 *Tip:* Test strategies with Paper Trading first!"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Import Wallet", callback_data="wallet:import")],
            [InlineKeyboardButton("« Back", callback_data="back:main")],
        ])
    else:
        text = (
            "💎 *Live Trading*\n\n"
            "⚠️ *REAL FUNDS — Trade carefully!*\n\n"
            "Commands:\n"
            "• `/buy [chain] [token] [amount]` — Buy token\n"
            "• `/sell [chain] [token] [amount]` — Sell token\n"
            "• `/send [chain] [to] [amount]` — Send native token\n\n"
            f"You have *{len(live_wallets)}* live wallet(s)."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Balances", callback_data="menu:balances"),
             InlineKeyboardButton("📜 History", callback_data="menu:history")],
            [InlineKeyboardButton("« Back", callback_data="back:main")],
        ])
    await send(update, text, kb, edit=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════════

async def strategies_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    active = db.get_user_strategies(user["id"])
    active_count = sum(1 for s in active if s["status"] == "active")

    text = (
        f"🤖 *Trading Strategies*\n\n"
        f"Active bots: *{active_count}*\n\n"
        f"Choose a strategy to run automatically:\n\n"
    )
    for key, s in STRATEGIES.items():
        text += f"• *{s['name']}* — {s['description'][:50]}...\n"
        text += f"  Risk: {s['risk']} | {s['best_for']}\n\n"

    rows = []
    for key, s in STRATEGIES.items():
        rows.append([InlineKeyboardButton(
            f"▶️ {s['name']}", callback_data=f"strategy_select:{key}"
        )])
    if active:
        rows.append([InlineKeyboardButton("📋 My Running Strategies", callback_data="strategy_list")])
    rows.append([InlineKeyboardButton("« Back", callback_data="back:main")])

    await send(update, text, InlineKeyboardMarkup(rows), edit=True)

async def strategy_select_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    strategy_key = update.callback_query.data.split(":")[1]
    s = STRATEGIES.get(strategy_key)
    if not s:
        return

    ctx.user_data["strategy_key"] = strategy_key
    text = (
        f"🤖 *{s['name']}*\n\n"
        f"📖 {s['description']}\n\n"
        f"⚙️ Default params:\n"
        + "\n".join(f"  • `{k}`: `{v}`" for k, v in s["params"].items()) +
        f"\n\n🔗 Select chain:"
    )
    await send(update, text, chain_keyboard("strategy_chain"), edit=True)
    return AWAIT_STRATEGY_CHAIN

async def strategy_chain_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    chain_key = update.callback_query.data.split(":")[1]
    ctx.user_data["strategy_chain"] = chain_key
    ci = CHAINS.get(chain_key, {})
    await send(update,
        f"🤖 Strategy — {ci.get('emoji','')} {ci.get('name', chain_key)}\n\n"
        f"Send the *token contract address* to trade:",
        edit=True)
    return AWAIT_STRATEGY_TOKEN

async def strategy_token_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip()
    ctx.user_data["strategy_token"] = token
    chain_key = ctx.user_data.get("strategy_chain", "ethereum")

    # Try to get symbol
    price_data = get_price_dexscreener(chain_key, token)
    symbol = "TOKEN"
    if price_data and price_data.get("base_token"):
        symbol = price_data["base_token"].get("symbol", "TOKEN")
    ctx.user_data["strategy_symbol"] = symbol

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Paper (safe)", callback_data="strategy_mode:paper"),
         InlineKeyboardButton("💎 Live (real $)", callback_data="strategy_mode:live")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ])
    await update.message.reply_text(
        f"🤖 Token: *{symbol}* (`{token[:12]}...`)\n\nChoose trading mode:",
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb
    )
    return AWAIT_STRATEGY_MODE

async def strategy_mode_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    mode = update.callback_query.data.split(":")[1]
    user = ensure_user(update)

    strategy_key = ctx.user_data.get("strategy_key")
    chain_key = ctx.user_data.get("strategy_chain")
    token = ctx.user_data.get("strategy_token")
    symbol = ctx.user_data.get("strategy_symbol", "TOKEN")
    s = STRATEGIES[strategy_key]

    # Get wallet if live mode
    wallet_id = None
    if mode == "live":
        wallet = db.get_default_wallet(user["id"], chain_key, wallet_type="live")
        if not wallet:
            await send(update,
                "❌ No live wallet for this chain.\nImport one first via Wallets → Import.",
                edit=True)
            return ConversationHandler.END
        wallet_id = wallet["id"]

    sid = db.create_strategy({
        "user_id": user["id"],
        "name": strategy_key,
        "chain": chain_key,
        "token_address": token,
        "token_symbol": symbol,
        "mode": mode,
        "wallet_id": wallet_id,
        "params": s["params"],
    })

    ci = CHAINS.get(chain_key, {})
    mode_tag = "📝 Paper" if mode == "paper" else "💎 Live"
    await send(update,
        f"✅ *Strategy Started!* \\[#{sid}\\]\n\n"
        f"🤖 *{s['name']}*\n"
        f"{ci.get('emoji','')} Chain: {ci.get('name', chain_key)}\n"
        f"🪙 Token: {symbol}\n"
        f"Mode: {mode_tag}\n\n"
        f"The bot will now monitor this token and trade automatically.\n"
        f"Use /mystrats to view running strategies.",
        edit=True)
    return ConversationHandler.END

async def my_strategies_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    strategies = db.get_user_strategies(user["id"])
    if not strategies:
        await update.message.reply_text("🤖 No strategies running. Use /start → Strategies.")
        return

    text = "🤖 *Your Strategies*\n\n"
    buttons = []
    for s in strategies:
        status_emoji = {"active": "🟢", "stopped": "🔴", "paused": "⏸"}.get(s["status"], "⚪")
        mode_tag = "📝" if s["mode"] == "paper" else "💎"
        ci = CHAINS.get(s["chain"], {})
        pnl = s.get("pnl", 0)
        pnl_str = f"+{pnl:.4f}" if pnl >= 0 else f"{pnl:.4f}"
        text += (
            f"{status_emoji}{mode_tag} *{STRATEGIES.get(s['name'], {}).get('name', s['name'])}* \\[#{s['id']}\\]\n"
            f"  {ci.get('emoji','')} {ci.get('name', s['chain'])} — {s.get('token_symbol','TOKEN')}\n"
            f"  P&L: `{pnl_str}` | Status: {s['status']}\n\n"
        )
        if s["status"] == "active":
            buttons.append([InlineKeyboardButton(f"⏹ Stop #{s['id']}", callback_data=f"stop_strategy:{s['id']}")])

    buttons.append([InlineKeyboardButton("« Back", callback_data="back:main")])
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=InlineKeyboardMarkup(buttons))

async def stop_strategy_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split(":")[1])
    user = ensure_user(update)
    db.stop_strategy(sid, user["id"])
    await update.callback_query.edit_message_text(
        f"⏹ Strategy \\#{sid} stopped.", parse_mode=ParseMode.MARKDOWN
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  DCA BOTS
# ═══════════════════════════════════════════════════════════════════════════════

async def dca_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    orders = db.get_user_dca(user["id"])
    active = [o for o in orders if o["status"] == "active"]

    text = (
        f"📊 *DCA Bot Manager*\n\n"
        f"Active orders: *{len(active)}*\n\n"
        f"Dollar Cost Averaging automatically buys at regular intervals.\n\n"
        f"Usage:\n"
        f"`/newdca [chain] [token] [amount] [freq_minutes]`\n\n"
        f"Examples:\n"
        f"`/newdca ethereum 0xUSDC 0.01 1440` — Daily\n"
        f"`/newdca bsc 0xCAKE 0.05 60` — Hourly\n\n"
        f"Frequency presets: 60=hourly 1440=daily 10080=weekly"
    )
    buttons = [[InlineKeyboardButton("📋 My DCA Orders", callback_data="dca_list")],
               [InlineKeyboardButton("« Back", callback_data="back:main")]]
    await send(update, text, InlineKeyboardMarkup(buttons), edit=True)

async def dca_list_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user = ensure_user(update)
    orders = db.get_user_dca(user["id"])
    if not orders:
        await send(update, "📊 No DCA orders. Use `/newdca` to create one.", edit=True)
        return

    text = "📊 *Your DCA Orders*\n\n"
    buttons = []
    for o in orders:
        ci = CHAINS.get(o["chain"], {})
        status_emoji = {"active": "🟢", "cancelled": "🔴", "completed": "✅"}.get(o["status"], "⚪")
        prog = f"{o['done_orders']}/{o['total_orders']}" if o["total_orders"] > 0 else f"{o['done_orders']}/∞"
        freq_str = _fmt_freq(o["freq_minutes"])
        text += (
            f"{status_emoji} *Order \\#{o['id']}* — {ci.get('emoji','')} {ci.get('name', o['chain'])}\n"
            f"  {o.get('symbol_in','?')} → {o.get('symbol_out','?')} | {o['amount_per_order']} per {freq_str}\n"
            f"  Progress: {prog}\n\n"
        )
        if o["status"] == "active":
            buttons.append([InlineKeyboardButton(f"❌ Cancel #{o['id']}", callback_data=f"cancel_dca:{o['id']}")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="menu:dca")])
    await send(update, text, InlineKeyboardMarkup(buttons), edit=True)

async def cancel_dca_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    oid = int(update.callback_query.data.split(":")[1])
    user = ensure_user(update)
    db.cancel_dca(oid, user["id"])
    await update.callback_query.edit_message_text(f"🔴 DCA Order \\#{oid} cancelled.",
                                                   parse_mode=ParseMode.MARKDOWN)

async def newdca_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 4:
        await update.message.reply_text(
            "📊 *New DCA Order*\n\n"
            "Usage: `/newdca [chain] [token] [amount] [freq_min] [total_orders?]`\n\n"
            "Examples:\n"
            "`/newdca ethereum 0xUSDC 0.01 1440` — Buy daily forever\n"
            "`/newdca bsc 0xCAKE 0.05 60 48` — Buy hourly 48 times",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    chain_key = args[0].lower()
    token = args[1]
    try:
        amount = float(args[2])
        freq = int(args[3])
        total = int(args[4]) if len(args) > 4 else 0
    except ValueError:
        await update.message.reply_text("❌ Invalid amount or frequency."); return

    _, chain_info = get_chain(chain_key)
    if not chain_info:
        await update.message.reply_text(f"❌ Unknown chain: {chain_key}"); return

    user = ensure_user(update)

    # Try to resolve symbol
    symbol = "TOKEN"
    try:
        pd = get_price_dexscreener(chain_key, token)
        if pd and pd.get("base_token"):
            symbol = pd["base_token"].get("symbol", "TOKEN")
    except Exception:
        pass

    oid = db.create_dca({
        "user_id": user["id"],
        "chain": chain_key,
        "mode": "paper",
        "token_in": "native",
        "token_out": token,
        "symbol_in": chain_info["symbol"],
        "symbol_out": symbol,
        "amount_per_order": amount,
        "freq_minutes": freq,
        "total_orders": total,
    })

    await update.message.reply_text(
        f"✅ *DCA Order Created \\#{oid}!*\n\n"
        f"{chain_info['emoji']} {chain_info['name']}: {chain_info['symbol']} → {symbol}\n"
        f"💰 Amount: `{amount} {chain_info['symbol']}` per order\n"
        f"⏱ Frequency: every {_fmt_freq(freq)}\n"
        f"📊 Total orders: {'unlimited' if total == 0 else total}\n\n"
        f"_Use /dcalist to manage orders_",
        parse_mode=ParseMode.MARKDOWN
    )

def _fmt_freq(minutes: int) -> str:
    if minutes < 60: return f"{minutes}min"
    if minutes < 1440: return f"{minutes//60}h"
    if minutes < 10080: return f"{minutes//1440}d"
    return f"{minutes//10080}w"

# ═══════════════════════════════════════════════════════════════════════════════
#  PRICES
# ═══════════════════════════════════════════════════════════════════════════════

async def prices_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send(update, "⏳ Fetching prices...", edit=True)
    prices = get_native_prices()

    tokens = [
        ("ethereum", "⟠", "ETH"), ("binancecoin", "🔶", "BNB"),
        ("matic-network", "🟣", "MATIC"), ("avalanche-2", "🔺", "AVAX"),
        ("solana", "◎", "SOL"),
    ]
    text = "💵 *Live Prices*\n\n"
    for cg_id, emoji, sym in tokens:
        d = prices.get(cg_id)
        if d:
            text += f"{emoji} *{sym}:* {fmt_price(d['usd'])} {fmt_change(d.get('usd_24h_change'))}\n"

    text += "\n_Use `/price [symbol]` or `/price [chain] [address]` for any token_"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="back:main")]])
    await send(update, text, kb, edit=True)

async def price_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Usage:\n`/price [symbol]` — e.g. `/price ethereum`\n"
            "`/price [chain] [address]` — e.g. `/price ethereum 0xToken`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await update.message.reply_text("⏳ Fetching...")

    if len(args) >= 2 and args[0].lower() in CHAINS:
        chain_key, token = args[0].lower(), args[1]
        pd = get_price_dexscreener(chain_key, token)
        if not pd:
            await update.message.reply_text("❌ No price data found for that token.")
            return
        ci = CHAINS[chain_key]
        text = (
            f"💵 *Token Price*\n\n"
            f"{ci['emoji']} Chain: *{ci['name']}*\n"
            f"📍 `{token[:12]}...`\n\n"
            f"💵 Price: *{fmt_price(pd['price'])}*\n"
            f"📊 24h: {fmt_change(pd.get('change24h'))}\n"
        )
        if pd.get("volume24h"):
            text += f"📦 Vol: ${pd['volume24h']:,.0f}\n"
        if pd.get("liquidity"):
            text += f"💧 Liq: ${pd['liquidity']:,.0f}\n"
        if pd.get("dex"):
            text += f"🔀 DEX: {pd['dex']}\n"
    else:
        query = " ".join(args)
        results = search_token(query)
        if not results:
            await update.message.reply_text(f"❌ Token '{query}' not found.")
            return
        coin = results[0]
        pd = get_price_coingecko(coin["id"])
        if not pd:
            await update.message.reply_text(f"❌ Price unavailable for {coin['name']}")
            return
        text = (
            f"💵 *{coin['name']} ({coin['symbol'].upper()})*\n\n"
            f"Price: *{fmt_price(pd['price'])}*\n"
            f"24h: {fmt_change(pd.get('change24h'))}\n"
            f"_Source: CoinGecko_"
        )

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ═══════════════════════════════════════════════════════════════════════════════
#  ALERTS
# ═══════════════════════════════════════════════════════════════════════════════

async def alerts_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    alerts = db.get_user_alerts(user["id"])
    active = [a for a in alerts if a["status"] == "active"]

    text = (
        f"🔔 *Price Alerts*\n\n"
        f"Active alerts: *{len(active)}*\n\n"
        f"Usage: `/alert [chain] [token] [above|below] [price]`\n\n"
        f"Examples:\n"
        f"`/alert ethereum native above 5000`\n"
        f"`/alert solana TokenMint below 0.001`"
    )
    buttons = []
    for a in active:
        ci = CHAINS.get(a["chain"], {})
        cond = "📈 >" if a["condition"] == "above" else "📉 <"
        buttons.append([InlineKeyboardButton(
            f"❌ {a.get('token_symbol','?')} {cond} ${a['target_price']} #{a['id']}",
            callback_data=f"cancel_alert:{a['id']}"
        )])
    buttons.append([InlineKeyboardButton("« Back", callback_data="back:main")])
    await send(update, text, InlineKeyboardMarkup(buttons), edit=True)

async def alert_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 4:
        await update.message.reply_text(
            "🔔 *Set Price Alert*\n\nUsage: `/alert [chain] [token] [above|below] [price]`\n\n"
            "Examples:\n"
            "`/alert ethereum native above 5000`\n"
            "`/alert bsc 0xCAKE below 0.5`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    chain_key = args[0].lower()
    token = args[1]
    condition = args[2].lower()
    try:
        target = float(args[3])
    except ValueError:
        await update.message.reply_text("❌ Invalid price."); return

    if condition not in ("above", "below"):
        await update.message.reply_text("❌ Condition must be `above` or `below`",
                                        parse_mode=ParseMode.MARKDOWN); return

    _, chain_info = get_chain(chain_key)
    if not chain_info:
        await update.message.reply_text(f"❌ Unknown chain: {chain_key}"); return

    NATIVE_ADDR = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
    token_addr = NATIVE_ADDR if token.lower() == "native" else token
    symbol = chain_info["symbol"] if token.lower() == "native" else token[:8]

    user = ensure_user(update)
    aid = db.create_alert({
        "user_id": user["id"],
        "chain": chain_key,
        "token_address": token_addr,
        "token_symbol": symbol,
        "condition": condition,
        "target_price": target,
    })

    cond_str = f"rises above" if condition == "above" else "falls below"
    await update.message.reply_text(
        f"🔔 *Alert Set \\#{aid}!*\n\n"
        f"{chain_info['emoji']} {chain_info['name']} — *{symbol}*\n"
        f"Alert when price {cond_str} *{fmt_price(target)}*\n\n"
        f"_Checks every 2 minutes. Use /alerts to manage._",
        parse_mode=ParseMode.MARKDOWN
    )

async def cancel_alert_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    aid = int(update.callback_query.data.split(":")[1])
    user = ensure_user(update)
    db.cancel_alert(aid, user["id"])
    await update.callback_query.edit_message_text(
        f"🔕 Alert \\#{aid} cancelled.", parse_mode=ParseMode.MARKDOWN
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  TRADE HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

async def history_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    trades = db.get_trades(user["id"], limit=15)

    if not trades:
        await send(update, "📜 No trades yet. Start with Paper Trading!", edit=True)
        return

    text = "📜 *Recent Trades*\n\n"
    for t in trades:
        ci = CHAINS.get(t["chain"], {})
        type_emoji = {"buy": "📈", "sell": "📉", "swap": "💱", "dca": "🤖"}.get(t["trade_type"], "💱")
        mode_tag = "📝" if t["mode"] == "paper" else "💎"
        status_emoji = "✅" if t["status"] == "success" else "❌"
        date = t["created_at"][:10]
        text += (
            f"{type_emoji}{mode_tag} *{t['trade_type'].upper()}* — {ci.get('emoji','')} {ci.get('name', t['chain'])}\n"
            f"  {t.get('symbol_in','?')} → {t.get('symbol_out','?')}\n"
            f"  In: `{t.get('amount_in',0):.6f}` | Out: `{t.get('amount_out',0):.6f}` | {status_emoji} {date}\n\n"
        )

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="back:main")]])
    await send(update, text, kb, edit=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  HELP
# ═══════════════════════════════════════════════════════════════════════════════

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ *Help & Commands*\n\n"
        "*💼 WALLETS*\n"
        "`/start` — Main menu\n\n"
        "*📝 PAPER TRADING*\n"
        "`/pbuy [chain] [token] [amount]`\n"
        "`/psell [chain] [token] [amount]`\n"
        "`/portfolio` — View paper portfolio\n"
        "`/topup` — Add paper funds\n\n"
        "*🤖 STRATEGIES (auto-trading)*\n"
        "`/mystrats` — View running strategies\n"
        "_Set up via menu → Strategies_\n\n"
        "*📊 DCA BOTS*\n"
        "`/newdca [chain] [token] [amount] [min]`\n"
        "`/dcalist` — View DCA orders\n\n"
        "*💵 PRICES*\n"
        "`/price [symbol]` — Any token price\n"
        "`/price [chain] [address]` — By contract\n\n"
        "*🔔 ALERTS*\n"
        "`/alert [chain] [token] [above|below] [price]`\n"
        "`/alerts` — Manage alerts\n\n"
        "*CHAINS:* ethereum bsc polygon arbitrum base avalanche solana\n\n"
        "_Use `native` as token for ETH/BNB/SOL etc_"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="back:main")]])
    await send(update, text, kb, edit=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  BACKGROUND: Strategy & DCA runner + Alert monitor
# ═══════════════════════════════════════════════════════════════════════════════

async def run_background_tasks(app: Application):
    """Runs in a background thread — processes strategies, DCA, and alerts."""
    while True:
        try:
            await _process_strategies(app)
            await _process_dca(app)
            await _process_alerts(app)
        except Exception as e:
            print(f"[Background] Error: {e}")
        await asyncio.sleep(60)  # Check every minute

async def _process_strategies(app: Application):
    """Check all active strategies and execute trades if signal fires."""
    strategies = db.get_active_strategies()
    for s in strategies:
        try:
            params = json.loads(s.get("params") or "{}")
            signal = get_signal(s["name"], s["chain"], s["token_address"], params)

            if signal["signal"] == "hold":
                continue

            trade_amount = params.get("trade_amount", 0.01)
            user_id = s["user_id"]
            ci = CHAINS.get(s["chain"], {})

            if s["mode"] == "paper":
                if signal["signal"] == "buy":
                    try:
                        result = paper_buy(user_id, s["chain"], s["token_address"],
                                           s.get("token_symbol", "TOKEN"), trade_amount)
                        pnl_delta = 0
                    except Exception as e:
                        result = None

                elif signal["signal"] == "sell":
                    balance = db.get_paper_balance(user_id, s.get("token_symbol","TOKEN"), s["chain"])
                    if balance <= 0:
                        continue
                    try:
                        result = paper_sell(user_id, s["chain"], s["token_address"],
                                            s.get("token_symbol","TOKEN"), balance * 0.5)
                    except Exception:
                        continue

            # Notify user
            msg = format_signal_message(s["name"], signal, s.get("token_symbol","TOKEN"),
                                        s["chain"], s["mode"])
            try:
                await app.bot.send_message(
                    chat_id=s["tg_id"], text=msg, parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

        except Exception as e:
            print(f"[Strategy] Error for strategy {s['id']}: {e}")

async def _process_dca(app: Application):
    orders = db.get_due_dca_orders()
    for o in orders:
        try:
            from datetime import datetime, timedelta
            next_run = (datetime.utcnow() + timedelta(minutes=o["freq_minutes"])).isoformat()
            done = o["done_orders"] + 1
            is_complete = o["total_orders"] > 0 and done >= o["total_orders"]

            if o["mode"] == "paper":
                # Paper DCA execution
                try:
                    result = paper_buy(
                        o["user_id"], o["chain"], o["token_out"],
                        o.get("symbol_out", "TOKEN"), o["amount_per_order"]
                    )
                    status_msg = (
                        f"🤖 *DCA Executed \\#{o['id']}*\n\n"
                        f"Bought `{result['received']:.6f}` {result['received_symbol']}\n"
                        f"Spent `{result['spent']} {result['spent_symbol']}`\n"
                        f"Progress: {done}/{o['total_orders'] if o['total_orders'] > 0 else '∞'}"
                    )
                    if is_complete:
                        status_msg += "\n\n🎉 DCA order completed!"
                except Exception as e:
                    status_msg = f"❌ DCA \\#{o['id']} failed: {e}"

            db.update_dca(o["id"],
                          done_orders=done,
                          next_run=next_run,
                          status="completed" if is_complete else "active")
            try:
                await app.bot.send_message(chat_id=o["tg_id"], text=status_msg,
                                           parse_mode=ParseMode.MARKDOWN)
            except Exception:
                pass
        except Exception as e:
            print(f"[DCA] Error for order {o['id']}: {e}")

async def _process_alerts(app: Application):
    alerts = db.get_active_alerts()
    for a in alerts:
        try:
            if a["chain"] == "solana":
                pd = get_price_dexscreener("solana", a["token_address"])
            else:
                cg_id = CHAINS.get(a["chain"], {}).get("coingecko_id")
                native_addr = CHAINS.get(a["chain"], {}).get("native", "")
                if a["token_address"].lower() == native_addr.lower() and cg_id:
                    pd = get_price_coingecko(cg_id)
                else:
                    pd = get_price_dexscreener(a["chain"], a["token_address"])

            if not pd or not pd.get("price"):
                continue

            price = pd["price"]
            triggered = (
                (a["condition"] == "above" and price >= a["target_price"]) or
                (a["condition"] == "below" and price <= a["target_price"])
            )
            if triggered:
                db.trigger_alert(a["id"])
                cond_str = "risen above" if a["condition"] == "above" else "fallen below"
                await app.bot.send_message(
                    chat_id=a["tg_id"],
                    text=(
                        f"🔔 *Price Alert Triggered!*\n\n"
                        f"*{a.get('token_symbol','Token')}* has {cond_str} "
                        f"*{fmt_price(a['target_price'])}*\n"
                        f"Current price: *{fmt_price(price)}*"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
#  HEALTH CHECK SERVER — keeps Railway/Render happy
# ═══════════════════════════════════════════════════════════════════════════════

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","bot":"CryptoBot","running":true}')

    def log_message(self, format, *args):
        pass  # Silence access logs

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"✅ Health check server running on port {port}")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ ERROR: Add your bot token to config/secrets.py")
        print("   Or set the BOT_TOKEN environment variable")
        print("   Get one from @BotFather on Telegram → /newbot")
        sys.exit(1)

    # Start health check server (required for Railway/Render)
    start_health_server()

    db.init_db()
    print("✅ Database initialised")

    app = Application.builder().token(BOT_TOKEN).build()

    # Wallet import conversation
    import_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(import_chain_callback, pattern="^import_chain:")],
        states={AWAIT_IMPORT_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, import_key_received)]},
        fallbacks=[CallbackQueryHandler(cancel_callback, pattern="^cancel$")],
        per_message=False,
    )

    # Top-up conversation
    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_start, pattern="^topup:start$")],
        states={
            AWAIT_TOPUP_CHAIN:  [CallbackQueryHandler(topup_chain_selected, pattern="^topup_chain:")],
            AWAIT_TOPUP_ASSET:  [CallbackQueryHandler(topup_asset_selected, pattern="^topup_asset:")],
            AWAIT_TOPUP_AMOUNT: [
                CallbackQueryHandler(topup_amount_selected, pattern="^topup_amt:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, topup_custom_received),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_callback, pattern="^cancel$")],
        per_message=False,
    )

    # Strategy setup conversation
    strategy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(strategy_select_callback, pattern="^strategy_select:")],
        states={
            AWAIT_STRATEGY_CHAIN: [CallbackQueryHandler(strategy_chain_callback, pattern="^strategy_chain:")],
            AWAIT_STRATEGY_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, strategy_token_received)],
            AWAIT_STRATEGY_MODE:  [CallbackQueryHandler(strategy_mode_callback, pattern="^strategy_mode:")],
        },
        fallbacks=[CallbackQueryHandler(cancel_callback, pattern="^cancel$")],
        per_message=False,
    )

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("alert", alert_cmd))
    app.add_handler(CommandHandler("alerts", lambda u, c: alerts_menu(u, c)))
    app.add_handler(CommandHandler("pbuy", pbuy_cmd))
    app.add_handler(CommandHandler("psell", psell_cmd))
    app.add_handler(CommandHandler("portfolio", lambda u, c: (
        ensure_user(u),
        asyncio.ensure_future(u.message.reply_text(
            "📊 Use /start → Paper Trade → Portfolio", parse_mode=ParseMode.MARKDOWN
        ))
    )))
    app.add_handler(CommandHandler("newdca", newdca_cmd))
    app.add_handler(CommandHandler("dcalist", lambda u, c: dca_menu(u, c)))
    app.add_handler(CommandHandler("mystrats", my_strategies_cmd))

    app.add_handler(import_conv)
    app.add_handler(topup_conv)
    app.add_handler(strategy_conv)

    app.add_handler(CallbackQueryHandler(start, pattern="^back:main$"))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu:"))
    app.add_handler(CallbackQueryHandler(wallet_callback, pattern="^wallet:"))
    app.add_handler(CallbackQueryHandler(gen_wallet_callback, pattern="^gen_wallet:"))
    app.add_handler(CallbackQueryHandler(paper_trade_callback, pattern="^ptrade:"))
    app.add_handler(CallbackQueryHandler(fund_start, pattern="^fund:start$"))
    app.add_handler(CallbackQueryHandler(dca_list_callback, pattern="^dca_list$"))
    app.add_handler(CallbackQueryHandler(cancel_dca_callback, pattern="^cancel_dca:"))
    app.add_handler(CallbackQueryHandler(cancel_alert_callback, pattern="^cancel_alert:"))
    app.add_handler(CallbackQueryHandler(stop_strategy_callback, pattern="^stop_strategy:"))
    app.add_handler(CallbackQueryHandler(strategy_select_callback, pattern="^strategy_select:"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel$"))

    # Start background task loop
    async def post_init(application: Application):
        asyncio.create_task(run_background_tasks(application))

    app.post_init = post_init

    print("🚀 Bot is running! Open Telegram and send /start")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

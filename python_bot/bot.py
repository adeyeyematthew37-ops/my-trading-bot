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
    get_price_dexscreener, search_token, fmt_price, fmt_change,
    get_token_full_info, rug_check, fmt_mcap, get_chart_url
)
from wallet.generator import (
    generate_evm_wallet, generate_solana_wallet,
    import_wallet, short_addr
)
from wallet.balances import get_native_balance, get_solana_balance
from trading.paper_trade import (
    paper_buy, paper_sell, get_paper_portfolio, get_unrealized_pnl
)
from strategies.engine import (
    STRATEGIES, get_signal, format_signal_message,
    format_strategy_description, get_editable_params,
    on_trade_executed
)
from strategies.learning import (
    get_strategy_stats, get_weekly_report,
    get_learning_log, record_trade_outcome
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
    AWAIT_PARAM_VALUE,
) = range(26)

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
        [InlineKeyboardButton("📊 Perp Trading", callback_data="menu:perp")],
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
        f"🔵 Arbitrum  🔷 Base  🔺 Avalanche  ◎ Solana\n"
        f"Ⓝ NEAR Protocol  🔥 HOT Chain\n\n"
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
    elif action == "perp":
        from bot.perp_handlers import perp_menu as _perp_menu
        await _perp_menu(update, ctx)

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
    native_sym = chain_info["symbol"]
    current = db.get_paper_balance(user["id"], native_sym, chain_key)
    if current == 0:
        db.set_paper_balance(user["id"], native_sym, chain_key, 1.0)

    is_solana = chain_info["type"] == "solana"
    mnemonic = w.get("mnemonic", "")

    if is_solana and mnemonic:
        seed_section = (
            f"\n\n"
            f"🔑 *Your 12-Word Seed Phrase:*\n"
            f"`{mnemonic}`\n\n"
            f"📲 *Import into Phantom:*\n"
            f"1\\. Open Phantom → tap the menu ☰\n"
            f"2\\. Add/Connect Wallet\n"
            f"3\\. Import Secret Recovery Phrase\n"
            f"4\\. Enter the 12 words above ✅"
        )
    elif mnemonic:
        seed_section = (
            f"\n\n"
            f"🔑 *Seed Phrase \\(save this\\!\\):*\n"
            f"`{mnemonic}`\n\n"
            f"📲 Import into MetaMask or Trust Wallet using these words"
        )
    else:
        seed_section = ""

    text = (
        f"✅ *New {chain_info['emoji']} {chain_info['name']} Wallet Generated\\!*\n\n"
        f"📍 *Address:*\n`{w['address']}`"
        f"{seed_section}\n\n"
        f"{'━' * 22}\n"
        f"⚠️ *SECURITY — READ THIS:*\n"
        f"• Screenshot or write down the seed phrase\n"
        f"• Store it offline — never in screenshots or cloud\n"
        f"• Anyone with these words controls your wallet\n"
        f"• This message will NOT be shown again\n"
        f"{'━' * 22}\n\n"
        f"📝 Started with *1 {native_sym}* paper balance\\.\n"
        f"Use the menu to top up or start trading\\!"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Wallets", callback_data="menu:wallets")]])
    await send(update, text, kb, edit=True)

async def import_chain_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    chain_key = update.callback_query.data.split(":")[1]
    ctx.user_data["import_chain"] = chain_key
    chain_info = CHAINS.get(chain_key, {})
    is_solana = chain_info.get("type") == "solana"

    if is_solana:
        instructions = (
            f"📥 *Import {chain_info.get('emoji','')} Solana Wallet*\n\n"
            f"Send any of these formats — the bot auto-detects:\n\n"
            f"*Option A — Seed Phrase \\(recommended\\)*\n"
            f"Your 12 or 24 words separated by spaces\n"
            f"_Works with Phantom, Solflare, Backpack_\n\n"
            f"*Option B — Private Key \\(base58\\)*\n"
            f"The long string Phantom exports\n"
            f"_Phantom: Settings → Security → Export Private Key_\n\n"
            f"*Option C — Byte Array*\n"
            f"Format: \\[1,2,3,4,\\.\\.\\.\\]\n"
            f"_Used by some developer wallets_\n\n"
            f"{'━'*22}\n"
            f"⚠️ Send your key now\\. "
            f"The bot will *immediately delete* your message\\."
        )
    else:
        instructions = (
            f"📥 *Import {chain_info.get('emoji','')} {chain_info.get('name',chain_key)} Wallet*\n\n"
            f"Send any of these formats:\n\n"
            f"*Option A — Private Key*\n"
            f"64-character hex string \\(with or without 0x\\)\n"
            f"_MetaMask: Account → Export Private Key_\n\n"
            f"*Option B — Seed Phrase*\n"
            f"Your 12 or 24 recovery words\n"
            f"_MetaMask: Settings → Security → Reveal Phrase_\n\n"
            f"{'━'*22}\n"
            f"⚠️ Send your key now\\. "
            f"The bot will *immediately delete* your message\\."
        )

    await send(update, instructions, edit=True)
    return AWAIT_IMPORT_KEY

async def import_key_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = ensure_user(update)
    chain_key = ctx.user_data.get("import_chain", "ethereum")
    key_input = update.message.text.strip()
    chain_info = CHAINS.get(chain_key, {})

    # Delete user message immediately for security
    try:
        await update.message.delete()
    except Exception:
        pass

    await update.message.reply_text("⏳ Importing wallet...")

    try:
        w = import_wallet(key_input, chain_info.get("type", "evm"))
        enc_key = encrypt(w["private_key"])
        db.save_wallet(
            user["id"], chain_key, w["address"], enc_key,
            label=f"Imported {chain_info.get('name', chain_key)}",
            wallet_type="live"
        )

        # Show address and fund instructions
        explorer_url = f"{chain_info.get('explorer','')}/address/{w['address']}"
        mnemonic_note = ""
        if w.get("mnemonic"):
            mnemonic_note = (
                f"\n\n🔑 *Seed Phrase detected & saved*\n"
                f"Your wallet was recovered from the seed phrase\\."
            )

        text = (
            f"✅ *Wallet Imported as LIVE Wallet\\!*\n\n"
            f"{chain_info.get('emoji','')} *Chain:* {chain_info.get('name', chain_key)}\n"
            f"📍 *Address:*\n`{w['address']}`"
            f"{mnemonic_note}\n\n"
            f"{'━'*22}\n"
            f"💎 *This is a LIVE wallet*\n"
            f"Trades will use real funds on chain\\.\n\n"
            f"*To fund it:* Send {chain_info.get('symbol','crypto')} to the address above\n"
            f"*Check balance:* Menu → Balances\n"
            f"*Start trading:* Menu → Live Trade\n"
            f"{'━'*22}\n\n"
            f"⚠️ Your previous message was deleted for security\\."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Check Balance", callback_data="menu:balances")],
            [InlineKeyboardButton("💎 Start Live Trading", callback_data="menu:live")],
            [InlineKeyboardButton("« Main Menu", callback_data="back:main")],
        ])
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                        reply_markup=kb)

    except ValueError as e:
        await update.message.reply_text(
            f"❌ *Import Failed*\n\n{e}\n\n"
            f"Try again via Menu → Wallets → Import",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ *Unexpected error:* `{e}`\n\nPlease try again\\.",
            parse_mode=ParseMode.MARKDOWN
        )

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
                ci  = CHAINS.get(item["chain"], {})
                bal = item["balance"]
                if item.get("usd_value", 0) > 0:
                    usd_str = f" \\(≈${item['usd_value']:.2f}\\)"
                elif not item.get("has_price", True):
                    usd_str = " \\(price N/A\\)"
                else:
                    usd_str = ""
                text += f"{ci.get('emoji','🔗')} *{item['symbol']}*: `{bal:.6f}`{usd_str}\n"
            # Unrealized PnL from open positions
            upnl = portfolio.get("unrealized_pnl", 0)
            upnl_str = ""
            if upnl != 0:
                sign = "+" if upnl >= 0 else ""
                upnl_str = f"\n📂 Unrealized P&L: `{sign}{upnl:.4f}`"
            text += f"\n💵 *Total: ${portfolio['total_usd']:.2f}*{upnl_str}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="menu:paper")]])
        await send(update, text, kb, edit=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  /pbuy and /psell commands
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
#  TOKEN PANEL — Fluxbot-style trade interface
# ═══════════════════════════════════════════════════════════════════════════════

def _token_panel_keyboard(chain: str, token: str, mode: str = "paper") -> InlineKeyboardMarkup:
    """Build the Fluxbot-style trade panel keyboard."""
    chart_url = get_chart_url(chain, token)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📈 Chart",    url=chart_url),
            InlineKeyboardButton("🕵️ RugCheck", callback_data=f"rugcheck:{chain}:{token}"),
            InlineKeyboardButton("❌ Close",    callback_data="back:main"),
        ],
        [InlineKeyboardButton(f"⇅ ── SWAP MODE ── ⇅", callback_data="noop")],
        [
            InlineKeyboardButton("🟢 Buy",  callback_data=f"tp_buy:{chain}:{token}:{mode}"),
            InlineKeyboardButton("⚫ Sell", callback_data=f"tp_sell:{chain}:{token}:{mode}"),
        ],
        [InlineKeyboardButton("💵 ── AMOUNT ── 💵", callback_data="noop")],
        [
            InlineKeyboardButton("0.1",    callback_data=f"tp_amt:{chain}:{token}:{mode}:buy:0.1"),
            InlineKeyboardButton("0.5",    callback_data=f"tp_amt:{chain}:{token}:{mode}:buy:0.5"),
            InlineKeyboardButton("1",      callback_data=f"tp_amt:{chain}:{token}:{mode}:buy:1"),
        ],
        [
            InlineKeyboardButton("5",      callback_data=f"tp_amt:{chain}:{token}:{mode}:buy:5"),
            InlineKeyboardButton("10",     callback_data=f"tp_amt:{chain}:{token}:{mode}:buy:10"),
            InlineKeyboardButton("Custom", callback_data=f"tp_custom:{chain}:{token}:{mode}:buy"),
        ],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"tp_refresh:{chain}:{token}:{mode}")],
    ])


async def _build_token_panel_text(chain: str, token: str, user_id: int, mode: str = "paper") -> str:
    """Build the Fluxbot-style token info panel text."""
    ci = CHAINS.get(chain, {})
    info = get_token_full_info(chain, token)

    if not info:
        return (
            f"{'━'*28}\n"
            f"{ci.get('emoji','')} *Token Panel*\n"
            f"Chain: {ci.get('name', chain)}\n"
            f"Contract: `{token[:12]}\\.\\.\\. `\n\n"
            f"⚠️ Could not fetch token data\\. Check contract address\\."
        )

    sym      = info["base_symbol"]
    name     = info["base_name"]
    price    = info["price"]
    mcap     = info["mcap"]
    vol24    = info["volume24h"]
    liq      = info["liquidity"]
    ch5m     = info["change5m"]
    ch1h     = info["change1h"]
    ch24     = info["change24h"]
    buys     = info["buys24h"]
    sells    = info["sells24h"]
    dex      = info["dex"]
    age_h    = info["age_hours"]

    # Age display
    if age_h is not None:
        if age_h < 1:    age_str = f"{age_h*60:.0f}m old"
        elif age_h < 24: age_str = f"{age_h:.1f}h old"
        else:            age_str = f"{age_h/24:.1f}d old"
    else:
        age_str = "age unknown"

    # Buy/sell pressure
    total_txns = buys + sells
    if total_txns > 0:
        buy_pct = buys / total_txns * 100
        pressure = f"🟢 {buy_pct:.0f}% buys" if buy_pct > 55 else f"🔴 {100-buy_pct:.0f}% sells"
    else:
        pressure = "No txns"

    # Paper balance check
    bal = db.get_paper_balance(user_id, sym.upper(), chain)
    bal_usd = bal * price if price > 0 else 0

    mode_tag = "📝 Paper" if mode == "paper" else "💎 Live"

    # Unrealized PnL for this token
    positions = db.get_open_positions(user_id)
    token_pos = [p for p in positions if p["token_address"].lower() == token.lower()]
    pnl_line = ""
    if token_pos:
        pos = token_pos[0]
        if pos["entry_price_usd"] > 0:
            pnl_pct = ((price - pos["entry_price_usd"]) / pos["entry_price_usd"]) * 100
            pnl_usd = (price - pos["entry_price_usd"]) * pos["qty"]
            pnl_e   = "✅" if pnl_usd >= 0 else "❌"
            pnl_line = (
                f"\n{pnl_e} *Unrealized P&L:* "
                f"`{'+'if pnl_usd>=0 else ''}{pnl_usd:.4f}` "
                f"\\({'+' if pnl_pct>=0 else ''}{pnl_pct:.2f}%\\)"
            )

    text = (
        f"{'━'*28}\n"
        f"{ci.get('emoji','')} *{name}* \\| {sym} \\| {mode_tag}\n\n"
        f"💵 *Price:* `{fmt_price(price)}`\n"
        f"📊 *MCap:* `{fmt_mcap(mcap)}`\n"
        f"📦 *Vol 24h:* `{fmt_mcap(vol24)}`\n"
        f"💧 *Liquidity:* `{fmt_mcap(liq)}`\n"
        f"🔀 *DEX:* {dex} \\| _{age_str}_\n\n"
        f"📈 *Price Change:*\n"
        f"  5m: `{'+'if ch5m>=0 else ''}{ch5m:.2f}%` \\| "
        f"1h: `{'+'if ch1h>=0 else ''}{ch1h:.2f}%` \\| "
        f"24h: `{'+'if ch24>=0 else ''}{ch24:.2f}%`\n\n"
        f"💱 *Txns:* {buys} buys / {sells} sells — {pressure}\n\n"
        f"👛 *Your Balance:* `{bal:.6f} {sym}` \\(≈${bal_usd:.4f}\\)"
        f"{pnl_line}\n"
        f"{'━'*28}"
    )
    return text



async def rugcheck_standalone_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/rugcheck [chain] [address] — Run a rug pull risk check on any token."""
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "🕵️ *Rug Check*\n\nUsage: `/rugcheck [chain] [address]`\n\n"
            "Example: `/rugcheck solana TokenMintAddress`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    chain_key, token = args[0].lower(), args[1]
    await update.message.reply_text("⏳ Running rug check...")
    result = rug_check(chain_key, token)
    ci     = CHAINS.get(chain_key, {})
    lines  = [
        f"🕵️ *Rug Check — {ci.get('name', chain_key)}*",
        f"📍 `{token[:20]}...`",
        f"",
        f"*Risk Score: {result['score']}*",
        f"",
    ]
    for w in result["warnings"]:
        lines.append(f"  {w}")
    info = result.get("info", {})
    if info:
        lines += [
            f"",
            f"💧 Liquidity: `{fmt_mcap(info.get('liquidity',0))}`",
            f"📊 MCap: `{fmt_mcap(info.get('mcap',0))}`",
            f"📦 Vol 24h: `{fmt_mcap(info.get('volume24h',0))}`",
        ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def token_panel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/token [chain] [address] — Open the Fluxbot-style trade panel."""
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "📊 *Token Panel*\n\n"
            "Usage: `/token [chain] [address]`\n\n"
            "Example:\n"
            "`/token solana TokenMintAddress`\n"
            "`/token ethereum 0xTokenAddress`\n\n"
            "Opens the full trade panel with chart, rug check, buy/sell buttons\\.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    chain_key = args[0].lower()
    token     = args[1]
    _, ci     = get_chain(chain_key)
    if not ci:
        await update.message.reply_text(f"❌ Unknown chain: `{chain_key}`", parse_mode=ParseMode.MARKDOWN)
        return

    user = ensure_user(update)
    msg  = await update.message.reply_text("⏳ Loading token data\\.\\.\\.", parse_mode=ParseMode.MARKDOWN)

    text = await _build_token_panel_text(chain_key, token, user["id"], "paper")
    kb   = _token_panel_keyboard(chain_key, token, "paper")

    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def tp_refresh_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Refresh the token panel with latest data."""
    await update.callback_query.answer("Refreshing...")
    parts = update.callback_query.data.split(":")
    chain, token, mode = parts[1], parts[2], parts[3]
    user  = ensure_user(update)
    text  = await _build_token_panel_text(chain, token, user["id"], mode)
    kb    = _token_panel_keyboard(chain, token, mode)
    try:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    except Exception:
        pass  # Telegram throws if content unchanged


async def rugcheck_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Run rug check on a token and display results."""
    await update.callback_query.answer("Checking...")
    parts = update.callback_query.data.split(":")
    chain, token = parts[1], parts[2]
    ci = CHAINS.get(chain, {})

    result = rug_check(chain, token)
    score  = result["score"]
    warns  = result["warnings"]
    info   = result.get("info", {})

    lines = [
        f"🕵️ *Rug Check Report*",
        f"",
        f"{ci.get('emoji','')} Chain: {ci.get('name', chain)}",
        f"📍 `{token[:16]}\\.\\.\\. `",
        f"",
        f"*Risk Score: {score}*",
        f"",
        f"*Findings:*",
    ]
    for w in warns:
        lines.append(f"  {w}")

    if info:
        lines += [
            f"",
            f"*Token Stats:*",
            f"  💧 Liquidity: {fmt_mcap(info.get('liquidity',0))}",
            f"  📊 MCap: {fmt_mcap(info.get('mcap',0))}",
            f"  📦 Vol 24h: {fmt_mcap(info.get('volume24h',0))}",
            f"  🔀 DEX: {info.get('dex','?')}",
        ]
        if info.get("age_hours") is not None:
            h = info["age_hours"]
            age = f"{h*60:.0f}m" if h < 1 else (f"{h:.1f}h" if h < 24 else f"{h/24:.1f}d")
            lines.append(f"  🕐 Age: {age}")

    lines += [
        f"",
        f"_Always do your own research\\. "
        f"This is not financial advice\\._",
    ]

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("« Back to Panel",
                             callback_data=f"tp_refresh:{chain}:{token}:paper")
    ]])
    await send(update, "\n".join(lines), kb, edit=True)


async def tp_buy_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show buy amount buttons for the token panel."""
    await update.callback_query.answer()
    parts = update.callback_query.data.split(":")
    chain, token, mode = parts[1], parts[2], parts[3]
    ci = CHAINS.get(chain, {})

    # Show SOL/ETH/BNB amount buttons
    sym = ci.get("symbol", "ETH")
    buttons = [
        [
            InlineKeyboardButton(f"0.01 {sym}", callback_data=f"tp_amt:{chain}:{token}:{mode}:buy:0.01"),
            InlineKeyboardButton(f"0.05 {sym}", callback_data=f"tp_amt:{chain}:{token}:{mode}:buy:0.05"),
            InlineKeyboardButton(f"0.1 {sym}",  callback_data=f"tp_amt:{chain}:{token}:{mode}:buy:0.1"),
        ],
        [
            InlineKeyboardButton(f"0.5 {sym}",  callback_data=f"tp_amt:{chain}:{token}:{mode}:buy:0.5"),
            InlineKeyboardButton(f"1 {sym}",    callback_data=f"tp_amt:{chain}:{token}:{mode}:buy:1"),
            InlineKeyboardButton(f"Custom",     callback_data=f"tp_custom:{chain}:{token}:{mode}:buy"),
        ],
        [InlineKeyboardButton("« Back", callback_data=f"tp_refresh:{chain}:{token}:{mode}")],
    ]
    await send(update,
        f"🟢 *Buy {ci.get('name', chain)} Token*\n\n"
        f"Select how much *{sym}* to spend:",
        InlineKeyboardMarkup(buttons), edit=True)


async def tp_sell_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show sell percentage buttons for the token panel."""
    await update.callback_query.answer()
    parts = update.callback_query.data.split(":")
    chain, token, mode = parts[1], parts[2], parts[3]
    ci  = CHAINS.get(chain, {})
    user = ensure_user(update)

    # Find what token symbol we have
    info = get_token_full_info(chain, token)
    sym  = info["base_symbol"] if info else "TOKEN"
    bal  = db.get_paper_balance(user["id"], sym.upper(), chain)

    buttons = [
        [
            InlineKeyboardButton("25%",   callback_data=f"tp_sell_pct:{chain}:{token}:{mode}:{sym}:25"),
            InlineKeyboardButton("50%",   callback_data=f"tp_sell_pct:{chain}:{token}:{mode}:{sym}:50"),
            InlineKeyboardButton("75%",   callback_data=f"tp_sell_pct:{chain}:{token}:{mode}:{sym}:75"),
        ],
        [
            InlineKeyboardButton("100% (All)", callback_data=f"tp_sell_pct:{chain}:{token}:{mode}:{sym}:100"),
            InlineKeyboardButton("Custom",     callback_data=f"tp_custom:{chain}:{token}:{mode}:sell"),
        ],
        [InlineKeyboardButton("« Back", callback_data=f"tp_refresh:{chain}:{token}:{mode}")],
    ]
    price  = info["price"] if info else 0
    bal_usd = bal * price if price > 0 else 0
    await send(update,
        f"⚫ *Sell {sym}*\n\n"
        f"Your balance: `{bal:.6f} {sym}` \\(≈${bal_usd:.4f}\\)\n\n"
        f"Select % to sell:",
        InlineKeyboardMarkup(buttons), edit=True)


async def tp_amt_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Execute paper buy for a specific amount from the panel."""
    await update.callback_query.answer("Executing...")
    parts  = update.callback_query.data.split(":")
    chain, token, mode, action, amount_str = parts[1], parts[2], parts[3], parts[4], parts[5]
    user   = ensure_user(update)
    ci     = CHAINS.get(chain, {})

    try:
        amount = float(amount_str)
        info   = get_token_full_info(chain, token)
        sym    = info["base_symbol"] if info else "TOKEN"

        if mode == "paper":
            result = paper_buy(user["id"], chain, token, sym, amount)
            pnl_emoji = "✅"
            text = (
                f"{pnl_emoji} *Paper Buy Executed\\!*\n\n"
                f"{ci.get('emoji','')} {ci.get('name', chain)}\n"
                f"💸 Spent: `{amount} {ci.get('symbol','')}`\n"
                f"🪙 Got: `{result['received']:.6f} {sym}`\n"
                f"💵 Price: `{fmt_price(result['price'])}`\n"
                f"💰 USD: `${result['usd_value']:.4f}`"
            )
        else:
            text = "💎 Live buy — use /buy command for live trades\\."

    except Exception as e:
        text = f"❌ Buy failed: {e}"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Refresh Panel", callback_data=f"tp_refresh:{chain}:{token}:{mode}")
    ]])
    await send(update, text, kb, edit=True)


async def tp_sell_pct_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Execute paper sell for a percentage of holdings from the panel."""
    await update.callback_query.answer("Selling...")
    parts  = update.callback_query.data.split(":")
    chain, token, mode, sym, pct_str = parts[1], parts[2], parts[3], parts[4], parts[5]
    pct    = float(pct_str) / 100
    user   = ensure_user(update)
    ci     = CHAINS.get(chain, {})

    try:
        bal    = db.get_paper_balance(user["id"], sym.upper(), chain)
        amount = bal * pct
        if amount <= 0:
            await send(update, f"❌ No {sym} balance to sell\\.", edit=True)
            return

        if mode == "paper":
            result = paper_sell(user["id"], chain, token, sym, amount)
            pnl    = result["realized_pnl_usd"]
            ppct   = result["realized_pnl_pct"]
            pnl_e  = "✅" if pnl >= 0 else "❌"
            text = (
                f"{pnl_e} *Paper Sell Executed\\!*\n\n"
                f"{ci.get('emoji','')} {ci.get('name', chain)}\n"
                f"🪙 Sold: `{amount:.6f} {sym}` \\({pct_str}%\\)\n"
                f"💸 Got: `{result['received']:.6f} {result['received_symbol']}`\n"
                f"💵 Price: `{fmt_price(result['price'])}`\n\n"
                f"{pnl_e} *Realized P&L:* "
                f"`{'+'if pnl>=0 else ''}{pnl:.4f}` "
                f"\\(`{'+'if ppct>=0 else ''}{ppct:.2f}%`\\)"
            )
        else:
            text = "💎 Live sell — use /sell command for live trades\\."

    except Exception as e:
        text = f"❌ Sell failed: {e}"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Refresh Panel", callback_data=f"tp_refresh:{chain}:{token}:{mode}")
    ]])
    await send(update, text, kb, edit=True)


async def tp_noop_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """No-op for label buttons."""
    await update.callback_query.answer()

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
        f"Tap any strategy to see a full plain\\-English explanation "
        f"and set it up:\n\n"
    )
    # Two strategies per row to keep the button list compact
    keys  = list(STRATEGIES.keys())
    rows  = []
    for i in range(0, len(keys), 2):
        row = []
        for key in keys[i:i+2]:
            s = STRATEGIES[key]
            row.append(InlineKeyboardButton(
                f"{s['emoji']} {s['name']}", callback_data=f"strategy_select:{key}"
            ))
        rows.append(row)

    if active:
        rows.append([InlineKeyboardButton(
            f"📋 My Running Strategies ({active_count})",
            callback_data="strategy_list"
        )])
    rows.append([InlineKeyboardButton("« Back", callback_data="back:main")])

    await send(update, text, InlineKeyboardMarkup(rows), edit=True)

async def strategy_select_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    strategy_key = update.callback_query.data.split(":")[1]
    s = STRATEGIES.get(strategy_key)
    if not s:
        await send(update, "❌ Strategy not found\\.", edit=True)
        return

    ctx.user_data["strategy_key"] = strategy_key

    # Show plain-English description with default params filled in
    native_sym = "ETH"  # generic for description preview
    desc = format_strategy_description(strategy_key, s["params"], native_sym)

    text = (
        f"{s['emoji']} *{s['name']}*\n"
        f"_Risk: {s['risk']} · Best for: {s['best_for']}_\n\n"
        f"{desc}\n\n"
        f"{'━'*28}\n"
        f"Select a chain to continue:"
    )

    kb = chain_keyboard("strategy_chain",
        extra_row=[InlineKeyboardButton("« Back to Strategies", callback_data="menu:strategies")]
    )
    await send(update, text, kb, edit=True)
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
        await update.message.reply_text(
            "🤖 No strategies running\\. Use /start → Strategies to set one up\\.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    text = "🤖 *Your Trading Strategies*\n\n"
    buttons = []

    for s in strategies:
        stats    = get_strategy_stats(s["id"])
        s_info   = STRATEGIES.get(s["name"], {})
        ci       = CHAINS.get(s["chain"], {})
        status_e = {"active": "🟢", "stopped": "🔴", "paused": "⏸"}.get(s["status"], "⚪")
        mode_tag = "📝" if s["mode"] == "paper" else "💎"

        # Realized P&L from closed positions
        realized        = db.get_realized_pnl(user["id"], s["id"])
        unrealized_data = get_unrealized_pnl(user["id"], s["id"])
        unrealized      = unrealized_data["total_unrealized"]
        total_pnl       = realized + unrealized

        pnl_emoji   = "✅" if total_pnl >= 0 else "❌"
        total_sign  = "+" if total_pnl  >= 0 else ""
        real_sign   = "+" if realized   >= 0 else ""
        unreal_sign = "+" if unrealized >= 0 else ""
        wr_str      = f"{stats['win_rate']*100:.0f}%" if stats["total_trades"] > 0 else "—"
        logs        = get_learning_log(s["id"])
        learned_str = f" 🧠x{len(logs)}" if logs else ""

        # Live token data — DexScreener first, fallback to CoinGecko
        token_info = get_token_full_info(s["chain"], s["token_address"])
        if token_info and token_info.get("price"):
            price_str = fmt_price(token_info["price"])
            mcap_str  = fmt_mcap(token_info["mcap"])
            vol_str   = fmt_mcap(token_info["volume24h"])
            ch24_val  = token_info.get("change24h", 0) or 0
            ch24_sign = "+" if ch24_val >= 0 else ""
            ch24_str  = f"{ch24_sign}{ch24_val:.1f}%"
        else:
            from trading.paper_trade import _get_token_usd_price
            fb_price  = _get_token_usd_price(
                s.get("token_symbol", ""), s["chain"], s["token_address"]
            )
            price_str = fmt_price(fb_price) if fb_price else "N/A"
            mcap_str  = "N/A"
            vol_str   = "N/A"
            ch24_str  = ""

        text += (
            f"{status_e}{mode_tag} *{s_info.get('name', s['name'])}* \\[\\#{s['id']}\\]\n"
            f"  {ci.get('emoji','')} {ci.get('name',s['chain'])} — *{s.get('token_symbol','?')}*\n"
            f"  💵 {price_str} {ch24_str} | MCap: {mcap_str} | Vol: {vol_str}\n"
            f"  📊 {stats['total_trades']} trades | WR: {wr_str}{learned_str}\n"
            f"  {pnl_emoji} Total P&L: `{total_sign}{total_pnl:.4f}`\n"
            f"    ✅ Realized: `{real_sign}{realized:.4f}`"
        )
        if unrealized_data["positions"]:
            open_count = len(unrealized_data["positions"])
            text += (
                f" | 📂 Unrealized: `{unreal_sign}{unrealized:.4f}` [{open_count} pos]"
            )
        text += "\n\n"

        row = []
        if s["status"] == "active":
            row.append(InlineKeyboardButton(
                f"⚙️ Edit #{s['id']}", callback_data=f"edit_strat:{s['id']}"
            ))
            row.append(InlineKeyboardButton(
                f"📈 Stats #{s['id']}", callback_data=f"strat_stats:{s['id']}"
            ))
            row.append(InlineKeyboardButton(
                f"⏹ Stop #{s['id']}", callback_data=f"stop_strategy:{s['id']}"
            ))
        buttons.append(row)

    buttons.append([InlineKeyboardButton("📊 Weekly Report", callback_data="weekly_report")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="back:main")])

    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def strategy_stats_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show deep stats for a single strategy."""
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split(":")[1])
    strategies = db.get_user_strategies_by_id(sid)
    if not strategies:
        await send(update, "❌ Strategy not found\\.", edit=True); return

    s      = strategies[0]
    stats  = get_strategy_stats(sid)
    s_info = STRATEGIES.get(s["name"], {})
    ci     = CHAINS.get(s["chain"], {})
    logs   = get_learning_log(sid)

    pnl       = stats["total_pnl"]
    pnl_emoji = "✅" if pnl >= 0 else "❌"

    text = (
        f"📈 *Strategy Deep Stats* \\[\\#{sid}\\]\n"
        f"{s_info.get('emoji','')} *{s_info.get('name', s['name'])}*\n"
        f"{ci.get('emoji','')} {ci.get('name',s['chain'])} — *{s.get('token_symbol','?')}*\n\n"
        f"{'━'*28}\n"
        f"📊 *Performance*\n"
        f"  Total trades: *{stats['total_trades']}*\n"
        f"  Wins / Losses: *{stats['wins']}W / {stats['losses']}L*\n"
        f"  Win rate: *{stats['win_rate']*100:.1f}%*\n\n"
        f"{pnl_emoji} *P&L*\n"
        f"  Total: `{'+'if pnl>=0 else ''}{pnl:.6f}`\n"
        f"  Avg win: `+{stats['avg_win']:.2f}%`\n"
        f"  Avg loss: `{stats['avg_loss']:.2f}%`\n"
        f"  Best trade: `+{stats['best_trade']:.2f}%`\n"
        f"  Worst trade: `{stats['worst_trade']:.2f}%`\n\n"
        f"📐 *Quality Metrics*\n"
        f"  Profit factor: *{stats['profit_factor']:.2f}x* "
        f"_\\(>1 = profitable overall\\)_\n"
        f"  Expectancy: *{stats['expectancy']:+.2f}%* per trade\n\n"
    )

    if logs:
        text += f"🧠 *What the Bot Learned \\({len(logs)} adjustments\\)*\n"
        for log in logs[:3]:
            adjustments = json.loads(log.get("adjustments") or "[]")
            for adj in adjustments[:2]:
                text += f"  • {adj}\n"
        text += "\n"

    text += f"{'━'*28}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Edit Params", callback_data=f"edit_strat:{sid}")],
        [InlineKeyboardButton("« Back", callback_data="back:main")],
    ])
    await send(update, text, kb, edit=True)


async def edit_strategy_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show all editable parameters for a strategy."""
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split(":")[1])
    strategies = db.get_user_strategies_by_id(sid)
    if not strategies:
        await send(update, "❌ Strategy not found\\.", edit=True); return

    s       = strategies[0]
    params  = json.loads(s.get("params") or "{}")
    s_info  = STRATEGIES.get(s["name"], {})
    ci      = CHAINS.get(s["chain"], {})
    ep_list = get_editable_params(s["name"])

    text = (
        f"⚙️ *Edit Strategy* \\[\\#{sid}\\]\n"
        f"{s_info.get('emoji','')} *{s_info.get('name', s['name'])}*\n"
        f"{ci.get('emoji','')} {ci.get('name',s['chain'])} — *{s.get('token_symbol','?')}*\n\n"
        f"{'━'*28}\n"
        f"*Current Settings:*\n"
    )
    for ep in ep_list:
        current = params.get(ep["key"], s_info.get("params",{}).get(ep["key"], "?"))
        text += f"  • {ep['label']}: `{current}`\n"

    text += f"\n_Tap a parameter to change it:_"

    buttons = []
    for ep in ep_list:
        current = params.get(ep["key"], s_info.get("params",{}).get(ep["key"], "?"))
        buttons.append([InlineKeyboardButton(
            f"✏️ {ep['label']} (now: {current})",
            callback_data=f"edit_param:{sid}:{ep['key']}"
        )])

    buttons.append([InlineKeyboardButton("« Back to Stats", callback_data=f"strat_stats:{sid}")])
    await send(update, text, InlineKeyboardMarkup(buttons), edit=True)


async def edit_param_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show options for editing a specific strategy parameter."""
    await update.callback_query.answer()
    parts = update.callback_query.data.split(":")
    sid, param_key = int(parts[1]), parts[2]

    strategies = db.get_user_strategies_by_id(sid)
    if not strategies: return
    s      = strategies[0]
    params = json.loads(s.get("params") or "{}")
    s_info = STRATEGIES.get(s["name"], {})
    ep_list = get_editable_params(s["name"])
    ep = next((e for e in ep_list if e["key"] == param_key), None)
    if not ep: return

    current = params.get(param_key, s_info.get("params",{}).get(param_key, "?"))

    ctx.user_data["edit_sid"]   = sid
    ctx.user_data["edit_param"] = param_key

    text = (
        f"✏️ *Edit: {ep['label']}*\n\n"
        f"📖 {ep['desc']}\n\n"
        f"Current value: `{current}`\n"
        f"Allowed range: `{ep['min']}` → `{ep['max']}`\n\n"
    )

    buttons = []

    # Show preset buttons if available
    presets = ep.get("presets", [])
    preset_labels = ep.get("preset_labels", [str(p) for p in presets])
    if presets:
        text += "*Quick presets:*\n"
        row = []
        for p, pl in zip(presets, preset_labels):
            marker = " ✅" if str(p) == str(current) else ""
            row.append(InlineKeyboardButton(
                f"{pl}{marker}", callback_data=f"set_param:{sid}:{param_key}:{p}"
            ))
            if len(row) == 3:
                buttons.append(row); row = []
        if row:
            buttons.append(row)
        text += "\n_Or type a custom value:_"
    else:
        text += "_Type your custom value and send it:_"

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"edit_strat:{sid}")])
    await send(update, text, InlineKeyboardMarkup(buttons), edit=True)
    return AWAIT_PARAM_VALUE


async def set_param_preset_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Apply a preset param value."""
    await update.callback_query.answer()
    parts     = update.callback_query.data.split(":")
    sid       = int(parts[1])
    param_key = parts[2]
    new_val   = parts[3]
    await _apply_param_change(update, ctx, sid, param_key, new_val)
    return ConversationHandler.END


async def set_param_custom(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Apply a typed custom param value."""
    sid       = ctx.user_data.get("edit_sid")
    param_key = ctx.user_data.get("edit_param")
    if not sid or not param_key:
        return ConversationHandler.END
    await _apply_param_change(update, ctx, sid, param_key, update.message.text.strip())
    return ConversationHandler.END


async def _apply_param_change(update, ctx, sid, param_key, raw_value):
    strategies = db.get_user_strategies_by_id(sid)
    if not strategies: return
    s      = strategies[0]
    params = json.loads(s.get("params") or "{}")
    s_info = STRATEGIES.get(s["name"], {})
    ep_list = get_editable_params(s["name"])
    ep = next((e for e in ep_list if e["key"] == param_key), None)
    if not ep: return

    try:
        if ep["type"] == "int":
            val = int(float(raw_value))
        else:
            val = float(raw_value)

        if val < ep["min"] or val > ep["max"]:
            raise ValueError(f"Must be between {ep['min']} and {ep['max']}")

        params[param_key] = val
        db.update_strategy_params(sid, params)

        confirm_text = (
            f"✅ *Setting updated\\!*\n\n"
            f"*{ep['label']}* changed to `{val}`\n\n"
            f"The strategy will use this new value from the next trade onwards\\."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Edit More Settings", callback_data=f"edit_strat:{sid}")],
            [InlineKeyboardButton("📈 View Stats", callback_data=f"strat_stats:{sid}")],
        ])
        if update.callback_query:
            await send(update, confirm_text, kb, edit=True)
        else:
            await update.message.reply_text(confirm_text, parse_mode=ParseMode.MARKDOWN,
                                            reply_markup=kb)
    except ValueError as e:
        err = f"❌ Invalid value: {e}\\. Please try again\\."
        if update.callback_query:
            await send(update, err, edit=True)
        else:
            await update.message.reply_text(err, parse_mode=ParseMode.MARKDOWN)


async def weekly_report_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send the weekly performance report."""
    await update.callback_query.answer()
    user = ensure_user(update)
    await send(update, "⏳ Generating your weekly report\\.\\.\\.", edit=True)
    try:
        report = get_weekly_report(user["id"])
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="back:main")]])
        await send(update, report, kb, edit=True)
    except Exception as e:
        await send(update, f"❌ Error generating report: {e}", edit=True)


async def weekly_report_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send weekly report via command."""
    user = ensure_user(update)
    await update.message.reply_text("⏳ Generating weekly report...")
    report = get_weekly_report(user["id"])
    await update.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)

async def stop_strategy_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    sid = int(update.callback_query.data.split(":")[1])
    user = ensure_user(update)
    db.stop_strategy(sid, user["id"])
    await update.callback_query.edit_message_text(
        f"⏹ Strategy \\#{sid} stopped\\.", parse_mode=ParseMode.MARKDOWN
    )

async def strategy_list_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show running strategies from the strategies menu."""
    await update.callback_query.answer()
    # Re-use my_strategies_cmd logic but as inline
    user = ensure_user(update)
    strategies = db.get_user_strategies(user["id"])
    if not strategies:
        await send(update, "🤖 No strategies running yet\\.\nUse the Strategies menu to set one up\\!", edit=True)
        return
    # Build same text as my_strategies_cmd but send inline
    text = "📋 *Running Strategies*\n\n"
    buttons = []
    for s in strategies:
        stats    = get_strategy_stats(s["id"])
        s_info   = STRATEGIES.get(s["name"], {})
        ci       = CHAINS.get(s["chain"], {})
        status_e = {"active": "🟢", "stopped": "🔴", "paused": "⏸"}.get(s["status"], "⚪")
        mode_tag = "📝" if s["mode"] == "paper" else "💎"
        pnl      = stats["total_pnl"]
        pnl_str  = f"{'+'if pnl>=0 else ''}{pnl:.4f}"
        wr_str   = f"{stats['win_rate']*100:.0f}%" if stats["total_trades"] > 0 else "—"
        text += (
            f"{status_e}{mode_tag} *{s_info.get('name', s['name'])}* \\[\\#{s['id']}\\]\n"
            f"  {ci.get('emoji','')} {ci.get('name',s['chain'])} — *{s.get('token_symbol','?')}*\n"
            f"  {stats['total_trades']} trades | WR: {wr_str} | P&L: `{pnl_str}`\n\n"
        )
        row = []
        if s["status"] == "active":
            row.append(InlineKeyboardButton(f"📈 Stats", callback_data=f"strat_stats:{s['id']}"))
            row.append(InlineKeyboardButton(f"⚙️ Edit",  callback_data=f"edit_strat:{s['id']}"))
            row.append(InlineKeyboardButton(f"⏹ Stop",  callback_data=f"stop_strategy:{s['id']}"))
            buttons.append(row)
    buttons.append([InlineKeyboardButton("« Back to Strategies", callback_data="menu:strategies")])
    await send(update, text, InlineKeyboardMarkup(buttons), edit=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  RESET COMMAND — user-controlled, never automatic
# ═══════════════════════════════════════════════════════════════════════════════

async def reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show reset options — user must explicitly choose what to wipe."""
    text = (
        "🔄 *Reset Data*\n\n"
        "⚠️ Choose what to reset\\. "
        "This cannot be undone\\.\n\n"
        "Your strategies and wallets are *never* touched by updates — "
        "only you can reset them here\\."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Reset Paper Balance Only",  callback_data="reset:paper")],
        [InlineKeyboardButton("📜 Clear Trade History",       callback_data="reset:trades")],
        [InlineKeyboardButton("🤖 Stop & Delete All Strategies", callback_data="reset:strategies")],
        [InlineKeyboardButton("📊 Cancel All DCA Orders",    callback_data="reset:dca")],
        [InlineKeyboardButton("🔔 Cancel All Alerts",        callback_data="reset:alerts")],
        [InlineKeyboardButton("☢️ FULL RESET (wipe everything)", callback_data="reset:all")],
        [InlineKeyboardButton("❌ Cancel — keep everything", callback_data="back:main")],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def reset_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle reset confirmation."""
    await update.callback_query.answer()
    what = update.callback_query.data.split(":")[1]

    labels = {
        "paper":      "paper balance",
        "trades":     "trade history",
        "strategies": "all strategies and learning data",
        "dca":        "all DCA orders",
        "alerts":     "all price alerts",
        "all":        "EVERYTHING",
    }
    label = labels.get(what, what)

    # First tap shows confirmation
    confirm_key = f"reset_confirmed_{what}"
    if not ctx.user_data.get(confirm_key):
        ctx.user_data[confirm_key] = True
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Yes, reset {label}", callback_data=f"reset_confirm:{what}")],
            [InlineKeyboardButton("❌ No, cancel", callback_data="back:main")],
        ])
        await send(update,
            f"⚠️ *Are you sure?*\n\n"
            f"This will permanently delete your *{label}*\\.\n\n"
            f"Tap confirm to proceed:",
            kb, edit=True)
        return

async def reset_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Execute the reset after double-confirmation."""
    await update.callback_query.answer()
    what  = update.callback_query.data.split(":")[1]
    user  = ensure_user(update)
    wiped = db.reset_user_data(user["id"], [what])

    labels = {
        "paper":      "📝 Paper balance reset to zero",
        "trades":     "📜 Trade history cleared",
        "strategies": "🤖 All strategies stopped and deleted",
        "dca":        "📊 All DCA orders cancelled",
        "alerts":     "🔔 All price alerts removed",
        "all":        "☢️ Full reset complete",
    }
    msg = labels.get(what, f"Reset: {what}")

    # Clear any confirmation state
    for key in list(ctx.user_data.keys()):
        if key.startswith("reset_confirmed_"):
            del ctx.user_data[key]

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Main Menu", callback_data="back:main")]])
    await send(update,
        f"✅ *Done\\!*\n\n{msg}\\.\n\n"
        f"_Your other data is untouched\\._",
        kb, edit=True)

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
        "*TOKEN PANEL & ANALYSIS*\n"
        "`/token [chain] [address]` — Full trade panel with chart, buy/sell\n"
        "`/rugcheck [chain] [address]` — Rug pull risk analysis\n\n"
        "*RESET*\n"
        "`/reset` — Selectively wipe data \\(double confirmed\\)\n\n"
        "_Use `native` as token for ETH/BNB/SOL etc_"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="back:main")]])
    await send(update, text, kb, edit=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  BACKGROUND: Strategy & DCA runner + Alert monitor
# ═══════════════════════════════════════════════════════════════════════════════

async def run_background_tasks(app: Application):
    """Master background loop — runs every 60 seconds."""
    tick = 0
    while True:
        try:
            await _process_strategies(app)
            await _process_dca(app)
            await _process_alerts(app)

            # Every 24 hours: clean up old signal messages
            if tick % 1440 == 0 and tick > 0:
                await _cleanup_old_messages(app)

            # Every 7 days: send weekly reports
            if tick % 10080 == 0 and tick > 0:
                await _send_weekly_reports(app)

            tick += 1
        except Exception as e:
            print(f"[Background] Error: {e}")
        await asyncio.sleep(60)


async def _process_strategies(app: Application):
    """Check all active strategies, execute trades, record outcomes for learning."""
    strategies = db.get_active_strategies()
    for s in strategies:
        try:
            params = json.loads(s.get("params") or "{}")

            # Route perp strategies to their dedicated processor
            if params.get("strategy_type") == "perp":
                try:
                    from bot.perp_handlers import process_perp_strategy
                    await process_perp_strategy(s, params, app)
                except Exception as pe:
                    print(f"[PerpStrategy #{s['id']}] Error: {pe}")
                continue

            signal      = get_signal(s["name"], s["chain"], s["token_address"], params, strategy_id=s["id"])
            trade_amount = params.get("trade_amount", 0.01)
            user_id      = s["user_id"]
            ci           = CHAINS.get(s["chain"], {})

            if signal["signal"] == "hold":
                continue

            result      = None
            entry_price = signal["indicators"].get("current_price", 0)

            # ── Paper mode ────────────────────────────────────────────────────
            if s["mode"] == "paper":
                if signal["signal"] == "buy":
                    try:
                        result = paper_buy(
                            user_id, s["chain"], s["token_address"],
                            s.get("token_symbol", "TOKEN"), trade_amount,
                            strategy_id=s["id"]
                        )
                        on_trade_executed(s["id"], "buy", entry_price)
                        # paper_buy already calls save_trade internally
                        if False: trade_id = db.save_trade({
                            "user_id":    user_id,
                            "chain":      s["chain"],
                            "trade_type": "buy",
                            "mode":       "paper",
                            "token_in":   "native",
                            "token_out":  s["token_address"],
                            "symbol_in":  ci.get("symbol",""),
                            "symbol_out": s.get("token_symbol","TOKEN"),
                            "amount_in":  trade_amount,
                            "amount_out": result.get("received", 0),
                            "price_at_trade": entry_price,
                            "entry_price": entry_price,
                            "status":     "success",
                            "strategy":   s["name"],
                        })
                    except Exception as ex:
                        print(f"[Strategy] Paper buy failed: {ex}")
                        result = None

                elif signal["signal"] == "sell":
                    token_sym = s.get("token_symbol", "TOKEN")
                    balance   = db.get_paper_balance(user_id, token_sym, s["chain"])
                    if balance <= 0:
                        continue
                    try:
                        result = paper_sell(
                            user_id, s["chain"], s["token_address"],
                            token_sym, balance * 0.9,
                            strategy_id=s["id"]  # links position for real PnL
                        )
                        on_trade_executed(s["id"], "sell", signal["indicators"].get("current_price", 0))
                        exit_price = signal["indicators"].get("current_price", 0)

                        # Find matching buy trade to calculate PnL
                        recent = db.get_trades(user_id, limit=50, mode="paper")
                        buy_trade = next(
                            (t for t in recent
                             if t["trade_type"] == "buy"
                             and t.get("token_out") == s["token_address"]
                             and t.get("strategy") == s["name"]),
                            None
                        )
                        if buy_trade and buy_trade.get("entry_price", 0) > 0:
                            record_trade_outcome(
                                strategy_id  = s["id"],
                                trade_id     = buy_trade["id"],
                                entry_price  = buy_trade["entry_price"],
                                exit_price   = exit_price,
                                amount       = buy_trade.get("amount_out", 0),
                                signal_data  = signal["indicators"],
                            )

                    except Exception as ex:
                        print(f"[Strategy] Paper sell failed: {ex}")
                        continue

            # ── Send notification & log message id for cleanup ────────────────
            msg_text = format_signal_message(
                s["name"], signal, s.get("token_symbol","TOKEN"),
                s["chain"], s["mode"],
                strategy_id=s["id"], user_id=s["user_id"]
            )
            try:
                sent = await app.bot.send_message(
                    chat_id=s["tg_id"], text=msg_text,
                    parse_mode=ParseMode.MARKDOWN
                )
                # Log message so we can delete it during daily cleanup
                db.log_message(s["tg_id"], s["tg_id"], sent.message_id, "signal")
            except Exception:
                pass

        except Exception as e:
            print(f"[Strategy] Error for strategy {s['id']}: {e}")


async def _process_dca(app: Application):
    """Execute due DCA orders."""
    orders = db.get_due_dca_orders()
    for o in orders:
        try:
            next_run    = (datetime.utcnow() + timedelta(minutes=o["freq_minutes"])).isoformat()
            done        = o["done_orders"] + 1
            is_complete = o["total_orders"] > 0 and done >= o["total_orders"]

            if o["mode"] == "paper":
                try:
                    result = paper_buy(
                        o["user_id"], o["chain"], o["token_out"],
                        o.get("symbol_out","TOKEN"), o["amount_per_order"]
                    )
                    db.save_trade({
                        "user_id":    o["user_id"],
                        "chain":      o["chain"],
                        "trade_type": "dca",
                        "mode":       "paper",
                        "token_in":   "native",
                        "token_out":  o["token_out"],
                        "symbol_in":  o.get("symbol_in",""),
                        "symbol_out": o.get("symbol_out","TOKEN"),
                        "amount_in":  o["amount_per_order"],
                        "amount_out": result.get("received",0),
                        "price_at_trade": result.get("price",0),
                        "status": "success",
                    })
                    status_msg = (
                        f"🤖 *DCA Executed \\#{o['id']}*\n\n"
                        f"✅ Bought `{result['received']:.6f}` {result['received_symbol']}\n"
                        f"💸 Spent `{o['amount_per_order']} {result['spent_symbol']}`\n"
                        f"💵 Price: {fmt_price(result.get('price'))}\n"
                        f"📊 Progress: {done}/"
                        f"{'∞' if o['total_orders']==0 else o['total_orders']}"
                    )
                    if is_complete:
                        status_msg += "\n\n🎉 *DCA order completed\\!*"
                except Exception as e:
                    status_msg = f"❌ DCA \\#{o['id']} failed: `{e}`"

            db.update_dca(o["id"],
                          done_orders=done,
                          next_run=next_run,
                          status="completed" if is_complete else "active")
            try:
                sent = await app.bot.send_message(
                    chat_id=o["tg_id"], text=status_msg,
                    parse_mode=ParseMode.MARKDOWN
                )
                db.log_message(o["tg_id"], o["tg_id"], sent.message_id, "dca")
            except Exception:
                pass
        except Exception as e:
            print(f"[DCA] Error for order {o['id']}: {e}")


async def _process_alerts(app: Application):
    """Check price alerts and notify when triggered."""
    alerts = db.get_active_alerts()
    for a in alerts:
        try:
            native_addr = CHAINS.get(a["chain"], {}).get("native","")
            cg_id       = CHAINS.get(a["chain"], {}).get("coingecko_id")
            is_native   = a["token_address"].lower() == native_addr.lower()

            if a["chain"] == "solana":
                pd = get_price_dexscreener("solana", a["token_address"])
            elif is_native and cg_id:
                pd = get_price_coingecko(cg_id)
            else:
                pd = get_price_dexscreener(a["chain"], a["token_address"])

            if not pd or not pd.get("price"):
                continue

            price     = pd["price"]
            triggered = (
                (a["condition"] == "above" and price >= a["target_price"]) or
                (a["condition"] == "below" and price <= a["target_price"])
            )
            if triggered:
                db.trigger_alert(a["id"])
                cond_str = "risen above" if a["condition"] == "above" else "fallen below"
                ci = CHAINS.get(a["chain"], {})
                await app.bot.send_message(
                    chat_id=a["tg_id"],
                    text=(
                        f"🔔 *Price Alert Triggered\\!*\n\n"
                        f"{ci.get('emoji','')} *{a.get('token_symbol','Token')}* "
                        f"on {ci.get('name', a['chain'])}\n"
                        f"Price has {cond_str} *{fmt_price(a['target_price'])}*\n"
                        f"Current price: *{fmt_price(price)}*\n\n"
                        f"_Alert \\#{a['id']} has been deactivated_"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception:
            pass


async def _cleanup_old_messages(app: Application):
    """
    Delete signal and DCA notification messages older than 24 hours.
    Keeps the chat clean — users get a weekly summary instead.
    """
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    old_msgs = db.get_old_messages(cutoff, msg_type="signal")
    old_msgs += db.get_old_messages(cutoff, msg_type="dca")

    deleted_ids = []
    for msg in old_msgs:
        try:
            await app.bot.delete_message(
                chat_id=msg["chat_id"],
                message_id=msg["message_id"]
            )
            deleted_ids.append(msg["id"])
        except Exception:
            # Message already deleted or too old — still remove from log
            deleted_ids.append(msg["id"])

    if deleted_ids:
        db.delete_message_log_entries(deleted_ids)
        print(f"[Cleanup] Deleted {len(deleted_ids)} old messages")


async def _send_weekly_reports(app: Application):
    """Auto-send weekly reports to all users on Sunday."""
    from utils.database import get_conn
    conn = get_conn()
    users = conn.execute("SELECT * FROM users").fetchall()
    conn.close()

    for user_row in users:
        user = dict(user_row)
        try:
            report = get_weekly_report(user["id"])
            sent = await app.bot.send_message(
                chat_id=user["tg_id"],
                text=report,
                parse_mode=ParseMode.MARKDOWN
            )
            db.log_message(user["tg_id"], user["tg_id"], sent.message_id, "weekly_report")
        except Exception as e:
            print(f"[WeeklyReport] Failed for user {user['tg_id']}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  HEALTH CHECK SERVER — keeps Railway/Render happy
# ═══════════════════════════════════════════════════════════════════════════════

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","bot":"CryptoBot","running":true}')

    def log_message(self, fmt, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"✅ Health check server on port {port}")
    except Exception as e:
        print(f"⚠️  Health server could not start: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def cleanup_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Manually trigger a chat cleanup right now."""
    await update.message.reply_text("🧹 Cleaning up old messages...")
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    old_msgs = db.get_old_messages(cutoff, msg_type="signal")
    old_msgs += db.get_old_messages(cutoff, msg_type="dca")
    deleted = 0
    ids_to_remove = []
    for msg in old_msgs:
        try:
            await ctx.bot.delete_message(
                chat_id=msg["chat_id"],
                message_id=msg["message_id"]
            )
            deleted += 1
        except Exception:
            pass
        ids_to_remove.append(msg["id"])
    if ids_to_remove:
        db.delete_message_log_entries(ids_to_remove)
    await update.message.reply_text(
        f"✅ *Cleanup done\\!*\n\n"
        f"Removed {deleted} old signal/DCA messages from chat\\.\n"
        f"_Auto\\-cleanup runs daily\\. Use /report for your weekly summary\\._",
        parse_mode=ParseMode.MARKDOWN
    )


def main():
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE" or not BOT_TOKEN:
        print("=" * 55)
        print("❌  BOT_TOKEN is not set!")
        print("=" * 55)
        print("Railway: Variables tab → add BOT_TOKEN")
        print("Local:   Edit config/secrets.py")
        print("=" * 55)
        sys.exit(1)

    start_health_server()

    db.init_db()
    try:
        db.ensure_learning_tables()
    except Exception:
        pass
    try:
        db.ensure_positions_table()
    except Exception:
        pass
    try:
        from trading.perpetuals import ensure_perp_tables
        ensure_perp_tables()
    except Exception:
        pass
    print("✅ Database initialised")

    app = Application.builder().token(BOT_TOKEN).build()

    # ── Conversation: wallet import ───────────────────────────────────────────
    import_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(import_chain_callback, pattern="^import_chain:")],
        states={AWAIT_IMPORT_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, import_key_received)]},
        fallbacks=[CallbackQueryHandler(cancel_callback, pattern="^cancel$")],
        per_message=False,
    )

    # ── Conversation: paper top-up ────────────────────────────────────────────
    topup_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(topup_start, pattern="^topup:start$")],
        states={
            AWAIT_TOPUP_CHAIN:  [CallbackQueryHandler(topup_chain_selected,  pattern="^topup_chain:")],
            AWAIT_TOPUP_ASSET:  [CallbackQueryHandler(topup_asset_selected,  pattern="^topup_asset:")],
            AWAIT_TOPUP_AMOUNT: [
                CallbackQueryHandler(topup_amount_selected, pattern="^topup_amt:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, topup_custom_received),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_callback, pattern="^cancel$")],
        per_message=False,
    )

    # ── Conversation: strategy setup ──────────────────────────────────────────
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

    # ── Conversation: edit strategy param ─────────────────────────────────────
    edit_param_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_param_callback, pattern="^edit_param:")],
        states={
            AWAIT_PARAM_VALUE: [
                CallbackQueryHandler(set_param_preset_callback, pattern="^set_param:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_param_custom),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_callback, pattern="^cancel$")],
        per_message=False,
    )

    # ── Commands ──────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("help",       help_cmd))
    app.add_handler(CommandHandler("price",      price_cmd))
    app.add_handler(CommandHandler("alert",      alert_cmd))
    app.add_handler(CommandHandler("alerts",     lambda u,c: alerts_menu(u,c)))
    app.add_handler(CommandHandler("pbuy",       pbuy_cmd))
    app.add_handler(CommandHandler("psell",      psell_cmd))
    app.add_handler(CommandHandler("portfolio",  lambda u,c: paper_menu(u,c)))
    app.add_handler(CommandHandler("newdca",     newdca_cmd))
    app.add_handler(CommandHandler("dcalist",    lambda u,c: dca_menu(u,c)))
    app.add_handler(CommandHandler("mystrats",   my_strategies_cmd))
    app.add_handler(CommandHandler("report",     weekly_report_cmd))
    app.add_handler(CommandHandler("cleanup",    cleanup_cmd))
    app.add_handler(CommandHandler("reset",      reset_cmd))
    app.add_handler(CommandHandler("token",      token_panel_cmd))
    app.add_handler(CommandHandler("rugcheck",   rugcheck_standalone_cmd))

    # ── Conversations (must come before generic callback handlers) ────────────
    app.add_handler(import_conv)
    app.add_handler(topup_conv)
    app.add_handler(strategy_conv)
    app.add_handler(edit_param_conv)

    # ── Callback buttons ──────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(start,                    pattern="^back:main$"))
    app.add_handler(CallbackQueryHandler(menu_callback,            pattern="^menu:"))
    app.add_handler(CallbackQueryHandler(wallet_callback,          pattern="^wallet:"))
    app.add_handler(CallbackQueryHandler(gen_wallet_callback,      pattern="^gen_wallet:"))
    app.add_handler(CallbackQueryHandler(paper_trade_callback,     pattern="^ptrade:"))
    app.add_handler(CallbackQueryHandler(fund_start,               pattern="^fund:start$"))
    app.add_handler(CallbackQueryHandler(dca_list_callback,        pattern="^dca_list$"))
    app.add_handler(CallbackQueryHandler(cancel_dca_callback,      pattern="^cancel_dca:"))
    app.add_handler(CallbackQueryHandler(cancel_alert_callback,    pattern="^cancel_alert:"))
    app.add_handler(CallbackQueryHandler(stop_strategy_callback,   pattern="^stop_strategy:"))
    app.add_handler(CallbackQueryHandler(strategy_list_callback,   pattern="^strategy_list$"))
    app.add_handler(CallbackQueryHandler(strategy_select_callback, pattern="^strategy_select:"))
    app.add_handler(CallbackQueryHandler(strategy_stats_callback,  pattern="^strat_stats:"))
    app.add_handler(CallbackQueryHandler(edit_strategy_callback,   pattern="^edit_strat:"))
    app.add_handler(CallbackQueryHandler(set_param_preset_callback,pattern="^set_param:"))
    app.add_handler(CallbackQueryHandler(weekly_report_callback,   pattern="^weekly_report$"))
    app.add_handler(CallbackQueryHandler(reset_callback,           pattern="^reset:"))
    app.add_handler(CallbackQueryHandler(reset_confirm_callback,   pattern="^reset_confirm:"))
    app.add_handler(CallbackQueryHandler(cancel_callback,          pattern="^cancel$"))
    app.add_handler(CallbackQueryHandler(tp_refresh_callback,      pattern="^tp_refresh:"))
    app.add_handler(CallbackQueryHandler(rugcheck_callback,        pattern="^rugcheck:"))
    app.add_handler(CallbackQueryHandler(tp_buy_callback,          pattern="^tp_buy:"))
    app.add_handler(CallbackQueryHandler(tp_sell_callback,         pattern="^tp_sell:"))
    app.add_handler(CallbackQueryHandler(tp_amt_callback,          pattern="^tp_amt:"))
    app.add_handler(CallbackQueryHandler(tp_sell_pct_callback,     pattern="^tp_sell_pct:"))
    app.add_handler(CallbackQueryHandler(tp_noop_callback,         pattern="^noop$"))

    # ── Background loop ───────────────────────────────────────────────────────
    async def post_init(application: Application):
        asyncio.create_task(run_background_tasks(application))

    app.post_init = post_init

    # ── Perpetuals handlers ──────────────────────────────────────────────────
    from bot.perp_handlers import register_perp_handlers
    register_perp_handlers(app)

    # ── Perp button in main menu (add to menu callback) ───────────────────────

    print("🚀 Bot is running! Open Telegram and send /start")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()


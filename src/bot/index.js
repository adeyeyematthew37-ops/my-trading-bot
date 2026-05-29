// src/bot/index.js
const { Telegraf, Markup, session } = require('telegraf');
const logger = require('../utils/logger');
const db = require('../utils/database');

// Import all command handlers
const { handleStart, handleHelp } = require('./commands/start');
const walletCommands = require('./commands/wallet');
const tradeCommands = require('./commands/trade');
const dcaCommands = require('./commands/dca');
const priceCommands = require('./commands/price');
const alertCommands = require('./commands/alerts');

function createBot() {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token || token === 'your_telegram_bot_token_here') {
    throw new Error('TELEGRAM_BOT_TOKEN is not set. Get one from @BotFather on Telegram.');
  }

  const bot = new Telegraf(token);

  // Session middleware for multi-step flows
  bot.use(session());

  // Auth middleware — register user on every interaction
  bot.use(async (ctx, next) => {
    if (ctx.from) {
      db.upsertUser(ctx.from.id, ctx.from.username, ctx.from.first_name);
    }
    return next();
  });

  // ─── Core Commands ────────────────────────────────────────────────────────
  bot.start(handleStart);
  bot.help(handleHelp);
  bot.command('menu', handleStart);

  // ─── Wallet Commands ──────────────────────────────────────────────────────
  bot.command('wallet', walletCommands.showWallets);
  bot.command('generate', walletCommands.generateWallet);
  bot.command('import', walletCommands.importWallet);
  bot.command('balance', walletCommands.showBalance);
  bot.command('send', walletCommands.sendTokens);
  bot.command('export', walletCommands.exportPrivateKey);

  // ─── Trading Commands ─────────────────────────────────────────────────────
  bot.command('buy', tradeCommands.buyToken);
  bot.command('sell', tradeCommands.sellToken);
  bot.command('swap', tradeCommands.swapTokens);
  bot.command('history', tradeCommands.tradeHistory);

  // ─── Price Commands ───────────────────────────────────────────────────────
  bot.command('price', priceCommands.getPrice);
  bot.command('chart', priceCommands.getChart);
  bot.command('search', priceCommands.searchCoin);

  // ─── DCA Commands ─────────────────────────────────────────────────────────
  bot.command('dca', dcaCommands.showDCA);
  bot.command('newdca', dcaCommands.createDCA);
  bot.command('stopdca', dcaCommands.stopDCA);
  bot.command('dcalist', dcaCommands.listDCA);

  // ─── Alert Commands ───────────────────────────────────────────────────────
  bot.command('alert', alertCommands.createAlert);
  bot.command('alerts', alertCommands.listAlerts);
  bot.command('stopalert', alertCommands.stopAlert);

  // ─── Inline Button Callbacks ──────────────────────────────────────────────
  bot.action(/^chain_(.+)$/, walletCommands.handleChainSelect);
  bot.action(/^wallet_gen_(.+)$/, walletCommands.handleWalletGenerate);
  bot.action(/^set_default_(.+)_(.+)$/, walletCommands.handleSetDefault);
  bot.action(/^del_wallet_(.+)$/, walletCommands.handleDeleteWallet);
  bot.action(/^trade_chain_(.+)$/, tradeCommands.handleTradeChainSelect);
  bot.action(/^dca_chain_(.+)$/, dcaCommands.handleDCAChainSelect);
  bot.action(/^cancel_dca_(.+)$/, dcaCommands.handleCancelDCA);
  bot.action(/^cancel_alert_(.+)$/, alertCommands.handleCancelAlert);
  bot.action('back_main', handleStart);
  bot.action('noop', (ctx) => ctx.answerCbQuery());

  // ─── Global Error Handler ─────────────────────────────────────────────────
  bot.catch((err, ctx) => {
    logger.error(`Bot error for ${ctx.updateType}:`, err);
    const msg = err.message?.includes('not configured') || err.message?.includes('RPC URL')
      ? `⚙️ Configuration needed: ${err.message}`
      : '❌ Something went wrong. Please try again.';
    ctx.reply(msg).catch(() => {});
  });

  return bot;
}

module.exports = { createBot };

// src/bot/commands/start.js
const { Markup } = require('telegraf');

async function handleStart(ctx) {
  const firstName = ctx.from?.first_name || 'Trader';

  const welcome = [
    `🤖 *CryptoBot — Multi-Chain Trading*`,
    ``,
    `Welcome back, *${firstName}*! Ready to trade? 🚀`,
    ``,
    `I support trading on:`,
    `⟠ Ethereum  🔶 BNB Chain  🟣 Polygon`,
    `🔵 Arbitrum  🔷 Base  🔺 Avalanche  ◎ Solana`,
    ``,
    `What would you like to do?`
  ].join('\n');

  const keyboard = Markup.inlineKeyboard([
    [
      Markup.button.callback('👛 Wallets', 'menu_wallets'),
      Markup.button.callback('💱 Trade', 'menu_trade')
    ],
    [
      Markup.button.callback('📊 DCA Bots', 'menu_dca'),
      Markup.button.callback('💰 Prices', 'menu_prices')
    ],
    [
      Markup.button.callback('🔔 Alerts', 'menu_alerts'),
      Markup.button.callback('📜 History', 'menu_history')
    ],
    [
      Markup.button.callback('❓ Help', 'menu_help')
    ]
  ]);

  const method = ctx.callbackQuery ? 'editMessageText' : 'reply';

  if (ctx.callbackQuery) {
    await ctx.answerCbQuery();
    await ctx.editMessageText(welcome, { parse_mode: 'Markdown', ...keyboard });
  } else {
    await ctx.reply(welcome, { parse_mode: 'Markdown', ...keyboard });
  }

  // Handle menu callbacks inline
  ctx.telegram.on?.('callback_query', () => {});
}

// Register menu callbacks in the main bot file via action handlers
async function handleMenuWallets(ctx) {
  await ctx.answerCbQuery();
  return ctx.reply(
    '👛 *Wallet Commands*\n\n' +
    '`/wallet` — View all wallets\n' +
    '`/generate` — Generate new wallet\n' +
    '`/import` — Import from private key\n' +
    '`/balance` — Check balances\n' +
    '`/send` — Send tokens\n' +
    '`/export` — Export private key',
    { parse_mode: 'Markdown' }
  );
}

async function handleHelp(ctx) {
  const helpText = [
    `📖 *CryptoBot Help*`,
    ``,
    `*👛 WALLET COMMANDS*`,
    `\`/wallet\` — View your wallets`,
    `\`/generate [chain]\` — Generate new wallet`,
    `\`/import [chain] [key]\` — Import wallet`,
    `\`/balance [chain]\` — Check balances`,
    `\`/send [chain] [to] [amount]\` — Send tokens`,
    `\`/export [chain]\` — Export private key`,
    ``,
    `*💱 TRADING COMMANDS*`,
    `\`/buy [chain] [token] [amount]\` — Buy a token`,
    `\`/sell [chain] [token] [amount]\` — Sell a token`,
    `\`/swap [chain] [tokenIn] [tokenOut] [amount]\` — Swap tokens`,
    `\`/history\` — View trade history`,
    ``,
    `*📊 DCA COMMANDS*`,
    `\`/dca\` — DCA menu`,
    `\`/newdca\` — Create DCA order`,
    `\`/dcalist\` — View DCA orders`,
    `\`/stopdca [id]\` — Stop a DCA order`,
    ``,
    `*💰 PRICE COMMANDS*`,
    `\`/price [token]\` — Get token price`,
    `\`/search [query]\` — Search for tokens`,
    ``,
    `*🔔 ALERT COMMANDS*`,
    `\`/alert [chain] [token] [above/below] [price]\` — Set alert`,
    `\`/alerts\` — View active alerts`,
    `\`/stopalert [id]\` — Remove alert`,
    ``,
    `*SUPPORTED CHAINS:*`,
    `\`ethereum\` \`bsc\` \`polygon\` \`arbitrum\` \`base\` \`avalanche\` \`solana\``,
    ``,
    `*NATIVE TOKEN PLACEHOLDER:*`,
    `Use \`native\` for ETH/BNB/MATIC/SOL in swaps`
  ].join('\n');

  await ctx.reply(helpText, {
    parse_mode: 'Markdown',
    ...Markup.inlineKeyboard([[Markup.button.callback('« Back to Menu', 'back_main')]])
  });
}

module.exports = { handleStart, handleHelp, handleMenuWallets };

// src/bot/commands/dca.js
const { Markup } = require('telegraf');
const db = require('../../utils/database');
const { getChain, getAllChains, CHAINS } = require('../../config/chains');
const { getTokenInfo } = require('../../wallet/balanceChecker');
const logger = require('../../utils/logger');

// ─── /dca — DCA info & menu ───────────────────────────────────────────────────

async function showDCA(ctx) {
  const user = db.getUserByTelegramId(ctx.from.id);
  const orders = db.getUserDCAOrders(user.id);
  const active = orders.filter(o => o.status === 'active');

  const text = [
    `🤖 *DCA Bot Manager*`,
    ``,
    `Dollar Cost Averaging (DCA) automatically buys tokens at regular intervals, reducing the impact of volatility.`,
    ``,
    `*Your DCA Orders:*`,
    `• Active: ${active.length}`,
    `• Total: ${orders.length}`,
    ``,
    `*Commands:*`,
    `\`/newdca\` — Create new DCA order`,
    `\`/dcalist\` — View all orders`,
    `\`/stopdca [id]\` — Cancel an order`,
    ``,
    `*Example:*`,
    `Buy $50 of ETH every day:`,
    `\`/newdca ethereum native 0xUSDC 50 1440\``,
    `_(chain tokenIn tokenOut amount frequencyMinutes)_`
  ].join('\n');

  await ctx.reply(text, {
    parse_mode: 'Markdown',
    ...Markup.inlineKeyboard([
      [Markup.button.callback('➕ New DCA', 'newdca_guide')],
      [Markup.button.callback('📋 My DCA Orders', 'dcalist_inline')],
      [Markup.button.callback('« Back', 'back_main')]
    ])
  });
}

// ─── /newdca [chain] [tokenIn] [tokenOut] [amount] [frequencyMinutes] [totalOrders?] ───

async function createDCA(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const [chainArg, tokenInArg, tokenOutArg, amountArg, frequencyArg, totalOrdersArg] = args;

  if (!chainArg || !tokenInArg || !tokenOutArg || !amountArg || !frequencyArg) {
    return ctx.reply(
      '🤖 *Create DCA Order*\n\n' +
      'Usage:\n`/newdca [chain] [tokenIn] [tokenOut] [amount] [freqMinutes] [totalOrders?]`\n\n' +
      '*Examples:*\n' +
      '`/newdca ethereum native 0xUSDC 0.01 1440`\n' +
      '_Buy 0.01 ETH worth of USDC daily (1440 min)_\n\n' +
      '`/newdca bsc native 0xCAKE 0.05 60 48`\n' +
      '_Buy CAKE every hour for 48 times_\n\n' +
      '`/newdca solana native TokenMint 0.1 10080`\n' +
      '_Buy weekly with 0.1 SOL_\n\n' +
      '*Frequency presets:*\n' +
      '• 60 = hourly\n• 1440 = daily\n• 10080 = weekly',
      { parse_mode: 'Markdown' }
    );
  }

  const chain = getChain(chainArg);
  if (!chain) return ctx.reply(`❌ Unknown chain: ${chainArg}`);

  const amount = parseFloat(amountArg);
  const frequencyMinutes = parseInt(frequencyArg);
  const totalOrders = totalOrdersArg ? parseInt(totalOrdersArg) : 0;

  if (isNaN(amount) || amount <= 0) return ctx.reply('❌ Invalid amount');
  if (isNaN(frequencyMinutes) || frequencyMinutes < 1) return ctx.reply('❌ Invalid frequency (minimum 1 minute)');

  const user = db.getUserByTelegramId(ctx.from.id);
  const wallet = db.getDefaultWallet(user.id, chainArg);
  if (!wallet) return ctx.reply(`❌ No default wallet for ${chain.name}. Use /generate ${chainArg}`);

  // Resolve native token
  const NATIVE = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE';
  const { SOL_MINT } = require('../../trading/solanaSwap');
  const tokenIn = (tokenInArg.toLowerCase() === 'native')
    ? (chain.type === 'solana' ? SOL_MINT : NATIVE)
    : tokenInArg;

  let tokenInSymbol = chain.symbol;
  let tokenOutSymbol = 'TOKEN';

  if (chain.type === 'evm' && tokenIn !== NATIVE) {
    try { tokenInSymbol = (await getTokenInfo(tokenIn, chainArg)).symbol; } catch {}
  }
  if (chain.type === 'evm') {
    try { tokenOutSymbol = (await getTokenInfo(tokenOutArg, chainArg)).symbol; } catch {}
  }

  const result = db.createDCAOrder({
    userId: user.id,
    walletId: wallet.id,
    chain: chainArg,
    tokenIn,
    tokenOut: tokenOutArg,
    tokenInSymbol,
    tokenOutSymbol,
    amountPerOrder: amountArg,
    frequencyMinutes,
    totalOrders
  });

  const orderId = result.lastInsertRowid;
  const freqText = formatFrequency(frequencyMinutes);
  const nextExec = new Date(Date.now() + frequencyMinutes * 60000);

  await ctx.reply(
    `✅ *DCA Order Created!* #${orderId}\n\n` +
    `${chain.emoji} *Chain:* ${chain.name}\n` +
    `💱 *Pair:* ${tokenInSymbol} → ${tokenOutSymbol}\n` +
    `💰 *Amount:* ${amountArg} ${tokenInSymbol} per order\n` +
    `⏱ *Frequency:* ${freqText}\n` +
    `📊 *Total Orders:* ${totalOrders > 0 ? totalOrders : 'Unlimited'}\n` +
    `🕐 *First Execution:* ${nextExec.toLocaleString()}\n\n` +
    `_Use /stopdca ${orderId} to cancel_`,
    { parse_mode: 'Markdown' }
  );
}

// ─── /dcalist — List DCA orders ───────────────────────────────────────────────

async function listDCA(ctx) {
  const user = db.getUserByTelegramId(ctx.from.id);
  const orders = db.getUserDCAOrders(user.id);

  if (orders.length === 0) {
    return ctx.reply('📋 No DCA orders. Use /newdca to create one!');
  }

  let text = '📋 *Your DCA Orders*\n\n';
  const buttons = [];

  for (const order of orders) {
    const chain = CHAINS[order.chain];
    const statusEmoji = {
      active: '🟢', completed: '✅', cancelled: '🔴', paused: '⏸️'
    }[order.status] || '⚪';

    const freqText = formatFrequency(order.frequency_minutes);
    const progress = order.total_orders > 0
      ? `${order.completed_orders}/${order.total_orders}`
      : `${order.completed_orders}/∞`;

    text += `${statusEmoji} *Order #${order.id}*\n`;
    text += `  ${chain?.emoji || ''} ${chain?.name || order.chain}: ${order.token_in_symbol} → ${order.token_out_symbol}\n`;
    text += `  💰 ${order.amount_per_order} ${order.token_in_symbol} | ⏱ ${freqText}\n`;
    text += `  📊 Progress: ${progress}\n`;

    if (order.next_execution && order.status === 'active') {
      const nextExec = new Date(order.next_execution);
      text += `  🕐 Next: ${nextExec.toLocaleString()}\n`;
    }
    text += '\n';

    if (order.status === 'active') {
      buttons.push([Markup.button.callback(`❌ Stop #${order.id}`, `cancel_dca_${order.id}`)]);
    }
  }

  buttons.push([Markup.button.callback('« Back', 'back_main')]);

  await ctx.reply(text, {
    parse_mode: 'Markdown',
    ...Markup.inlineKeyboard(buttons)
  });
}

// ─── /stopdca [id] ────────────────────────────────────────────────────────────

async function stopDCA(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const orderId = parseInt(args[0]);

  if (!orderId) {
    return ctx.reply('Usage: `/stopdca [orderId]`\nExample: `/stopdca 3`', { parse_mode: 'Markdown' });
  }

  const user = db.getUserByTelegramId(ctx.from.id);
  const result = db.cancelDCAOrder(orderId, user.id);

  if (result.changes === 0) {
    return ctx.reply(`❌ DCA Order #${orderId} not found or already cancelled.`);
  }

  await ctx.reply(`🔴 *DCA Order #${orderId} Cancelled*\n\nThe bot will stop buying at the next scheduled interval.`, { parse_mode: 'Markdown' });
}

async function handleDCAChainSelect(ctx) {
  await ctx.answerCbQuery();
  const chain = ctx.match[1];
  await ctx.reply(`Selected ${chain} for DCA. Use /newdca ${chain} to set up your order.`);
}

async function handleCancelDCA(ctx) {
  await ctx.answerCbQuery();
  const orderId = parseInt(ctx.match[1]);
  const user = db.getUserByTelegramId(ctx.from.id);
  const result = db.cancelDCAOrder(orderId, user.id);

  if (result.changes === 0) {
    return ctx.editMessageText(`❌ Could not cancel DCA Order #${orderId}`);
  }

  await ctx.editMessageText(
    `🔴 *DCA Order #${orderId} Cancelled*`,
    { parse_mode: 'Markdown' }
  );
}

function formatFrequency(minutes) {
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h`;
  if (minutes < 10080) return `${Math.floor(minutes / 1440)}d`;
  return `${Math.floor(minutes / 10080)}w`;
}

module.exports = { showDCA, createDCA, listDCA, stopDCA, handleDCAChainSelect, handleCancelDCA };

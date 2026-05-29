// src/bot/commands/alerts.js
const { Markup } = require('telegraf');
const db = require('../../utils/database');
const { getChain, CHAINS } = require('../../config/chains');
const { formatPrice } = require('../../trading/priceService');

// ─── /alert [chain] [tokenAddress] [above|below] [price] ─────────────────────

async function createAlert(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const [chainArg, tokenAddress, condition, targetPriceArg] = args;

  if (!chainArg || !tokenAddress || !condition || !targetPriceArg) {
    return ctx.reply(
      '🔔 *Create Price Alert*\n\n' +
      'Usage: `/alert [chain] [tokenAddress] [above|below] [price]`\n\n' +
      'Examples:\n' +
      '`/alert ethereum 0xTokenAddress above 1.50` — Alert when > $1.50\n' +
      '`/alert solana TokenMint below 0.001` — Alert when < $0.001\n\n' +
      'For native tokens use: `native` as address',
      { parse_mode: 'Markdown' }
    );
  }

  const chain = getChain(chainArg);
  if (!chain) return ctx.reply(`❌ Unknown chain: ${chainArg}`);

  if (!['above', 'below'].includes(condition.toLowerCase())) {
    return ctx.reply('❌ Condition must be `above` or `below`', { parse_mode: 'Markdown' });
  }

  const targetPrice = parseFloat(targetPriceArg);
  if (isNaN(targetPrice) || targetPrice <= 0) {
    return ctx.reply('❌ Invalid price. Must be a positive number.');
  }

  const user = db.getUserByTelegramId(ctx.from.id);

  let tokenSymbol = tokenAddress.slice(0, 8);
  if (tokenAddress.toLowerCase() === 'native') {
    tokenSymbol = chain.symbol;
  }

  try {
    const result = db.createPriceAlert({
      userId: user.id,
      chain: chainArg,
      tokenAddress: tokenAddress.toLowerCase() === 'native'
        ? (chain.type === 'solana' ? 'So11111111111111111111111111111111111111112' : '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE')
        : tokenAddress,
      tokenSymbol,
      condition: condition.toLowerCase(),
      targetPrice
    });

    const alertId = result.lastInsertRowid;
    const conditionText = condition.toLowerCase() === 'above' ? '📈 rises above' : '📉 falls below';

    await ctx.reply(
      `🔔 *Price Alert Set!* #${alertId}\n\n` +
      `${chain.emoji} *Chain:* ${chain.name}\n` +
      `🎯 *Token:* ${tokenSymbol}\n` +
      `📊 *Alert when price ${conditionText}:* ${formatPrice(targetPrice)}\n\n` +
      `_Checks every 2 minutes. Use /stopalert ${alertId} to remove._`,
      { parse_mode: 'Markdown' }
    );
  } catch (err) {
    await ctx.reply(`❌ Failed to create alert: ${err.message}`);
  }
}

// ─── /alerts — List active alerts ────────────────────────────────────────────

async function listAlerts(ctx) {
  const user = db.getUserByTelegramId(ctx.from.id);
  const alerts = db.getUserAlerts(user.id);

  if (alerts.length === 0) {
    return ctx.reply('🔔 No price alerts. Use /alert to create one!');
  }

  let text = '🔔 *Your Price Alerts*\n\n';
  const buttons = [];

  for (const alert of alerts) {
    const chain = CHAINS[alert.chain];
    const statusEmoji = { active: '🟢', triggered: '✅', cancelled: '🔴' }[alert.status] || '⚪';
    const condIcon = alert.condition === 'above' ? '📈' : '📉';
    const shortAddr = alert.token_address.length > 12
      ? `${alert.token_address.slice(0, 8)}...`
      : alert.token_address;

    text += `${statusEmoji} *Alert #${alert.id}*\n`;
    text += `  ${chain?.emoji || ''} ${chain?.name || alert.chain}: ${alert.token_symbol || shortAddr}\n`;
    text += `  ${condIcon} ${alert.condition} ${formatPrice(alert.target_price)}\n`;
    if (alert.current_price) {
      text += `  Now: ${formatPrice(alert.current_price)}\n`;
    }
    text += '\n';

    if (alert.status === 'active') {
      buttons.push([Markup.button.callback(`❌ Cancel #${alert.id}`, `cancel_alert_${alert.id}`)]);
    }
  }

  buttons.push([Markup.button.callback('« Back', 'back_main')]);

  await ctx.reply(text, {
    parse_mode: 'Markdown',
    ...Markup.inlineKeyboard(buttons)
  });
}

// ─── /stopalert [id] ─────────────────────────────────────────────────────────

async function stopAlert(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const alertId = parseInt(args[0]);

  if (!alertId) {
    return ctx.reply('Usage: `/stopalert [alertId]`\nExample: `/stopalert 5`', { parse_mode: 'Markdown' });
  }

  const user = db.getUserByTelegramId(ctx.from.id);
  const result = db.cancelAlert(alertId, user.id);

  if (result.changes === 0) {
    return ctx.reply(`❌ Alert #${alertId} not found.`);
  }

  await ctx.reply(`🔕 *Alert #${alertId} Cancelled*`, { parse_mode: 'Markdown' });
}

async function handleCancelAlert(ctx) {
  await ctx.answerCbQuery();
  const alertId = parseInt(ctx.match[1]);
  const user = db.getUserByTelegramId(ctx.from.id);
  const result = db.cancelAlert(alertId, user.id);

  if (result.changes === 0) {
    return ctx.editMessageText(`❌ Could not cancel Alert #${alertId}`);
  }

  await ctx.editMessageText(`🔕 *Alert #${alertId} Cancelled*`, { parse_mode: 'Markdown' });
}

module.exports = { createAlert, listAlerts, stopAlert, handleCancelAlert };

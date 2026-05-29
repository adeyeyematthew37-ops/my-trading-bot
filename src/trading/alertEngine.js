// src/trading/alertEngine.js
const cron = require('node-cron');
const db = require('../utils/database');
const { getTokenPriceDexScreener, getSolanaTokenPrice } = require('./priceService');
const logger = require('../utils/logger');

let bot = null;

function initAlertEngine(telegramBot) {
  bot = telegramBot;

  // Check price alerts every 2 minutes
  cron.schedule('*/2 * * * *', async () => {
    await checkPriceAlerts();
  });

  logger.info('Price alert engine initialized');
}

async function checkPriceAlerts() {
  const alerts = db.getActivePriceAlerts();
  if (alerts.length === 0) return;

  for (const alert of alerts) {
    try {
      let priceData;
      if (alert.chain === 'solana') {
        priceData = await getSolanaTokenPrice(alert.token_address);
      } else {
        priceData = await getTokenPriceDexScreener(alert.chain, alert.token_address);
      }

      if (!priceData) continue;
      const currentPrice = priceData.price;

      // Update current price in DB
      db.getDB().prepare('UPDATE price_alerts SET current_price = ? WHERE id = ?')
        .run(currentPrice, alert.id);

      const shouldTrigger =
        (alert.condition === 'above' && currentPrice >= alert.target_price) ||
        (alert.condition === 'below' && currentPrice <= alert.target_price);

      if (shouldTrigger) {
        db.triggerPriceAlert(alert.id);
        await notifyAlert(alert, currentPrice);
      }
    } catch (err) {
      logger.warn(`Alert check failed for alert ${alert.id}: ${err.message}`);
    }
  }
}

async function notifyAlert(alert, currentPrice) {
  if (!bot) return;
  const direction = alert.condition === 'above' ? '📈 Above' : '📉 Below';
  const msg = [
    `🔔 *Price Alert Triggered!*`,
    ``,
    `Token: *${alert.token_symbol || alert.token_address.slice(0, 8) + '...'}*`,
    `Chain: ${alert.chain}`,
    `Condition: ${direction} $${alert.target_price}`,
    `Current Price: $${currentPrice.toFixed(6)}`
  ].join('\n');

  try {
    await bot.telegram.sendMessage(alert.telegram_id, msg, { parse_mode: 'Markdown' });
  } catch (err) {
    logger.warn(`Failed to send alert notification: ${err.message}`);
  }
}

module.exports = { initAlertEngine };

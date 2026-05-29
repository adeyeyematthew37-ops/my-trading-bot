// src/index.js
require('dotenv').config();
const logger = require('./utils/logger');
const { initDatabase } = require('./utils/database');
const { createBot } = require('./bot/index');
const { initDCAEngine } = require('./trading/dcaEngine');
const { initAlertEngine } = require('./trading/alertEngine');

async function main() {
  logger.info('🚀 Starting CryptoBot...');

  // Validate environment
  const requiredVars = ['TELEGRAM_BOT_TOKEN', 'ENCRYPTION_KEY'];
  for (const varName of requiredVars) {
    if (!process.env[varName] || process.env[varName].includes('your_') || process.env[varName].includes('YOUR_')) {
      logger.error(`❌ Missing required environment variable: ${varName}`);
      logger.error('Please copy .env.example to .env and fill in your values');
      process.exit(1);
    }
  }

  // Initialize database
  initDatabase();
  logger.info('✅ Database initialized');

  // Create Telegram bot
  const bot = createBot();
  logger.info('✅ Telegram bot created');

  // Initialize automation engines
  initDCAEngine(bot);
  initAlertEngine(bot);
  logger.info('✅ DCA & Alert engines started');

  // Start bot
  await bot.launch({
    dropPendingUpdates: true
  });

  logger.info('✅ Bot is running! Send /start on Telegram');
  logger.info(`Bot username: @${bot.botInfo?.username || 'unknown'}`);

  // Graceful shutdown
  process.once('SIGINT', () => {
    logger.info('Shutting down...');
    bot.stop('SIGINT');
  });
  process.once('SIGTERM', () => {
    logger.info('Shutting down...');
    bot.stop('SIGTERM');
  });
}

main().catch(err => {
  logger.error('Fatal error:', err);
  process.exit(1);
});

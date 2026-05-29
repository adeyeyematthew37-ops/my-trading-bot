// src/trading/dcaEngine.js
const cron = require('node-cron');
const { ethers } = require('ethers');
const db = require('../utils/database');
const { executeEVMSwap } = require('./evmSwap');
const { executeSolanaSwap } = require('./solanaSwap');
const { CHAINS } = require('../config/chains');
const logger = require('../utils/logger');

let bot = null; // Telegram bot reference for notifications

/**
 * Initialize DCA engine with bot reference
 */
function initDCAEngine(telegramBot) {
  bot = telegramBot;
  logger.info('DCA engine initialized');

  // Run every minute to check for due orders
  const intervalMinutes = parseInt(process.env.DCA_CHECK_INTERVAL_MINUTES) || 1;
  const cronExpr = `*/${intervalMinutes} * * * *`;

  cron.schedule(cronExpr, async () => {
    await processDueOrders();
  });

  logger.info(`DCA cron job scheduled every ${intervalMinutes} minute(s)`);
}

/**
 * Process all DCA orders that are due for execution
 */
async function processDueOrders() {
  let orders;
  try {
    orders = db.getActiveDCAOrders();
  } catch (err) {
    logger.error('Failed to fetch DCA orders:', err);
    return;
  }

  if (orders.length === 0) return;
  logger.info(`Processing ${orders.length} DCA order(s)`);

  for (const order of orders) {
    await executeDCAOrder(order);
  }
}

/**
 * Execute a single DCA order
 */
async function executeDCAOrder(order) {
  logger.info(`Executing DCA order #${order.id} for user ${order.telegram_id}`);

  const user = db.getUserByTelegramId(order.telegram_id);
  if (!user) {
    logger.error(`User not found for DCA order ${order.id}`);
    return;
  }

  const chain = CHAINS[order.chain];
  if (!chain) {
    logger.error(`Invalid chain ${order.chain} for DCA order ${order.id}`);
    return;
  }

  // Save trade record
  const tradeRecord = db.saveTrade({
    userId: order.user_id,
    walletId: order.wallet_id,
    chain: order.chain,
    type: 'dca',
    tokenIn: order.token_in,
    tokenOut: order.token_out,
    tokenInSymbol: order.token_in_symbol,
    tokenOutSymbol: order.token_out_symbol,
    amountIn: order.amount_per_order,
    status: 'pending',
    dcaOrderId: order.id
  });

  try {
    let result;

    if (chain.type === 'evm') {
      // Parse amount (stored as string, could be in ether or wei)
      let amountIn;
      try {
        // Try parsing as ether amount first
        amountIn = ethers.parseEther(order.amount_per_order);
      } catch {
        amountIn = BigInt(order.amount_per_order);
      }

      result = await executeEVMSwap({
        chainKey: order.chain,
        encryptedPrivateKey: order.encrypted_private_key,
        tokenIn: order.token_in,
        tokenOut: order.token_out,
        amountIn: amountIn.toString(),
        slippagePercent: 1.5,
        userAddress: order.address
      });
    } else if (chain.type === 'solana') {
      const { LAMPORTS_PER_SOL } = require('@solana/web3.js');
      const amountLamports = Math.floor(parseFloat(order.amount_per_order) * LAMPORTS_PER_SOL);

      result = await executeSolanaSwap({
        encryptedPrivateKey: order.encrypted_private_key,
        inputMint: order.token_in,
        outputMint: order.token_out,
        amountLamports,
        slippageBps: 150,
        userAddress: order.address
      });
    }

    // Update trade record
    const tradeId = tradeRecord.lastInsertRowid;
    db.getDB().prepare(
      'UPDATE trades SET tx_hash = ?, status = ?, amount_out = ? WHERE rowid = ?'
    ).run(result.txHash, result.status, result.amountOut || null, tradeId);

    // Update DCA order
    const completedOrders = order.completed_orders + 1;
    const nextExecution = new Date(Date.now() + order.frequency_minutes * 60000).toISOString();
    const isComplete = order.total_orders > 0 && completedOrders >= order.total_orders;

    db.updateDCAOrder(order.id, {
      completed_orders: completedOrders,
      next_execution: nextExecution,
      status: isComplete ? 'completed' : 'active'
    });

    // Notify user
    const explorerUrl = `${chain.explorer}/tx/${result.txHash}`;
    const notifMsg = [
      `✅ *DCA Order Executed* #${order.id}`,
      ``,
      `${chain.emoji} *Chain:* ${chain.name}`,
      `💱 *Pair:* ${order.token_in_symbol || 'Token'} → ${order.token_out_symbol || 'Token'}`,
      `💰 *Amount:* ${order.amount_per_order} ${order.token_in_symbol || ''}`,
      `📊 *Orders:* ${completedOrders}${order.total_orders > 0 ? `/${order.total_orders}` : ' (unlimited)'}`,
      ``,
      `[View Transaction](${explorerUrl})`,
      isComplete ? `\n🎉 DCA order completed!` : `\n⏱ Next: ${new Date(nextExecution).toLocaleString()}`
    ].join('\n');

    await sendNotification(order.telegram_id, notifMsg);
    logger.info(`DCA order #${order.id} executed successfully: ${result.txHash}`);

  } catch (err) {
    logger.error(`DCA order #${order.id} failed:`, err.message);

    const tradeId = tradeRecord.lastInsertRowid;
    db.getDB().prepare(
      'UPDATE trades SET status = ?, error_message = ? WHERE rowid = ?'
    ).run('failed', err.message, tradeId);

    // Update next execution even on failure (retry next interval)
    const nextExecution = new Date(Date.now() + order.frequency_minutes * 60000).toISOString();
    db.updateDCAOrder(order.id, { next_execution: nextExecution });

    await sendNotification(order.telegram_id,
      `❌ *DCA Order #${order.id} Failed*\n\n` +
      `${chain.emoji} ${chain.name}: ${order.token_in_symbol} → ${order.token_out_symbol}\n` +
      `Error: ${err.message}\n\nWill retry at next scheduled interval.`
    );
  }
}

async function sendNotification(telegramId, message) {
  if (!bot) return;
  try {
    await bot.telegram.sendMessage(telegramId, message, { parse_mode: 'Markdown' });
  } catch (err) {
    logger.warn(`Failed to send notification to ${telegramId}: ${err.message}`);
  }
}

module.exports = { initDCAEngine, processDueOrders };

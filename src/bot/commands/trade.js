// src/bot/commands/trade.js
const { Markup } = require('telegraf');
const { ethers } = require('ethers');
const db = require('../../utils/database');
const { executeEVMSwap } = require('../../trading/evmSwap');
const { executeSolanaSwap, SOL_MINT } = require('../../trading/solanaSwap');
const { getTokenInfo } = require('../../wallet/balanceChecker');
const { getChain, CHAINS } = require('../../config/chains');
const { formatPrice } = require('../../trading/priceService');
const logger = require('../../utils/logger');

const NATIVE = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE';

function parseNativeToken(tokenArg, chain) {
  if (!tokenArg) return null;
  if (tokenArg.toLowerCase() === 'native' || tokenArg.toLowerCase() === chain.symbol.toLowerCase()) {
    return chain.type === 'solana' ? SOL_MINT : NATIVE;
  }
  return tokenArg;
}

// ─── /buy [chain] [tokenAddress] [amountNative] ───────────────────────────────

async function buyToken(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const [chainArg, tokenAddress, amountArg] = args;

  if (!chainArg || !tokenAddress || !amountArg) {
    return ctx.reply(
      '📈 *Buy Token*\n\n' +
      'Usage: `/buy [chain] [tokenAddress] [amount]`\n\n' +
      'Examples:\n' +
      '`/buy ethereum 0xTokenAddress 0.01`\n' +
      '`/buy bsc 0xTokenAddress 0.05`\n' +
      '`/buy solana TokenMintAddress 0.1`\n\n' +
      '`amount` is in native token (ETH/BNB/SOL etc)',
      { parse_mode: 'Markdown' }
    );
  }

  const chain = getChain(chainArg);
  if (!chain) return ctx.reply(`❌ Unknown chain: ${chainArg}`);

  const user = db.getUserByTelegramId(ctx.from.id);
  const wallet = db.getDefaultWallet(user.id, chainArg);
  if (!wallet) return ctx.reply(`❌ No default wallet for ${chain.name}.\nUse /generate ${chainArg}`);

  await ctx.reply(`⏳ Preparing buy order on ${chain.emoji} ${chain.name}...`);

  try {
    const amount = parseFloat(amountArg);
    if (isNaN(amount) || amount <= 0) throw new Error('Invalid amount');

    let txResult;
    let tokenSymbol = 'TOKEN';

    if (chain.type === 'evm') {
      // Get token info
      try {
        const tokenInfo = await getTokenInfo(tokenAddress, chainArg);
        tokenSymbol = tokenInfo.symbol;
      } catch {}

      const amountWei = ethers.parseEther(amountArg);
      txResult = await executeEVMSwap({
        chainKey: chainArg,
        encryptedPrivateKey: wallet.encrypted_private_key,
        tokenIn: NATIVE,
        tokenOut: tokenAddress,
        amountIn: amountWei.toString(),
        slippagePercent: parseFloat(process.env.MAX_SLIPPAGE_PERCENT) || 1.0,
        userAddress: wallet.address
      });
    } else if (chain.type === 'solana') {
      const { LAMPORTS_PER_SOL } = require('@solana/web3.js');
      const lamports = Math.floor(amount * LAMPORTS_PER_SOL);
      txResult = await executeSolanaSwap({
        encryptedPrivateKey: wallet.encrypted_private_key,
        inputMint: SOL_MINT,
        outputMint: tokenAddress,
        amountLamports: lamports,
        slippageBps: 150,
        userAddress: wallet.address
      });
    }

    // Save trade to DB
    db.saveTrade({
      userId: user.id,
      walletId: wallet.id,
      chain: chainArg,
      type: 'buy',
      tokenIn: chain.type === 'solana' ? SOL_MINT : NATIVE,
      tokenOut: tokenAddress,
      tokenInSymbol: chain.symbol,
      tokenOutSymbol: tokenSymbol,
      amountIn: amountArg,
      amountOut: txResult.amountOut,
      txHash: txResult.txHash,
      status: txResult.status
    });

    const explorerUrl = `${chain.explorer}/tx/${txResult.txHash}`;
    await ctx.reply(
      `✅ *Buy Order Executed!*\n\n` +
      `${chain.emoji} *Chain:* ${chain.name}\n` +
      `💰 *Spent:* ${amountArg} ${chain.symbol}\n` +
      `🎯 *Token:* ${tokenSymbol} (\`${tokenAddress.slice(0, 10)}...\`)\n` +
      `📊 *Status:* ${txResult.status === 'success' ? '✅ Success' : '❌ Failed'}\n\n` +
      `[View Transaction](${explorerUrl})`,
      { parse_mode: 'Markdown' }
    );
  } catch (err) {
    logger.error('Buy failed:', err.message);
    await ctx.reply(`❌ *Buy Failed*\n\n${err.message}`, { parse_mode: 'Markdown' });
  }
}

// ─── /sell [chain] [tokenAddress] [amount] ────────────────────────────────────

async function sellToken(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const [chainArg, tokenAddress, amountArg] = args;

  if (!chainArg || !tokenAddress || !amountArg) {
    return ctx.reply(
      '📉 *Sell Token*\n\n' +
      'Usage: `/sell [chain] [tokenAddress] [amount]`\n\n' +
      'Examples:\n' +
      '`/sell ethereum 0xTokenAddress 100` — Sell 100 tokens\n' +
      '`/sell solana TokenMintAddress 50`\n\n' +
      '`amount` is in token units',
      { parse_mode: 'Markdown' }
    );
  }

  const chain = getChain(chainArg);
  if (!chain) return ctx.reply(`❌ Unknown chain: ${chainArg}`);

  const user = db.getUserByTelegramId(ctx.from.id);
  const wallet = db.getDefaultWallet(user.id, chainArg);
  if (!wallet) return ctx.reply(`❌ No default wallet for ${chain.name}`);

  await ctx.reply(`⏳ Preparing sell order on ${chain.emoji} ${chain.name}...`);

  try {
    let txResult;
    let tokenSymbol = 'TOKEN';
    let decimals = 18;

    if (chain.type === 'evm') {
      try {
        const tokenInfo = await getTokenInfo(tokenAddress, chainArg);
        tokenSymbol = tokenInfo.symbol;
        decimals = tokenInfo.decimals;
      } catch {}

      const amountRaw = ethers.parseUnits(amountArg, decimals);
      txResult = await executeEVMSwap({
        chainKey: chainArg,
        encryptedPrivateKey: wallet.encrypted_private_key,
        tokenIn: tokenAddress,
        tokenOut: NATIVE,
        amountIn: amountRaw.toString(),
        slippagePercent: parseFloat(process.env.MAX_SLIPPAGE_PERCENT) || 1.0,
        userAddress: wallet.address
      });
    } else if (chain.type === 'solana') {
      // For Solana, amount in token units (need to know decimals)
      const amountLamports = Math.floor(parseFloat(amountArg) * 1e6); // assuming 6 decimals
      txResult = await executeSolanaSwap({
        encryptedPrivateKey: wallet.encrypted_private_key,
        inputMint: tokenAddress,
        outputMint: SOL_MINT,
        amountLamports,
        slippageBps: 150,
        userAddress: wallet.address
      });
    }

    db.saveTrade({
      userId: user.id,
      walletId: wallet.id,
      chain: chainArg,
      type: 'sell',
      tokenIn: tokenAddress,
      tokenOut: chain.type === 'solana' ? SOL_MINT : NATIVE,
      tokenInSymbol: tokenSymbol,
      tokenOutSymbol: chain.symbol,
      amountIn: amountArg,
      amountOut: txResult.amountOut,
      txHash: txResult.txHash,
      status: txResult.status
    });

    const explorerUrl = `${chain.explorer}/tx/${txResult.txHash}`;
    await ctx.reply(
      `✅ *Sell Order Executed!*\n\n` +
      `${chain.emoji} *Chain:* ${chain.name}\n` +
      `💱 *Sold:* ${amountArg} ${tokenSymbol}\n` +
      `💰 *Received:* ${chain.symbol}\n` +
      `📊 *Status:* ${txResult.status === 'success' ? '✅ Success' : '❌ Failed'}\n\n` +
      `[View Transaction](${explorerUrl})`,
      { parse_mode: 'Markdown' }
    );
  } catch (err) {
    logger.error('Sell failed:', err.message);
    await ctx.reply(`❌ *Sell Failed*\n\n${err.message}`, { parse_mode: 'Markdown' });
  }
}

// ─── /swap [chain] [tokenIn] [tokenOut] [amount] ─────────────────────────────

async function swapTokens(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const [chainArg, tokenInArg, tokenOutArg, amountArg] = args;

  if (!chainArg || !tokenInArg || !tokenOutArg || !amountArg) {
    return ctx.reply(
      '💱 *Swap Tokens*\n\n' +
      'Usage: `/swap [chain] [tokenIn] [tokenOut] [amount]`\n\n' +
      'Examples:\n' +
      '`/swap ethereum native 0xUSDC 0.01` — ETH → USDC\n' +
      '`/swap bsc 0xBUSD native 10` — BUSD → BNB\n' +
      '`/swap solana native TokenMint 0.5` — SOL → Token\n\n' +
      'Use `native` for ETH/BNB/SOL',
      { parse_mode: 'Markdown' }
    );
  }

  const chain = getChain(chainArg);
  if (!chain) return ctx.reply(`❌ Unknown chain: ${chainArg}`);

  const tokenIn = parseNativeToken(tokenInArg, chain);
  const tokenOut = parseNativeToken(tokenOutArg, chain);

  const user = db.getUserByTelegramId(ctx.from.id);
  const wallet = db.getDefaultWallet(user.id, chainArg);
  if (!wallet) return ctx.reply(`❌ No default wallet for ${chain.name}`);

  await ctx.reply(`⏳ Executing swap on ${chain.emoji} ${chain.name}...`);

  try {
    let txResult;

    if (chain.type === 'evm') {
      const isNativeIn = tokenIn === NATIVE;
      let amountWei;
      if (isNativeIn) {
        amountWei = ethers.parseEther(amountArg);
      } else {
        let decimals = 18;
        try {
          const info = await getTokenInfo(tokenIn, chainArg);
          decimals = info.decimals;
        } catch {}
        amountWei = ethers.parseUnits(amountArg, decimals);
      }

      txResult = await executeEVMSwap({
        chainKey: chainArg,
        encryptedPrivateKey: wallet.encrypted_private_key,
        tokenIn,
        tokenOut,
        amountIn: amountWei.toString(),
        slippagePercent: parseFloat(process.env.MAX_SLIPPAGE_PERCENT) || 1.0,
        userAddress: wallet.address
      });
    } else if (chain.type === 'solana') {
      const { LAMPORTS_PER_SOL } = require('@solana/web3.js');
      const isNativeIn = tokenIn === SOL_MINT;
      const amountLamports = isNativeIn
        ? Math.floor(parseFloat(amountArg) * LAMPORTS_PER_SOL)
        : Math.floor(parseFloat(amountArg) * 1e6);

      txResult = await executeSolanaSwap({
        encryptedPrivateKey: wallet.encrypted_private_key,
        inputMint: tokenIn,
        outputMint: tokenOut,
        amountLamports,
        slippageBps: 150,
        userAddress: wallet.address
      });
    }

    db.saveTrade({
      userId: user.id,
      walletId: wallet.id,
      chain: chainArg,
      type: 'swap',
      tokenIn,
      tokenOut,
      amountIn: amountArg,
      amountOut: txResult.amountOut,
      txHash: txResult.txHash,
      status: txResult.status
    });

    const explorerUrl = `${chain.explorer}/tx/${txResult.txHash}`;
    await ctx.reply(
      `✅ *Swap Executed!*\n\n` +
      `${chain.emoji} *Chain:* ${chain.name}\n` +
      `💱 *Swapped:* ${amountArg} ${tokenInArg} → ${tokenOutArg}\n` +
      `📊 *Status:* ${txResult.status === 'success' ? '✅ Success' : '❌ Failed'}\n\n` +
      `[View Transaction](${explorerUrl})`,
      { parse_mode: 'Markdown' }
    );
  } catch (err) {
    logger.error('Swap failed:', err.message);
    await ctx.reply(`❌ *Swap Failed*\n\n${err.message}`, { parse_mode: 'Markdown' });
  }
}

// ─── /history ─────────────────────────────────────────────────────────────────

async function tradeHistory(ctx) {
  const user = db.getUserByTelegramId(ctx.from.id);
  const trades = db.getUserTrades(user.id, 10);

  if (trades.length === 0) {
    return ctx.reply('📜 No trades yet. Use /buy or /swap to get started!');
  }

  let text = '📜 *Recent Trades*\n\n';
  for (const trade of trades) {
    const chain = CHAINS[trade.chain];
    const date = new Date(trade.created_at).toLocaleDateString();
    const typeEmoji = { buy: '📈', sell: '📉', swap: '💱', dca: '🤖' }[trade.type] || '💱';
    const statusEmoji = trade.status === 'success' ? '✅' : trade.status === 'pending' ? '⏳' : '❌';
    const shortHash = trade.tx_hash ? `\`${trade.tx_hash.slice(0, 10)}...\`` : 'N/A';

    text += `${typeEmoji} *${trade.type.toUpperCase()}* — ${chain?.emoji || ''} ${chain?.name || trade.chain}\n`;
    text += `  ${trade.token_in_symbol || 'Token'} → ${trade.token_out_symbol || 'Token'}\n`;
    text += `  Amount: ${trade.amount_in} | ${statusEmoji} | ${date}\n`;
    if (trade.tx_hash) {
      text += `  Tx: ${shortHash}\n`;
    }
    text += '\n';
  }

  await ctx.reply(text, { parse_mode: 'Markdown' });
}

async function handleTradeChainSelect(ctx) {
  await ctx.answerCbQuery();
  const chain = ctx.match[1];
  await ctx.reply(`Selected ${chain} for trading. Use /buy ${chain} or /swap ${chain}`);
}

module.exports = { buyToken, sellToken, swapTokens, tradeHistory, handleTradeChainSelect };

// src/bot/commands/wallet.js
const { Markup } = require('telegraf');
const { encrypt } = require('../../utils/encryption');
const db = require('../../utils/database');
const {
  generateEVMWallet, generateSolanaWallet,
  walletFromPrivateKey, formatWalletDisplay
} = require('../../wallet/walletGenerator');
const { getWalletBalances, getGasPrice } = require('../../wallet/balanceChecker');
const { getAllChains, getChain, CHAINS } = require('../../config/chains');
const logger = require('../../utils/logger');

const NATIVE = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE';

// ─── /wallet — Show all wallets ───────────────────────────────────────────────

async function showWallets(ctx) {
  const user = db.getUserByTelegramId(ctx.from.id);
  const wallets = db.getUserWallets(user.id);

  if (wallets.length === 0) {
    return ctx.reply(
      '👛 *No wallets yet.*\n\nUse `/generate [chain]` to create your first wallet!\n\nExample: `/generate ethereum`',
      {
        parse_mode: 'Markdown',
        ...Markup.inlineKeyboard([
          [Markup.button.callback('🆕 Generate Wallet', 'menu_gen_wallet')],
          [Markup.button.callback('« Back', 'back_main')]
        ])
      }
    );
  }

  // Group by chain
  const grouped = {};
  wallets.forEach(w => {
    if (!grouped[w.chain]) grouped[w.chain] = [];
    grouped[w.chain].push(w);
  });

  let text = '👛 *Your Wallets*\n\n';
  for (const [chain, chainWallets] of Object.entries(grouped)) {
    const chainInfo = CHAINS[chain];
    text += `${chainInfo?.emoji || '🔗'} *${chainInfo?.name || chain}*\n`;
    chainWallets.forEach((w, i) => {
      const shortAddr = `${w.address.slice(0, 8)}...${w.address.slice(-6)}`;
      text += `  ${w.is_default ? '✅' : '  '} [${w.id}] \`${shortAddr}\` — ${w.label}\n`;
    });
    text += '\n';
  }

  text += `_Total: ${wallets.length} wallet(s)_\n\n`;
  text += 'Use `/balance [chain]` to check balances\nUse `/export [chain]` to export keys';

  const buttons = [
    [
      Markup.button.callback('➕ Generate New', 'show_chains_gen'),
      Markup.button.callback('📥 Import', 'show_chains_import')
    ],
    [Markup.button.callback('« Back', 'back_main')]
  ];

  await ctx.reply(text, {
    parse_mode: 'Markdown',
    ...Markup.inlineKeyboard(buttons)
  });
}

// ─── /generate [chain] ────────────────────────────────────────────────────────

async function generateWallet(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const chainArg = args[0]?.toLowerCase();

  if (!chainArg) {
    const chainButtons = buildChainButtons('wallet_gen');
    return ctx.reply(
      '🔗 *Select a chain to generate a wallet for:*',
      { parse_mode: 'Markdown', ...Markup.inlineKeyboard(chainButtons) }
    );
  }

  await doGenerateWallet(ctx, chainArg);
}

async function handleWalletGenerate(ctx) {
  await ctx.answerCbQuery();
  const chainKey = ctx.match[1];
  await doGenerateWallet(ctx, chainKey);
}

async function doGenerateWallet(ctx, chainKey) {
  const chain = getChain(chainKey);
  if (!chain) {
    return ctx.reply(`❌ Unknown chain: \`${chainKey}\`\n\nSupported: ethereum, bsc, polygon, arbitrum, base, avalanche, solana`, { parse_mode: 'Markdown' });
  }

  const user = db.getUserByTelegramId(ctx.from.id);
  const existing = db.getUserWallets(user.id, chain.key || chainKey);

  const MAX_WALLETS = parseInt(process.env.MAX_WALLETS_PER_USER) || 5;
  if (existing.length >= MAX_WALLETS) {
    return ctx.reply(`⚠️ You already have ${MAX_WALLETS} wallets on ${chain.name}. Delete one first.`);
  }

  const walletData = chain.type === 'solana'
    ? generateSolanaWallet()
    : generateEVMWallet();

  const encryptedKey = encrypt(walletData.privateKey);
  db.saveWallet(user.id, chainKey, walletData.address, encryptedKey, `${chain.name} Wallet`);

  const warningText = [
    `✅ *New ${chain.emoji} ${chain.name} Wallet Created!*`,
    ``,
    `📍 *Address:*`,
    `\`${walletData.address}\``,
    ``,
    walletData.mnemonic ? `🔑 *Recovery Phrase (SAVE THIS!):*\n\`${walletData.mnemonic}\`\n` : '',
    `⚠️ *SECURITY WARNING*`,
    `• Never share your private key or seed phrase`,
    `• Store it offline in a secure location`,
    `• This bot encrypts keys but use at your own risk`,
    `• This is a DEMO bot — don't store large amounts`,
    ``,
    `Use \`/balance ${chainKey}\` to check your balance`
  ].filter(Boolean).join('\n');

  const reply = ctx.callbackQuery ? ctx.editMessageText.bind(ctx) : ctx.reply.bind(ctx);
  await reply(warningText, {
    parse_mode: 'Markdown',
    ...Markup.inlineKeyboard([[Markup.button.callback('« Back', 'back_main')]])
  });
}

// ─── /import [chain] [privateKey] ────────────────────────────────────────────

async function importWallet(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const chainArg = args[0]?.toLowerCase();
  const privateKey = args[1];

  if (!chainArg || !privateKey) {
    return ctx.reply(
      '📥 *Import Wallet*\n\n' +
      'Usage: `/import [chain] [privateKey]`\n\n' +
      'Example:\n`/import ethereum 0xYourPrivateKey`\n`/import solana YourBase58Key`\n\n' +
      '⚠️ Delete this message after importing for security!',
      { parse_mode: 'Markdown' }
    );
  }

  const chain = getChain(chainArg);
  if (!chain) return ctx.reply(`❌ Unknown chain: ${chainArg}`);

  try {
    const walletData = walletFromPrivateKey(privateKey, chain.type);
    const encryptedKey = encrypt(walletData.privateKey);
    const user = db.getUserByTelegramId(ctx.from.id);

    db.saveWallet(user.id, chainArg, walletData.address, encryptedKey, `Imported ${chain.name}`);

    await ctx.reply(
      `✅ *Wallet Imported!*\n\n` +
      `${chain.emoji} *Chain:* ${chain.name}\n` +
      `📍 *Address:* \`${walletData.address}\`\n\n` +
      `⚠️ Please delete your previous message containing the private key!`,
      { parse_mode: 'Markdown' }
    );
  } catch (err) {
    await ctx.reply(`❌ Import failed: ${err.message}`);
  }
}

// ─── /balance [chain] ─────────────────────────────────────────────────────────

async function showBalance(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const chainArg = args[0]?.toLowerCase();
  const user = db.getUserByTelegramId(ctx.from.id);

  await ctx.reply('⏳ Fetching balances...');

  if (chainArg) {
    const chain = getChain(chainArg);
    if (!chain) return ctx.reply(`❌ Unknown chain: ${chainArg}`);

    const wallets = db.getUserWallets(user.id, chainArg);
    if (wallets.length === 0) {
      return ctx.reply(`No wallets found for ${chain.name}. Use /generate ${chainArg}`);
    }

    let text = `${chain.emoji} *${chain.name} Balances*\n\n`;
    for (const wallet of wallets) {
      const shortAddr = `${wallet.address.slice(0, 8)}...${wallet.address.slice(-6)}`;
      text += `*[${wallet.id}] ${wallet.label}*\n\`${shortAddr}\`\n`;
      try {
        const balanceData = await getWalletBalances(wallet.address, chainArg);
        const bal = parseFloat(balanceData.native.balance);
        text += `💰 ${bal.toFixed(6)} ${chain.symbol}\n\n`;
      } catch (err) {
        text += `⚠️ Error: ${err.message}\n\n`;
      }
    }

    return ctx.reply(text, { parse_mode: 'Markdown' });
  }

  // Show all chains
  const wallets = db.getUserWallets(user.id);
  if (wallets.length === 0) return ctx.reply('No wallets found. Use /generate to create one.');

  let text = '💰 *All Balances*\n\n';
  const chainGroups = {};
  wallets.forEach(w => {
    if (!chainGroups[w.chain]) chainGroups[w.chain] = [];
    chainGroups[w.chain].push(w);
  });

  for (const [chainKey, chainWallets] of Object.entries(chainGroups)) {
    const chain = CHAINS[chainKey];
    if (!chain) continue;
    text += `${chain.emoji} *${chain.name}*\n`;

    for (const wallet of chainWallets.slice(0, 2)) {
      const shortAddr = `${wallet.address.slice(0, 6)}...${wallet.address.slice(-4)}`;
      try {
        const balanceData = await getWalletBalances(wallet.address, chainKey);
        const bal = parseFloat(balanceData.native.balance);
        text += `  \`${shortAddr}\`: ${bal.toFixed(4)} ${chain.symbol}\n`;
      } catch {
        text += `  \`${shortAddr}\`: Error\n`;
      }
    }
    text += '\n';
  }

  await ctx.reply(text, { parse_mode: 'Markdown' });
}

// ─── /send [chain] [toAddress] [amount] [tokenAddress?] ──────────────────────

async function sendTokens(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const [chainArg, toAddress, amount, tokenAddress] = args;

  if (!chainArg || !toAddress || !amount) {
    return ctx.reply(
      '📤 *Send Tokens*\n\n' +
      'Usage: `/send [chain] [toAddress] [amount] [tokenAddress?]`\n\n' +
      'Examples:\n' +
      '`/send ethereum 0xRecipient 0.01` — Send 0.01 ETH\n' +
      '`/send bsc 0xRecipient 0.1` — Send 0.1 BNB\n' +
      '`/send solana RecipientPubkey 0.5` — Send 0.5 SOL',
      { parse_mode: 'Markdown' }
    );
  }

  const chain = getChain(chainArg);
  if (!chain) return ctx.reply(`❌ Unknown chain: ${chainArg}`);

  const user = db.getUserByTelegramId(ctx.from.id);
  const wallet = db.getDefaultWallet(user.id, chainArg);
  if (!wallet) return ctx.reply(`No default wallet for ${chain.name}. Use /generate ${chainArg}`);

  await ctx.reply(`⏳ Sending ${amount} ${chain.symbol} on ${chain.name}...`);

  try {
    let result;
    if (chain.type === 'evm') {
      const { sendNativeToken } = require('../../trading/evmSwap');
      result = await sendNativeToken(chainArg, wallet.encrypted_private_key, toAddress, amount);
    } else if (chain.type === 'solana') {
      const { sendSOL } = require('../../trading/solanaSwap');
      result = await sendSOL(wallet.encrypted_private_key, toAddress, parseFloat(amount));
    }

    const explorerUrl = `${chain.explorer}/tx/${result.txHash}`;
    await ctx.reply(
      `✅ *Sent Successfully!*\n\n` +
      `${chain.emoji} *Chain:* ${chain.name}\n` +
      `💸 *Amount:* ${amount} ${chain.symbol}\n` +
      `📬 *To:* \`${toAddress.slice(0, 10)}...\`\n\n` +
      `[View Transaction](${explorerUrl})`,
      { parse_mode: 'Markdown' }
    );
  } catch (err) {
    await ctx.reply(`❌ Send failed: ${err.message}`);
  }
}

// ─── /export [chain] — Export private key (dangerous!) ───────────────────────

async function exportPrivateKey(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const chainArg = args[0]?.toLowerCase();

  if (!chainArg) {
    return ctx.reply('Usage: `/export [chain]`\nExample: `/export ethereum`', { parse_mode: 'Markdown' });
  }

  const chain = getChain(chainArg);
  if (!chain) return ctx.reply(`❌ Unknown chain: ${chainArg}`);

  const user = db.getUserByTelegramId(ctx.from.id);
  const wallet = db.getDefaultWallet(user.id, chainArg);
  if (!wallet) return ctx.reply(`No wallet found for ${chain.name}`);

  const { decrypt } = require('../../utils/encryption');
  const privateKey = decrypt(wallet.encrypted_private_key);

  const msg = await ctx.reply(
    `🔑 *Private Key Export*\n\n` +
    `⚠️ *NEVER share this with anyone!*\n\n` +
    `${chain.emoji} ${chain.name}:\n\`${privateKey}\`\n\n` +
    `_This message will self-destruct in 30 seconds..._`,
    { parse_mode: 'Markdown' }
  );

  // Auto-delete after 30 seconds for security
  setTimeout(async () => {
    try {
      await ctx.deleteMessage(msg.message_id);
    } catch {}
  }, 30000);
}

// ─── Helper Functions ─────────────────────────────────────────────────────────

function buildChainButtons(prefix) {
  const chains = getAllChains();
  const buttons = [];
  for (let i = 0; i < chains.length; i += 3) {
    const row = chains.slice(i, i + 3).map(c =>
      Markup.button.callback(`${c.emoji} ${c.name}`, `${prefix}_${c.key}`)
    );
    buttons.push(row);
  }
  buttons.push([Markup.button.callback('« Cancel', 'back_main')]);
  return buttons;
}

async function handleChainSelect(ctx) {
  await ctx.answerCbQuery();
  const chainKey = ctx.match[1];
  await ctx.reply(`Selected chain: ${chainKey}\nUse /generate ${chainKey} to create a wallet.`);
}

async function handleSetDefault(ctx) {
  await ctx.answerCbQuery();
  const [walletId, chain] = [ctx.match[1], ctx.match[2]];
  const user = db.getUserByTelegramId(ctx.from.id);
  db.setDefaultWallet(user.id, parseInt(walletId), chain);
  await ctx.editMessageText(`✅ Wallet #${walletId} set as default for ${chain}`);
}

async function handleDeleteWallet(ctx) {
  await ctx.answerCbQuery();
  const walletId = ctx.match[1];
  const user = db.getUserByTelegramId(ctx.from.id);
  db.deleteWallet(parseInt(walletId), user.id);
  await ctx.editMessageText(`🗑️ Wallet #${walletId} deleted.`);
}

module.exports = {
  showWallets, generateWallet, importWallet,
  showBalance, sendTokens, exportPrivateKey,
  handleChainSelect, handleWalletGenerate,
  handleSetDefault, handleDeleteWallet
};

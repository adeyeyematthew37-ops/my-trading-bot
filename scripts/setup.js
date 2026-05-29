#!/usr/bin/env node
// scripts/setup.js — Interactive setup wizard

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const readline = require('readline');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

function ask(question) {
  return new Promise(resolve => rl.question(question, resolve));
}

async function setup() {
  console.log('\n🤖 CryptoBot Setup Wizard\n');
  console.log('='.repeat(50));

  // Check if .env already exists
  if (fs.existsSync('.env')) {
    const overwrite = await ask('\n⚠️  .env file already exists. Overwrite? (y/N): ');
    if (overwrite.toLowerCase() !== 'y') {
      console.log('Setup cancelled.');
      rl.close();
      return;
    }
  }

  console.log('\n📋 Let\'s configure your bot...\n');

  const config = {};

  // Telegram
  console.log('1. TELEGRAM SETUP');
  console.log('   Create a bot at https://t.me/BotFather and send /newbot');
  config.TELEGRAM_BOT_TOKEN = await ask('   Telegram Bot Token: ');

  console.log('\n2. YOUR TELEGRAM USER ID (for admin access)');
  console.log('   Get your ID from https://t.me/userinfobot');
  config.ADMIN_USER_IDS = await ask('   Your Telegram User ID: ');

  // RPC URLs
  console.log('\n3. RPC ENDPOINTS');
  console.log('   Get free keys from: infura.io, alchemy.com, helius.dev');

  const ethRpc = await ask('   Ethereum RPC URL (or press Enter for default): ');
  config.ETH_RPC_URL = ethRpc || 'https://eth.llamarpc.com';

  const bscRpc = await ask('   BSC RPC URL (or press Enter for default): ');
  config.BSC_RPC_URL = bscRpc || 'https://bsc-dataseed1.binance.org';

  const polyRpc = await ask('   Polygon RPC URL (or press Enter for default): ');
  config.POLYGON_RPC_URL = polyRpc || 'https://polygon.llamarpc.com';

  const arbRpc = await ask('   Arbitrum RPC URL (or press Enter for default): ');
  config.ARBITRUM_RPC_URL = arbRpc || 'https://arb1.arbitrum.io/rpc';

  const baseRpc = await ask('   Base RPC URL (or press Enter for default): ');
  config.BASE_RPC_URL = baseRpc || 'https://mainnet.base.org';

  const avaxRpc = await ask('   Avalanche RPC URL (or press Enter for default): ');
  config.AVAX_RPC_URL = avaxRpc || 'https://api.avax.network/ext/bc/C/rpc';

  const solRpc = await ask('   Solana RPC URL (or press Enter for default): ');
  config.SOLANA_RPC_URL = solRpc || 'https://api.mainnet-beta.solana.com';

  // Optional API Keys
  console.log('\n4. OPTIONAL API KEYS (improves functionality)');

  const cgKey = await ask('   CoinGecko API Key (or press Enter to skip): ');
  config.COINGECKO_API_KEY = cgKey || '';

  const inchKey = await ask('   1inch API Key (or press Enter to skip): ');
  config.ONEINCH_API_KEY = inchKey || '';

  // Auto-generate encryption key
  config.ENCRYPTION_KEY = crypto.randomBytes(32).toString('hex');
  console.log('\n✅ Generated secure encryption key automatically');

  // Settings
  config.DB_PATH = './data/bot.db';
  config.MAX_SLIPPAGE_PERCENT = '1.0';
  config.DEFAULT_GAS_MULTIPLIER = '1.2';
  config.DCA_CHECK_INTERVAL_MINUTES = '1';
  config.MAX_WALLETS_PER_USER = '5';

  // Write .env file
  const envContent = Object.entries(config)
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');

  fs.writeFileSync('.env', envContent);

  // Create data directory
  fs.mkdirSync('./data', { recursive: true });
  fs.mkdirSync('./logs', { recursive: true });

  console.log('\n' + '='.repeat(50));
  console.log('✅ Setup complete! Your .env file has been created.');
  console.log('\nNext steps:');
  console.log('  npm install');
  console.log('  npm start');
  console.log('\nThen open Telegram and send /start to your bot!');
  console.log('='.repeat(50) + '\n');

  rl.close();
}

setup().catch(err => {
  console.error('Setup failed:', err);
  rl.close();
  process.exit(1);
});

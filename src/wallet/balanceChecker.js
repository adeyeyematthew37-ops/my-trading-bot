// src/wallet/balanceChecker.js
const { ethers } = require('ethers');
const { Connection, PublicKey, LAMPORTS_PER_SOL } = require('@solana/web3.js');
const axios = require('axios');
const { CHAINS } = require('../config/chains');
const logger = require('../utils/logger');

const ERC20_ABI = [
  'function balanceOf(address) view returns (uint256)',
  'function decimals() view returns (uint8)',
  'function symbol() view returns (string)',
  'function name() view returns (string)'
];

const providers = {};

function getProvider(chainKey) {
  if (providers[chainKey]) return providers[chainKey];
  const chain = CHAINS[chainKey];
  if (!chain || chain.type !== 'evm') throw new Error(`Invalid EVM chain: ${chainKey}`);

  const rpcUrl = process.env[chain.rpcEnvKey];
  if (!rpcUrl || rpcUrl.includes('YOUR_')) {
    throw new Error(`RPC URL not configured for ${chain.name}. Set ${chain.rpcEnvKey} in .env`);
  }

  providers[chainKey] = new ethers.JsonRpcProvider(rpcUrl);
  return providers[chainKey];
}

function getSolanaConnection() {
  const rpcUrl = process.env.SOLANA_RPC_URL || 'https://api.mainnet-beta.solana.com';
  return new Connection(rpcUrl, 'confirmed');
}

/**
 * Get native token balance for EVM chain
 */
async function getEVMNativeBalance(address, chainKey) {
  const provider = getProvider(chainKey);
  const balance = await provider.getBalance(address);
  return ethers.formatEther(balance);
}

/**
 * Get ERC20 token balance
 */
async function getERC20Balance(address, tokenAddress, chainKey) {
  const provider = getProvider(chainKey);
  const contract = new ethers.Contract(tokenAddress, ERC20_ABI, provider);
  const [balance, decimals, symbol] = await Promise.all([
    contract.balanceOf(address),
    contract.decimals(),
    contract.symbol()
  ]);
  return {
    balance: ethers.formatUnits(balance, decimals),
    raw: balance,
    decimals: Number(decimals),
    symbol
  };
}

/**
 * Get SOL balance
 */
async function getSolanaBalance(address) {
  const connection = getSolanaConnection();
  const pubkey = new PublicKey(address);
  const balance = await connection.getBalance(pubkey);
  return (balance / LAMPORTS_PER_SOL).toString();
}

/**
 * Get all balances for a wallet across common tokens
 */
async function getWalletBalances(address, chainKey) {
  const chain = CHAINS[chainKey];
  if (!chain) throw new Error(`Unknown chain: ${chainKey}`);

  const result = {
    chain: chain.name,
    chainEmoji: chain.emoji,
    address,
    native: { symbol: chain.symbol, balance: '0' },
    tokens: []
  };

  try {
    if (chain.type === 'evm') {
      result.native.balance = await getEVMNativeBalance(address, chainKey);
    } else if (chain.type === 'solana') {
      result.native.balance = await getSolanaBalance(address);
    }
  } catch (err) {
    logger.error(`Error fetching balance for ${chainKey}:`, err.message);
    result.native.balance = 'Error';
  }

  return result;
}

/**
 * Get token info for an ERC20 contract
 */
async function getTokenInfo(tokenAddress, chainKey) {
  const provider = getProvider(chainKey);
  const contract = new ethers.Contract(tokenAddress, ERC20_ABI, provider);

  try {
    const [name, symbol, decimals] = await Promise.all([
      contract.name(),
      contract.symbol(),
      contract.decimals()
    ]);
    return { name, symbol, decimals: Number(decimals), address: tokenAddress };
  } catch {
    throw new Error(`Could not fetch token info for ${tokenAddress} on ${chainKey}`);
  }
}

/**
 * Get gas price for a chain
 */
async function getGasPrice(chainKey) {
  const provider = getProvider(chainKey);
  const feeData = await provider.getFeeData();
  return {
    gasPrice: feeData.gasPrice ? ethers.formatUnits(feeData.gasPrice, 'gwei') : null,
    maxFeePerGas: feeData.maxFeePerGas ? ethers.formatUnits(feeData.maxFeePerGas, 'gwei') : null,
    maxPriorityFeePerGas: feeData.maxPriorityFeePerGas ? ethers.formatUnits(feeData.maxPriorityFeePerGas, 'gwei') : null
  };
}

module.exports = {
  getProvider,
  getSolanaConnection,
  getEVMNativeBalance,
  getERC20Balance,
  getSolanaBalance,
  getWalletBalances,
  getTokenInfo,
  getGasPrice
};

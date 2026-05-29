// src/config/chains.js
// Chain configurations for all supported networks

const CHAINS = {
  ethereum: {
    id: 1,
    name: 'Ethereum',
    symbol: 'ETH',
    rpcEnvKey: 'ETH_RPC_URL',
    explorer: 'https://etherscan.io',
    nativeToken: '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE',
    wrappedNative: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
    router: '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D', // Uniswap V2
    routerV3: '0xE592427A0AEce92De3Edee1F18E0157C05861564', // Uniswap V3
    emoji: '⟠',
    type: 'evm',
    coingeckoId: 'ethereum'
  },
  bsc: {
    id: 56,
    name: 'BNB Chain',
    symbol: 'BNB',
    rpcEnvKey: 'BSC_RPC_URL',
    explorer: 'https://bscscan.com',
    nativeToken: '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE',
    wrappedNative: '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',
    router: '0x10ED43C718714eb63d5aA57B78B54704E256024E', // PancakeSwap V2
    emoji: '🔶',
    type: 'evm',
    coingeckoId: 'binancecoin'
  },
  polygon: {
    id: 137,
    name: 'Polygon',
    symbol: 'MATIC',
    rpcEnvKey: 'POLYGON_RPC_URL',
    explorer: 'https://polygonscan.com',
    nativeToken: '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE',
    wrappedNative: '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270',
    router: '0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff', // QuickSwap
    emoji: '🟣',
    type: 'evm',
    coingeckoId: 'matic-network'
  },
  arbitrum: {
    id: 42161,
    name: 'Arbitrum',
    symbol: 'ETH',
    rpcEnvKey: 'ARBITRUM_RPC_URL',
    explorer: 'https://arbiscan.io',
    nativeToken: '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE',
    wrappedNative: '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
    router: '0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506', // SushiSwap
    emoji: '🔵',
    type: 'evm',
    coingeckoId: 'ethereum'
  },
  base: {
    id: 8453,
    name: 'Base',
    symbol: 'ETH',
    rpcEnvKey: 'BASE_RPC_URL',
    explorer: 'https://basescan.org',
    nativeToken: '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE',
    wrappedNative: '0x4200000000000000000000000000000000000006',
    router: '0x8357227D4eDc78991Db6FDB9bD6ADE250536dE1d', // BaseSwap
    emoji: '🔷',
    type: 'evm',
    coingeckoId: 'ethereum'
  },
  avalanche: {
    id: 43114,
    name: 'Avalanche',
    symbol: 'AVAX',
    rpcEnvKey: 'AVAX_RPC_URL',
    explorer: 'https://snowtrace.io',
    nativeToken: '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE',
    wrappedNative: '0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7',
    router: '0x60aE616a2155Ee3d9A68541Ba4544862310933d4', // TraderJoe
    emoji: '🔺',
    type: 'evm',
    coingeckoId: 'avalanche-2'
  },
  solana: {
    id: 'solana',
    name: 'Solana',
    symbol: 'SOL',
    rpcEnvKey: 'SOLANA_RPC_URL',
    explorer: 'https://solscan.io',
    emoji: '◎',
    type: 'solana',
    coingeckoId: 'solana',
    jupiterApiUrl: 'https://quote-api.jup.ag/v6'
  }
};

const CHAIN_ALIASES = {
  eth: 'ethereum',
  ether: 'ethereum',
  bnb: 'bsc',
  'bnb chain': 'bsc',
  poly: 'polygon',
  matic: 'polygon',
  arb: 'arbitrum',
  avax: 'avalanche',
  sol: 'solana'
};

function getChain(nameOrAlias) {
  const key = nameOrAlias.toLowerCase();
  const chainKey = CHAIN_ALIASES[key] || key;
  return CHAINS[chainKey] || null;
}

function getAllChains() {
  return Object.entries(CHAINS).map(([key, chain]) => ({ key, ...chain }));
}

function getEVMChains() {
  return Object.entries(CHAINS)
    .filter(([, c]) => c.type === 'evm')
    .map(([key, chain]) => ({ key, ...chain }));
}

module.exports = { CHAINS, getChain, getAllChains, getEVMChains };

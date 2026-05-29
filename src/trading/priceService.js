// src/trading/priceService.js
const axios = require('axios');
const logger = require('../utils/logger');

const COINGECKO_BASE = 'https://api.coingecko.com/api/v3';
const DEXSCREENER_BASE = 'https://api.dexscreener.com/latest';
const JUPITER_PRICE_API = 'https://price.jup.ag/v6/price';

// Cache to avoid rate limits
const priceCache = new Map();
const CACHE_TTL = 30000; // 30 seconds

function getCached(key) {
  const cached = priceCache.get(key);
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.value;
  }
  return null;
}

function setCache(key, value) {
  priceCache.set(key, { value, timestamp: Date.now() });
}

/**
 * Get price from CoinGecko by coin ID
 */
async function getPriceByCoingeckoId(coinId, vsCurrency = 'usd') {
  const cacheKey = `cg_${coinId}_${vsCurrency}`;
  const cached = getCached(cacheKey);
  if (cached) return cached;

  try {
    const params = { ids: coinId, vs_currencies: vsCurrency, include_24hr_change: true };
    const headers = process.env.COINGECKO_API_KEY
      ? { 'x-cg-demo-api-key': process.env.COINGECKO_API_KEY }
      : {};

    const res = await axios.get(`${COINGECKO_BASE}/simple/price`, { params, headers, timeout: 8000 });
    const data = res.data[coinId];
    if (!data) return null;

    const result = {
      price: data[vsCurrency],
      change24h: data[`${vsCurrency}_24h_change`] || 0,
      source: 'coingecko'
    };
    setCache(cacheKey, result);
    return result;
  } catch (err) {
    logger.warn(`CoinGecko price fetch failed for ${coinId}: ${err.message}`);
    return null;
  }
}

/**
 * Get token price from DEXScreener (works for any token address)
 */
async function getTokenPriceDexScreener(chainKey, tokenAddress) {
  const cacheKey = `dex_${chainKey}_${tokenAddress}`;
  const cached = getCached(cacheKey);
  if (cached) return cached;

  const chainMap = {
    ethereum: 'ethereum', bsc: 'bsc', polygon: 'polygon',
    arbitrum: 'arbitrum', base: 'base', avalanche: 'avalanche', solana: 'solana'
  };

  const dexChain = chainMap[chainKey];
  if (!dexChain) return null;

  try {
    const res = await axios.get(
      `${DEXSCREENER_BASE}/dex/tokens/${tokenAddress}`,
      { timeout: 8000 }
    );

    const pairs = res.data?.pairs;
    if (!pairs || pairs.length === 0) return null;

    // Find the most liquid pair on the right chain
    const chainPairs = pairs.filter(p => p.chainId === dexChain);
    const pair = chainPairs.sort((a, b) => (b.liquidity?.usd || 0) - (a.liquidity?.usd || 0))[0];
    if (!pair) return null;

    const result = {
      price: parseFloat(pair.priceUsd),
      change24h: pair.priceChange?.h24 || 0,
      volume24h: pair.volume?.h24 || 0,
      liquidity: pair.liquidity?.usd || 0,
      pairAddress: pair.pairAddress,
      dexName: pair.dexId,
      baseToken: pair.baseToken,
      source: 'dexscreener'
    };
    setCache(cacheKey, result);
    return result;
  } catch (err) {
    logger.warn(`DexScreener price fetch failed: ${err.message}`);
    return null;
  }
}

/**
 * Get Solana token price from Jupiter
 */
async function getSolanaTokenPrice(mintAddress) {
  const cacheKey = `jup_${mintAddress}`;
  const cached = getCached(cacheKey);
  if (cached) return cached;

  try {
    const res = await axios.get(`${JUPITER_PRICE_API}`, {
      params: { ids: mintAddress },
      timeout: 8000
    });

    const tokenData = res.data?.data?.[mintAddress];
    if (!tokenData) return null;

    const result = {
      price: tokenData.price,
      source: 'jupiter'
    };
    setCache(cacheKey, result);
    return result;
  } catch (err) {
    logger.warn(`Jupiter price fetch failed: ${err.message}`);
    return null;
  }
}

/**
 * Unified price getter — tries multiple sources
 */
async function getTokenPrice(chainKey, tokenAddress, coingeckoId = null) {
  // Try CoinGecko first if we have an ID
  if (coingeckoId) {
    const cgPrice = await getPriceByCoingeckoId(coingeckoId);
    if (cgPrice) return cgPrice;
  }

  // Try Solana-specific source
  if (chainKey === 'solana') {
    const jupPrice = await getSolanaTokenPrice(tokenAddress);
    if (jupPrice) return jupPrice;
  }

  // Fallback to DexScreener for any chain/token
  return await getTokenPriceDexScreener(chainKey, tokenAddress);
}

/**
 * Get prices for multiple native tokens at once
 */
async function getNativePrices() {
  const ids = 'ethereum,binancecoin,matic-network,avalanche-2,solana';
  try {
    const headers = process.env.COINGECKO_API_KEY
      ? { 'x-cg-demo-api-key': process.env.COINGECKO_API_KEY }
      : {};

    const res = await axios.get(`${COINGECKO_BASE}/simple/price`, {
      params: { ids, vs_currencies: 'usd', include_24hr_change: true },
      headers,
      timeout: 8000
    });

    return res.data;
  } catch (err) {
    logger.warn(`Native price fetch failed: ${err.message}`);
    return {};
  }
}

/**
 * Search for tokens by name/symbol
 */
async function searchToken(query) {
  try {
    const headers = process.env.COINGECKO_API_KEY
      ? { 'x-cg-demo-api-key': process.env.COINGECKO_API_KEY }
      : {};

    const res = await axios.get(`${COINGECKO_BASE}/search`, {
      params: { query },
      headers,
      timeout: 8000
    });

    return res.data.coins?.slice(0, 5) || [];
  } catch {
    return [];
  }
}

/**
 * Format price for display
 */
function formatPrice(price, decimals = null) {
  if (price === null || price === undefined) return 'N/A';
  const num = parseFloat(price);
  if (num === 0) return '$0.00';
  if (num < 0.000001) return `$${num.toExponential(4)}`;
  if (num < 0.01) return `$${num.toFixed(8)}`;
  if (num < 1) return `$${num.toFixed(6)}`;
  if (num < 1000) return `$${num.toFixed(4)}`;
  return `$${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatChange(change) {
  if (change === null || change === undefined) return '';
  const num = parseFloat(change);
  const emoji = num >= 0 ? '📈' : '📉';
  const sign = num >= 0 ? '+' : '';
  return `${emoji} ${sign}${num.toFixed(2)}%`;
}

module.exports = {
  getPriceByCoingeckoId,
  getTokenPriceDexScreener,
  getSolanaTokenPrice,
  getTokenPrice,
  getNativePrices,
  searchToken,
  formatPrice,
  formatChange
};

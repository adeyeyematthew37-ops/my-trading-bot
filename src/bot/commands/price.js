// src/bot/commands/price.js
const { Markup } = require('telegraf');
const {
  getTokenPrice, getTokenPriceDexScreener, getNativePrices,
  searchToken, formatPrice, formatChange, getPriceByCoingeckoId
} = require('../../trading/priceService');
const { getChain, CHAINS } = require('../../config/chains');

// ─── /price [token or "chain:address"] ───────────────────────────────────────

async function getPrice(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const query = args.join(' ').trim();

  if (!query) {
    // Show all native prices
    await ctx.reply('⏳ Fetching native token prices...');
    try {
      const prices = await getNativePrices();
      let text = '💰 *Native Token Prices*\n\n';

      const tokenMap = [
        { emoji: '⟠', name: 'Ethereum', id: 'ethereum' },
        { emoji: '🔶', name: 'BNB', id: 'binancecoin' },
        { emoji: '🟣', name: 'MATIC', id: 'matic-network' },
        { emoji: '🔺', name: 'AVAX', id: 'avalanche-2' },
        { emoji: '◎', name: 'Solana', id: 'solana' }
      ];

      for (const token of tokenMap) {
        const data = prices[token.id];
        if (data) {
          const price = formatPrice(data.usd);
          const change = formatChange(data.usd_24h_change);
          text += `${token.emoji} *${token.name}:* ${price} ${change}\n`;
        }
      }

      text += `\n_Use \`/price [symbol]\` for specific tokens_\n_Use \`/price [chain] [address]\` for any token_`;

      await ctx.reply(text, { parse_mode: 'Markdown' });
    } catch (err) {
      await ctx.reply(`❌ Failed to fetch prices: ${err.message}`);
    }
    return;
  }

  // Check if format is "chain:address" or "chain address"
  const parts = query.split(/[\s:]+/);

  if (parts.length >= 2 && CHAINS[parts[0].toLowerCase()]) {
    const chainKey = parts[0].toLowerCase();
    const tokenAddress = parts[1];
    await fetchTokenAddressPrice(ctx, chainKey, tokenAddress);
    return;
  }

  // Try CoinGecko search by symbol/name
  await ctx.reply('⏳ Searching...');
  try {
    const results = await searchToken(query);
    if (results.length === 0) {
      return ctx.reply(`❌ Token "${query}" not found. Try using a contract address:\n\`/price ethereum 0xTokenAddress\``, { parse_mode: 'Markdown' });
    }

    const coin = results[0];
    const priceData = await getPriceByCoingeckoId(coin.id);

    if (!priceData) {
      return ctx.reply(`❌ Could not fetch price for ${coin.name}`);
    }

    const text = [
      `💰 *${coin.name} (${coin.symbol?.toUpperCase()})*`,
      ``,
      `💵 *Price:* ${formatPrice(priceData.price)}`,
      `📊 *24h Change:* ${formatChange(priceData.change24h)}`,
      ``,
      `_Source: CoinGecko_`,
      `_Symbol: ${coin.symbol}_`
    ].join('\n');

    await ctx.reply(text, { parse_mode: 'Markdown' });
  } catch (err) {
    await ctx.reply(`❌ Error: ${err.message}`);
  }
}

async function fetchTokenAddressPrice(ctx, chainKey, tokenAddress) {
  const chain = CHAINS[chainKey];

  try {
    let priceData;
    if (chainKey === 'solana') {
      const { getSolanaTokenPrice } = require('../../trading/priceService');
      priceData = await getSolanaTokenPrice(tokenAddress);
    } else {
      priceData = await getTokenPriceDexScreener(chainKey, tokenAddress);
    }

    if (!priceData) {
      return ctx.reply(`❌ No price data found for this token on ${chain?.name || chainKey}`);
    }

    const shortAddr = `${tokenAddress.slice(0, 8)}...${tokenAddress.slice(-6)}`;
    let text = [
      `💰 *Token Price*`,
      ``,
      `${chain?.emoji || '🔗'} *Chain:* ${chain?.name || chainKey}`,
      `📍 *Contract:* \`${shortAddr}\``,
      ``,
      `💵 *Price:* ${formatPrice(priceData.price)}`,
      `📊 *24h Change:* ${formatChange(priceData.change24h)}`,
    ];

    if (priceData.volume24h) {
      text.push(`📦 *24h Volume:* $${(priceData.volume24h / 1000).toFixed(1)}K`);
    }
    if (priceData.liquidity) {
      text.push(`💧 *Liquidity:* $${(priceData.liquidity / 1000).toFixed(1)}K`);
    }
    if (priceData.dexName) {
      text.push(`\n_DEX: ${priceData.dexName}_`);
    }

    await ctx.reply(text.join('\n'), { parse_mode: 'Markdown' });
  } catch (err) {
    await ctx.reply(`❌ Error fetching price: ${err.message}`);
  }
}

// ─── /search [query] ─────────────────────────────────────────────────────────

async function searchCoin(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const query = args.join(' ').trim();

  if (!query) {
    return ctx.reply('Usage: `/search [token name or symbol]`\nExample: `/search uniswap`', { parse_mode: 'Markdown' });
  }

  await ctx.reply(`🔍 Searching for "${query}"...`);

  try {
    const results = await searchToken(query);
    if (results.length === 0) {
      return ctx.reply(`No results found for "${query}"`);
    }

    let text = `🔍 *Search Results for "${query}"*\n\n`;
    for (const coin of results.slice(0, 5)) {
      text += `• *${coin.name}* (${coin.symbol?.toUpperCase()})\n`;
      text += `  ID: \`${coin.id}\` | Rank: #${coin.market_cap_rank || 'N/A'}\n`;
    }

    text += `\n_Use /price [symbol] to get price_`;
    await ctx.reply(text, { parse_mode: 'Markdown' });
  } catch (err) {
    await ctx.reply(`❌ Search failed: ${err.message}`);
  }
}

// ─── /chart — Placeholder (links to chart) ───────────────────────────────────

async function getChart(ctx) {
  const args = ctx.message.text.split(' ').slice(1);
  const token = args[0]?.toLowerCase() || 'bitcoin';

  const chartUrl = `https://www.coingecko.com/en/coins/${token}`;
  await ctx.reply(
    `📈 *Chart for ${token}*\n\n[View on CoinGecko](${chartUrl})\n[View on DexScreener](https://dexscreener.com/search?q=${token})`,
    { parse_mode: 'Markdown' }
  );
}

module.exports = { getPrice, searchCoin, getChart };

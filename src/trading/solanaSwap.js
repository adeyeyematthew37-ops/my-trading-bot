// src/trading/solanaSwap.js
const { Connection, PublicKey, VersionedTransaction } = require('@solana/web3.js');
const axios = require('axios');
const bs58 = require('bs58');
const { getSolanaKeypair } = require('../wallet/walletGenerator');
const logger = require('../utils/logger');

const JUPITER_QUOTE_API = 'https://quote-api.jup.ag/v6/quote';
const JUPITER_SWAP_API = 'https://quote-api.jup.ag/v6/swap';

// Common Solana token mints
const SOL_MINT = 'So11111111111111111111111111111111111111112';
const USDC_MINT = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const USDT_MINT = 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB';

function getSolanaConnection() {
  const rpcUrl = process.env.SOLANA_RPC_URL || 'https://api.mainnet-beta.solana.com';
  return new Connection(rpcUrl, 'confirmed');
}

/**
 * Get Jupiter swap quote
 */
async function getJupiterQuote(inputMint, outputMint, amountLamports, slippageBps = 100) {
  try {
    const res = await axios.get(JUPITER_QUOTE_API, {
      params: {
        inputMint,
        outputMint,
        amount: amountLamports.toString(),
        slippageBps: slippageBps.toString(),
        onlyDirectRoutes: false,
        asLegacyTransaction: false
      },
      timeout: 10000
    });

    return res.data;
  } catch (err) {
    logger.error(`Jupiter quote failed: ${err.message}`);
    throw new Error(`Could not get swap quote: ${err.message}`);
  }
}

/**
 * Execute swap on Solana via Jupiter
 */
async function executeSolanaSwap({
  encryptedPrivateKey,
  inputMint,
  outputMint,
  amountLamports,
  slippageBps = 100,   // 1% = 100 bps
  userAddress
}) {
  const connection = getSolanaConnection();
  const keypair = getSolanaKeypair(encryptedPrivateKey);

  logger.info(`Solana swap: ${inputMint} → ${outputMint}, amount: ${amountLamports}`);

  // 1. Get quote
  const quote = await getJupiterQuote(inputMint, outputMint, amountLamports, slippageBps);
  logger.info(`Jupiter quote: ${quote.outAmount} output tokens`);

  // 2. Get swap transaction
  const swapRes = await axios.post(JUPITER_SWAP_API, {
    quoteResponse: quote,
    userPublicKey: keypair.publicKey.toBase58(),
    wrapAndUnwrapSol: true,
    computeUnitPriceMicroLamports: 'auto'
  }, { timeout: 15000 });

  const { swapTransaction } = swapRes.data;

  // 3. Deserialize and sign
  const txBuffer = Buffer.from(swapTransaction, 'base64');
  const transaction = VersionedTransaction.deserialize(txBuffer);
  transaction.sign([keypair]);

  // 4. Send transaction
  const txId = await connection.sendTransaction(transaction, {
    maxRetries: 3,
    skipPreflight: false
  });

  logger.info(`Solana swap tx: ${txId}`);

  // 5. Confirm
  const latestBlockhash = await connection.getLatestBlockhash();
  const confirmation = await connection.confirmTransaction({
    signature: txId,
    ...latestBlockhash
  }, 'confirmed');

  if (confirmation.value.err) {
    throw new Error(`Transaction failed: ${JSON.stringify(confirmation.value.err)}`);
  }

  return {
    txHash: txId,
    amountOut: quote.outAmount,
    status: 'success'
  };
}

/**
 * Send SOL to another address
 */
async function sendSOL(encryptedPrivateKey, toAddress, amountSOL) {
  const { SystemProgram, Transaction, LAMPORTS_PER_SOL } = require('@solana/web3.js');
  const connection = getSolanaConnection();
  const keypair = getSolanaKeypair(encryptedPrivateKey);

  const lamports = Math.floor(amountSOL * LAMPORTS_PER_SOL);
  const toPubkey = new PublicKey(toAddress);

  const transaction = new Transaction().add(
    SystemProgram.transfer({
      fromPubkey: keypair.publicKey,
      toPubkey,
      lamports
    })
  );

  const signature = await connection.sendTransaction(transaction, [keypair]);
  await connection.confirmTransaction(signature, 'confirmed');

  return { txHash: signature, status: 'success' };
}

/**
 * Parse Jupiter quote for display
 */
function formatJupiterQuote(quote, inputDecimals = 9, outputDecimals = 9) {
  const inputAmount = (parseInt(quote.inAmount) / Math.pow(10, inputDecimals)).toFixed(6);
  const outputAmount = (parseInt(quote.outAmount) / Math.pow(10, outputDecimals)).toFixed(6);
  const priceImpact = parseFloat(quote.priceImpactPct || 0).toFixed(3);

  return { inputAmount, outputAmount, priceImpact };
}

module.exports = {
  getJupiterQuote,
  executeSolanaSwap,
  sendSOL,
  formatJupiterQuote,
  SOL_MINT,
  USDC_MINT,
  USDT_MINT
};

// src/trading/evmSwap.js
const { ethers } = require('ethers');
const axios = require('axios');
const { getProvider } = require('../wallet/balanceChecker');
const { getEVMSigner } = require('../wallet/walletGenerator');
const { CHAINS } = require('../config/chains');
const logger = require('../utils/logger');

const UNISWAP_V2_ABI = [
  'function swapExactETHForTokens(uint amountOutMin, address[] calldata path, address to, uint deadline) external payable returns (uint[] memory amounts)',
  'function swapExactTokensForETH(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external returns (uint[] memory amounts)',
  'function swapExactTokensForTokens(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external returns (uint[] memory amounts)',
  'function getAmountsOut(uint amountIn, address[] calldata path) external view returns (uint[] memory amounts)'
];

const ERC20_ABI = [
  'function approve(address spender, uint256 amount) external returns (bool)',
  'function allowance(address owner, address spender) external view returns (uint256)',
  'function balanceOf(address) view returns (uint256)',
  'function decimals() view returns (uint8)',
  'function symbol() view returns (string)'
];

const NATIVE_TOKEN = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE';

/**
 * Get a swap quote using 1inch aggregator API
 */
async function get1inchQuote(chainId, tokenIn, tokenOut, amountIn, slippage = 1) {
  if (!process.env.ONEINCH_API_KEY || process.env.ONEINCH_API_KEY.includes('your_')) {
    return null;
  }

  try {
    const res = await axios.get(`https://api.1inch.dev/swap/v6.0/${chainId}/quote`, {
      params: { src: tokenIn, dst: tokenOut, amount: amountIn.toString() },
      headers: { Authorization: `Bearer ${process.env.ONEINCH_API_KEY}` },
      timeout: 8000
    });
    return res.data;
  } catch (err) {
    logger.warn(`1inch quote failed: ${err.message}`);
    return null;
  }
}

/**
 * Get a swap transaction from 1inch
 */
async function get1inchSwapTx(chainId, tokenIn, tokenOut, amountIn, fromAddress, slippage = 1) {
  if (!process.env.ONEINCH_API_KEY || process.env.ONEINCH_API_KEY.includes('your_')) {
    return null;
  }

  try {
    const res = await axios.get(`https://api.1inch.dev/swap/v6.0/${chainId}/swap`, {
      params: {
        src: tokenIn, dst: tokenOut,
        amount: amountIn.toString(),
        from: fromAddress,
        slippage: slippage.toString(),
        disableEstimate: false
      },
      headers: { Authorization: `Bearer ${process.env.ONEINCH_API_KEY}` },
      timeout: 10000
    });
    return res.data.tx;
  } catch (err) {
    logger.warn(`1inch swap tx failed: ${err.message}`);
    return null;
  }
}

/**
 * Get quote from UniswapV2-compatible DEX
 */
async function getV2Quote(chainKey, tokenIn, tokenOut, amountIn) {
  const chain = CHAINS[chainKey];
  const provider = getProvider(chainKey);
  const router = new ethers.Contract(chain.router, UNISWAP_V2_ABI, provider);

  const isNativeIn = tokenIn.toLowerCase() === NATIVE_TOKEN.toLowerCase();
  const isNativeOut = tokenOut.toLowerCase() === NATIVE_TOKEN.toLowerCase();

  const actualIn = isNativeIn ? chain.wrappedNative : tokenIn;
  const actualOut = isNativeOut ? chain.wrappedNative : tokenOut;

  const path = [actualIn, actualOut];
  const amounts = await router.getAmountsOut(amountIn, path);
  return amounts[amounts.length - 1];
}

/**
 * Ensure token approval for router
 */
async function ensureApproval(signer, tokenAddress, spender, amount) {
  const token = new ethers.Contract(tokenAddress, ERC20_ABI, signer);
  const allowance = await token.allowance(await signer.getAddress(), spender);

  if (allowance < amount) {
    logger.info(`Approving ${tokenAddress} for ${spender}`);
    const approveTx = await token.approve(spender, ethers.MaxUint256);
    await approveTx.wait();
    logger.info(`Approval confirmed: ${approveTx.hash}`);
  }
}

/**
 * Execute swap on EVM chain
 * Returns { txHash, amountOut, status }
 */
async function executeEVMSwap({
  chainKey,
  encryptedPrivateKey,
  tokenIn,
  tokenOut,
  amountIn,        // BigInt or string in wei
  slippagePercent = 1.0,
  userAddress
}) {
  const chain = CHAINS[chainKey];
  if (!chain || chain.type !== 'evm') throw new Error(`Invalid EVM chain: ${chainKey}`);

  const provider = getProvider(chainKey);
  const signer = getEVMSigner(encryptedPrivateKey, provider);
  const fromAddress = await signer.getAddress();

  const amountInBN = BigInt(amountIn.toString());
  const isNativeIn = tokenIn.toLowerCase() === NATIVE_TOKEN.toLowerCase();
  const isNativeOut = tokenOut.toLowerCase() === NATIVE_TOKEN.toLowerCase();

  logger.info(`Executing swap on ${chainKey}: ${tokenIn} → ${tokenOut}, amount: ${amountIn}`);

  // Try 1inch first if API key is configured
  const oneinchTx = await get1inchSwapTx(
    chain.id, tokenIn, tokenOut, amountInBN.toString(), fromAddress, slippagePercent
  );

  if (oneinchTx) {
    logger.info('Using 1inch aggregator for swap');
    const tx = await signer.sendTransaction({
      to: oneinchTx.to,
      data: oneinchTx.data,
      value: BigInt(oneinchTx.value || '0'),
      gasLimit: BigInt(Math.floor(Number(oneinchTx.gas) * 1.2))
    });
    const receipt = await tx.wait();
    return { txHash: tx.hash, status: receipt.status === 1 ? 'success' : 'failed' };
  }

  // Fallback to direct DEX router
  logger.info('Using direct DEX router for swap');
  const router = new ethers.Contract(chain.router, UNISWAP_V2_ABI, signer);
  const deadline = Math.floor(Date.now() / 1000) + 1200; // 20 min

  const actualIn = isNativeIn ? chain.wrappedNative : tokenIn;
  const actualOut = isNativeOut ? chain.wrappedNative : tokenOut;
  const path = [actualIn, actualOut];

  // Get expected output with slippage
  const amountsOut = await router.getAmountsOut(amountInBN, path);
  const expectedOut = amountsOut[amountsOut.length - 1];
  const minOut = expectedOut * BigInt(Math.floor((100 - slippagePercent) * 100)) / 10000n;

  let tx;

  if (isNativeIn) {
    // ETH → Token
    tx = await router.swapExactETHForTokens(minOut, path, fromAddress, deadline, {
      value: amountInBN,
      gasLimit: 300000n
    });
  } else if (isNativeOut) {
    // Token → ETH
    await ensureApproval(signer, tokenIn, chain.router, amountInBN);
    tx = await router.swapExactTokensForETH(amountInBN, minOut, path, fromAddress, deadline, {
      gasLimit: 300000n
    });
  } else {
    // Token → Token
    await ensureApproval(signer, tokenIn, chain.router, amountInBN);
    tx = await router.swapExactTokensForTokens(amountInBN, minOut, path, fromAddress, deadline, {
      gasLimit: 400000n
    });
  }

  logger.info(`Swap tx submitted: ${tx.hash}`);
  const receipt = await tx.wait();

  return {
    txHash: tx.hash,
    amountOut: expectedOut.toString(),
    status: receipt.status === 1 ? 'success' : 'failed'
  };
}

/**
 * Send native token (ETH/BNB/MATIC etc)
 */
async function sendNativeToken(chainKey, encryptedPrivateKey, toAddress, amountEther) {
  const provider = getProvider(chainKey);
  const signer = getEVMSigner(encryptedPrivateKey, provider);

  const tx = await signer.sendTransaction({
    to: toAddress,
    value: ethers.parseEther(amountEther.toString())
  });

  const receipt = await tx.wait();
  return { txHash: tx.hash, status: receipt.status === 1 ? 'success' : 'failed' };
}

/**
 * Send ERC20 token
 */
async function sendERC20Token(chainKey, encryptedPrivateKey, tokenAddress, toAddress, amount, decimals) {
  const provider = getProvider(chainKey);
  const signer = getEVMSigner(encryptedPrivateKey, provider);
  const token = new ethers.Contract(tokenAddress, ERC20_ABI, signer);

  const amountRaw = ethers.parseUnits(amount.toString(), decimals);
  const tx = await token.transfer(toAddress, amountRaw);
  const receipt = await tx.wait();

  return { txHash: tx.hash, status: receipt.status === 1 ? 'success' : 'failed' };
}

module.exports = {
  executeEVMSwap,
  sendNativeToken,
  sendERC20Token,
  get1inchQuote,
  getV2Quote
};

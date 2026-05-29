// src/wallet/walletGenerator.js
const { ethers } = require('ethers');
const { Keypair } = require('@solana/web3.js');
const bip39 = require('bip39');
const bs58 = require('bs58');
const { encrypt, decrypt } = require('../utils/encryption');
const logger = require('../utils/logger');

/**
 * Generates a new EVM wallet (works for ETH, BSC, Polygon, Arbitrum, Base, AVAX)
 */
function generateEVMWallet() {
  const wallet = ethers.Wallet.createRandom();
  return {
    address: wallet.address,
    privateKey: wallet.privateKey,
    mnemonic: wallet.mnemonic?.phrase || null,
    type: 'evm'
  };
}

/**
 * Generates a new Solana wallet
 */
function generateSolanaWallet() {
  const keypair = Keypair.generate();
  const privateKeyBytes = keypair.secretKey; // 64 bytes
  const privateKeyBase58 = bs58.encode(privateKeyBytes);
  const publicKey = keypair.publicKey.toBase58();

  return {
    address: publicKey,
    privateKey: privateKeyBase58,
    mnemonic: null,
    type: 'solana'
  };
}

/**
 * Generate a wallet from an existing mnemonic (HD wallet derivation)
 */
function walletFromMnemonic(mnemonic, chainType = 'evm', index = 0) {
  if (!bip39.validateMnemonic(mnemonic)) {
    throw new Error('Invalid mnemonic phrase');
  }

  if (chainType === 'evm') {
    const path = `m/44'/60'/0'/0/${index}`;
    const wallet = ethers.HDNodeWallet.fromPhrase(mnemonic, undefined, path);
    return {
      address: wallet.address,
      privateKey: wallet.privateKey,
      mnemonic,
      type: 'evm'
    };
  } else if (chainType === 'solana') {
    // For Solana, derive from seed using BIP44 path
    const seed = bip39.mnemonicToSeedSync(mnemonic);
    const keypair = Keypair.fromSeed(seed.slice(0, 32));
    return {
      address: keypair.publicKey.toBase58(),
      privateKey: bs58.encode(keypair.secretKey),
      mnemonic,
      type: 'solana'
    };
  }

  throw new Error(`Unsupported chain type: ${chainType}`);
}

/**
 * Import wallet from private key
 */
function walletFromPrivateKey(privateKey, chainType = 'evm') {
  if (chainType === 'evm') {
    const wallet = new ethers.Wallet(privateKey);
    return {
      address: wallet.address,
      privateKey: wallet.privateKey,
      mnemonic: null,
      type: 'evm'
    };
  } else if (chainType === 'solana') {
    const bytes = bs58.decode(privateKey);
    const keypair = Keypair.fromSecretKey(bytes);
    return {
      address: keypair.publicKey.toBase58(),
      privateKey,
      mnemonic: null,
      type: 'solana'
    };
  }

  throw new Error(`Unsupported chain type: ${chainType}`);
}

/**
 * Get a signer for EVM chain transactions
 */
function getEVMSigner(encryptedPrivateKey, provider) {
  const privateKey = decrypt(encryptedPrivateKey);
  return new ethers.Wallet(privateKey, provider);
}

/**
 * Get a Solana keypair from encrypted private key
 */
function getSolanaKeypair(encryptedPrivateKey) {
  const privateKeyBase58 = decrypt(encryptedPrivateKey);
  const bytes = bs58.decode(privateKeyBase58);
  return Keypair.fromSecretKey(bytes);
}

/**
 * Generate a new mnemonic phrase
 */
function generateMnemonic(strength = 128) {
  return bip39.generateMnemonic(strength);
}

/**
 * Format wallet info for display (hides private key)
 */
function formatWalletDisplay(wallet, chain) {
  return {
    address: wallet.address,
    shortAddress: `${wallet.address.slice(0, 6)}...${wallet.address.slice(-4)}`,
    chain,
    type: wallet.type
  };
}

module.exports = {
  generateEVMWallet,
  generateSolanaWallet,
  walletFromMnemonic,
  walletFromPrivateKey,
  getEVMSigner,
  getSolanaKeypair,
  generateMnemonic,
  formatWalletDisplay
};

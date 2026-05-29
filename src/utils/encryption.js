// src/utils/encryption.js
const crypto = require('crypto');

const ALGORITHM = 'aes-256-gcm';
const KEY_LENGTH = 32;
const IV_LENGTH = 16;
const TAG_LENGTH = 16;

function getKey() {
  const keyStr = process.env.ENCRYPTION_KEY;
  if (!keyStr) throw new Error('ENCRYPTION_KEY not set in environment');
  // Derive a 32-byte key from the provided string
  return crypto.createHash('sha256').update(keyStr).digest();
}

/**
 * Encrypts a private key or mnemonic for storage
 * @param {string} plaintext
 * @returns {string} base64 encoded encrypted data
 */
function encrypt(plaintext) {
  const key = getKey();
  const iv = crypto.randomBytes(IV_LENGTH);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv);

  let encrypted = cipher.update(plaintext, 'utf8', 'hex');
  encrypted += cipher.final('hex');
  const tag = cipher.getAuthTag();

  // Format: iv:tag:encrypted
  return Buffer.from(`${iv.toString('hex')}:${tag.toString('hex')}:${encrypted}`).toString('base64');
}

/**
 * Decrypts a stored private key or mnemonic
 * @param {string} encryptedData base64 encoded encrypted data
 * @returns {string} plaintext
 */
function decrypt(encryptedData) {
  const key = getKey();
  const decoded = Buffer.from(encryptedData, 'base64').toString('utf8');
  const [ivHex, tagHex, encrypted] = decoded.split(':');

  const iv = Buffer.from(ivHex, 'hex');
  const tag = Buffer.from(tagHex, 'hex');

  const decipher = crypto.createDecipheriv(ALGORITHM, key, iv);
  decipher.setAuthTag(tag);

  let decrypted = decipher.update(encrypted, 'hex', 'utf8');
  decrypted += decipher.final('utf8');
  return decrypted;
}

module.exports = { encrypt, decrypt };

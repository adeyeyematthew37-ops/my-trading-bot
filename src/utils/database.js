// src/utils/database.js
const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');
const logger = require('./logger');

let db;

function initDatabase() {
  const dbPath = process.env.DB_PATH || './data/bot.db';
  const dbDir = path.dirname(dbPath);

  if (!fs.existsSync(dbDir)) {
    fs.mkdirSync(dbDir, { recursive: true });
  }

  db = new Database(dbPath);
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = ON');

  createTables();
  logger.info('Database initialized');
  return db;
}

function createTables() {
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY,
      telegram_id TEXT UNIQUE NOT NULL,
      username TEXT,
      first_name TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      settings TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS wallets (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      chain TEXT NOT NULL,
      address TEXT NOT NULL,
      encrypted_private_key TEXT NOT NULL,
      label TEXT DEFAULT 'Wallet',
      is_default INTEGER DEFAULT 0,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (user_id) REFERENCES users(id),
      UNIQUE(user_id, chain, address)
    );

    CREATE TABLE IF NOT EXISTS dca_orders (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      wallet_id INTEGER NOT NULL,
      chain TEXT NOT NULL,
      token_in TEXT NOT NULL,
      token_out TEXT NOT NULL,
      token_in_symbol TEXT,
      token_out_symbol TEXT,
      amount_per_order TEXT NOT NULL,
      frequency_minutes INTEGER NOT NULL,
      total_orders INTEGER DEFAULT 0,
      completed_orders INTEGER DEFAULT 0,
      status TEXT DEFAULT 'active',
      next_execution DATETIME,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (user_id) REFERENCES users(id),
      FOREIGN KEY (wallet_id) REFERENCES wallets(id)
    );

    CREATE TABLE IF NOT EXISTS trades (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      wallet_id INTEGER NOT NULL,
      chain TEXT NOT NULL,
      type TEXT NOT NULL,
      token_in TEXT NOT NULL,
      token_out TEXT NOT NULL,
      token_in_symbol TEXT,
      token_out_symbol TEXT,
      amount_in TEXT NOT NULL,
      amount_out TEXT,
      tx_hash TEXT,
      status TEXT DEFAULT 'pending',
      dca_order_id INTEGER,
      error_message TEXT,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS price_alerts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      chain TEXT NOT NULL,
      token_address TEXT NOT NULL,
      token_symbol TEXT,
      condition TEXT NOT NULL,
      target_price REAL NOT NULL,
      current_price REAL,
      status TEXT DEFAULT 'active',
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (user_id) REFERENCES users(id)
    );
  `);
}

// ─── User Operations ─────────────────────────────────────────────────────────

function upsertUser(telegramId, username, firstName) {
  const stmt = db.prepare(`
    INSERT INTO users (telegram_id, username, first_name)
    VALUES (?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET
      username = excluded.username,
      first_name = excluded.first_name
  `);
  stmt.run(String(telegramId), username, firstName);
  return getUserByTelegramId(telegramId);
}

function getUserByTelegramId(telegramId) {
  return db.prepare('SELECT * FROM users WHERE telegram_id = ?').get(String(telegramId));
}

function updateUserSettings(telegramId, settings) {
  db.prepare('UPDATE users SET settings = ? WHERE telegram_id = ?')
    .run(JSON.stringify(settings), String(telegramId));
}

// ─── Wallet Operations ────────────────────────────────────────────────────────

function saveWallet(userId, chain, address, encryptedKey, label = 'Wallet') {
  const existing = db.prepare(
    'SELECT COUNT(*) as count FROM wallets WHERE user_id = ? AND chain = ?'
  ).get(userId, chain);

  const isDefault = existing.count === 0 ? 1 : 0;

  return db.prepare(`
    INSERT INTO wallets (user_id, chain, address, encrypted_private_key, label, is_default)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(userId, chain, address, encryptedKey, label, isDefault);
}

function getUserWallets(userId, chain = null) {
  if (chain) {
    return db.prepare('SELECT * FROM wallets WHERE user_id = ? AND chain = ? ORDER BY is_default DESC, id ASC')
      .all(userId, chain);
  }
  return db.prepare('SELECT * FROM wallets WHERE user_id = ? ORDER BY chain, is_default DESC, id ASC')
    .all(userId);
}

function getDefaultWallet(userId, chain) {
  return db.prepare('SELECT * FROM wallets WHERE user_id = ? AND chain = ? AND is_default = 1')
    .get(userId, chain);
}

function setDefaultWallet(userId, walletId, chain) {
  db.prepare('UPDATE wallets SET is_default = 0 WHERE user_id = ? AND chain = ?').run(userId, chain);
  db.prepare('UPDATE wallets SET is_default = 1 WHERE id = ? AND user_id = ?').run(walletId, userId);
}

function deleteWallet(walletId, userId) {
  return db.prepare('DELETE FROM wallets WHERE id = ? AND user_id = ?').run(walletId, userId);
}

// ─── DCA Operations ───────────────────────────────────────────────────────────

function createDCAOrder(data) {
  const nextExec = new Date(Date.now() + data.frequencyMinutes * 60000).toISOString();
  return db.prepare(`
    INSERT INTO dca_orders
    (user_id, wallet_id, chain, token_in, token_out, token_in_symbol, token_out_symbol,
     amount_per_order, frequency_minutes, total_orders, next_execution)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    data.userId, data.walletId, data.chain,
    data.tokenIn, data.tokenOut, data.tokenInSymbol, data.tokenOutSymbol,
    data.amountPerOrder, data.frequencyMinutes, data.totalOrders || 0,
    nextExec
  );
}

function getActiveDCAOrders() {
  return db.prepare(`
    SELECT d.*, w.address, w.encrypted_private_key, u.telegram_id
    FROM dca_orders d
    JOIN wallets w ON d.wallet_id = w.id
    JOIN users u ON d.user_id = u.id
    WHERE d.status = 'active' AND d.next_execution <= datetime('now')
    AND (d.total_orders = 0 OR d.completed_orders < d.total_orders)
  `).all();
}

function getUserDCAOrders(userId) {
  return db.prepare(`
    SELECT d.*, w.address, w.label as wallet_label
    FROM dca_orders d
    JOIN wallets w ON d.wallet_id = w.id
    WHERE d.user_id = ?
    ORDER BY d.created_at DESC
  `).all(userId);
}

function updateDCAOrder(id, updates) {
  const fields = Object.keys(updates).map(k => `${k} = ?`).join(', ');
  db.prepare(`UPDATE dca_orders SET ${fields} WHERE id = ?`)
    .run(...Object.values(updates), id);
}

function cancelDCAOrder(id, userId) {
  return db.prepare("UPDATE dca_orders SET status = 'cancelled' WHERE id = ? AND user_id = ?")
    .run(id, userId);
}

// ─── Trade Operations ─────────────────────────────────────────────────────────

function saveTrade(data) {
  return db.prepare(`
    INSERT INTO trades
    (user_id, wallet_id, chain, type, token_in, token_out, token_in_symbol, token_out_symbol,
     amount_in, amount_out, tx_hash, status, dca_order_id, error_message)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    data.userId, data.walletId, data.chain, data.type,
    data.tokenIn, data.tokenOut, data.tokenInSymbol, data.tokenOutSymbol,
    data.amountIn, data.amountOut, data.txHash, data.status,
    data.dcaOrderId || null, data.errorMessage || null
  );
}

function getUserTrades(userId, limit = 20) {
  return db.prepare(`
    SELECT * FROM trades WHERE user_id = ?
    ORDER BY created_at DESC LIMIT ?
  `).all(userId, limit);
}

// ─── Price Alerts ─────────────────────────────────────────────────────────────

function createPriceAlert(data) {
  return db.prepare(`
    INSERT INTO price_alerts (user_id, chain, token_address, token_symbol, condition, target_price)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(data.userId, data.chain, data.tokenAddress, data.tokenSymbol, data.condition, data.targetPrice);
}

function getActivePriceAlerts() {
  return db.prepare(`
    SELECT p.*, u.telegram_id FROM price_alerts p
    JOIN users u ON p.user_id = u.id
    WHERE p.status = 'active'
  `).all();
}

function triggerPriceAlert(id) {
  db.prepare("UPDATE price_alerts SET status = 'triggered' WHERE id = ?").run(id);
}

function getUserAlerts(userId) {
  return db.prepare('SELECT * FROM price_alerts WHERE user_id = ? ORDER BY created_at DESC').all(userId);
}

function cancelAlert(id, userId) {
  return db.prepare("UPDATE price_alerts SET status = 'cancelled' WHERE id = ? AND user_id = ?").run(id, userId);
}

function getDB() { return db; }

module.exports = {
  initDatabase, getDB,
  upsertUser, getUserByTelegramId, updateUserSettings,
  saveWallet, getUserWallets, getDefaultWallet, setDefaultWallet, deleteWallet,
  createDCAOrder, getActiveDCAOrders, getUserDCAOrders, updateDCAOrder, cancelDCAOrder,
  saveTrade, getUserTrades,
  createPriceAlert, getActivePriceAlerts, triggerPriceAlert, getUserAlerts, cancelAlert
};

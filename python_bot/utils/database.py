# utils/database.py  —  Full SQLite database for all bot data

import sqlite3
import json
import os
from datetime import datetime

# Respect DB_PATH env var so Railway volume keeps data across deploys.
# Set DB_PATH=/data/bot.db in Railway Variables, then add a Volume
# mounted at /data — that's the only thing needed for persistence.
_default_path = os.path.join(os.path.dirname(__file__), "..", "data", "bot.db")
DB_PATH = os.environ.get("DB_PATH", _default_path)

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id         INTEGER PRIMARY KEY,
        tg_id      TEXT UNIQUE NOT NULL,
        username   TEXT,
        first_name TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        settings   TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS wallets (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        chain         TEXT NOT NULL,
        address       TEXT NOT NULL,
        enc_key       TEXT NOT NULL,
        label         TEXT DEFAULT 'Wallet',
        wallet_type   TEXT DEFAULT 'paper',
        is_default    INTEGER DEFAULT 0,
        created_at    TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(user_id, chain, address)
    );

    CREATE TABLE IF NOT EXISTS paper_balances (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        asset      TEXT NOT NULL,
        chain      TEXT NOT NULL,
        balance    REAL DEFAULT 0.0,
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(user_id, asset, chain),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS trades (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        wallet_id       INTEGER,
        chain           TEXT NOT NULL,
        trade_type      TEXT NOT NULL,
        mode            TEXT DEFAULT 'paper',
        token_in        TEXT,
        token_out       TEXT,
        symbol_in       TEXT,
        symbol_out      TEXT,
        amount_in       REAL,
        amount_out      REAL,
        price_at_trade  REAL,
        entry_price     REAL DEFAULT 0.0,
        exit_price      REAL DEFAULT 0.0,
        pnl_abs         REAL DEFAULT 0.0,
        tx_hash         TEXT,
        status          TEXT DEFAULT 'pending',
        strategy        TEXT,
        dca_id          INTEGER,
        error_msg       TEXT,
        created_at      TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS dca_orders (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id          INTEGER NOT NULL,
        wallet_id        INTEGER,
        chain            TEXT NOT NULL,
        mode             TEXT DEFAULT 'paper',
        token_in         TEXT NOT NULL,
        token_out        TEXT NOT NULL,
        symbol_in        TEXT,
        symbol_out       TEXT,
        amount_per_order REAL NOT NULL,
        freq_minutes     INTEGER NOT NULL,
        total_orders     INTEGER DEFAULT 0,
        done_orders      INTEGER DEFAULT 0,
        status           TEXT DEFAULT 'active',
        next_run         TEXT,
        created_at       TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS strategies (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        name          TEXT NOT NULL,
        chain         TEXT NOT NULL,
        token_address TEXT NOT NULL,
        token_symbol  TEXT,
        mode          TEXT DEFAULT 'paper',
        wallet_id     INTEGER,
        params        TEXT DEFAULT '{}',
        status        TEXT DEFAULT 'active',
        pnl           REAL DEFAULT 0.0,
        created_at    TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS price_alerts (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        chain         TEXT NOT NULL,
        token_address TEXT NOT NULL,
        token_symbol  TEXT,
        condition     TEXT NOT NULL,
        target_price  REAL NOT NULL,
        current_price REAL,
        status        TEXT DEFAULT 'active',
        created_at    TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS enc_config (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()

# ── Users ─────────────────────────────────────────────────────────────────────

def upsert_user(tg_id, username=None, first_name=None):
    conn = get_conn()
    conn.execute("""
        INSERT INTO users (tg_id, username, first_name) VALUES (?,?,?)
        ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name
    """, (str(tg_id), username, first_name))
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE tg_id=?", (str(tg_id),)).fetchone()
    conn.close()
    return dict(row)

def get_user(tg_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE tg_id=?", (str(tg_id),)).fetchone()
    conn.close()
    return dict(row) if row else None

# ── Wallets ───────────────────────────────────────────────────────────────────

def save_wallet(user_id, chain, address, enc_key, label="Wallet", wallet_type="paper"):
    conn = get_conn()
    existing = conn.execute(
        "SELECT COUNT(*) as c FROM wallets WHERE user_id=? AND chain=?", (user_id, chain)
    ).fetchone()["c"]
    is_default = 1 if existing == 0 else 0
    conn.execute("""
        INSERT OR IGNORE INTO wallets (user_id, chain, address, enc_key, label, wallet_type, is_default)
        VALUES (?,?,?,?,?,?,?)
    """, (user_id, chain, address, enc_key, label, wallet_type, is_default))
    conn.commit()
    conn.close()

def get_wallets(user_id, chain=None, wallet_type=None):
    conn = get_conn()
    q = "SELECT * FROM wallets WHERE user_id=?"
    params = [user_id]
    if chain:
        q += " AND chain=?"; params.append(chain)
    if wallet_type:
        q += " AND wallet_type=?"; params.append(wallet_type)
    q += " ORDER BY is_default DESC, id ASC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_default_wallet(user_id, chain, wallet_type=None):
    conn = get_conn()
    q = "SELECT * FROM wallets WHERE user_id=? AND chain=? AND is_default=1"
    params = [user_id, chain]
    if wallet_type:
        q += " AND wallet_type=?"; params.append(wallet_type)
    row = conn.execute(q, params).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_wallet(wallet_id, user_id):
    conn = get_conn()
    conn.execute("DELETE FROM wallets WHERE id=? AND user_id=?", (wallet_id, user_id))
    conn.commit()
    conn.close()

def set_default_wallet(user_id, wallet_id, chain):
    conn = get_conn()
    conn.execute("UPDATE wallets SET is_default=0 WHERE user_id=? AND chain=?", (user_id, chain))
    conn.execute("UPDATE wallets SET is_default=1 WHERE id=? AND user_id=?", (wallet_id, user_id))
    conn.commit()
    conn.close()

# ── Paper Balances ────────────────────────────────────────────────────────────

def get_paper_balance(user_id, asset, chain="paper"):
    conn = get_conn()
    row = conn.execute(
        "SELECT balance FROM paper_balances WHERE user_id=? AND asset=? AND chain=?",
        (user_id, asset.upper(), chain)
    ).fetchone()
    conn.close()
    return row["balance"] if row else 0.0

def set_paper_balance(user_id, asset, chain, amount):
    conn = get_conn()
    conn.execute("""
        INSERT INTO paper_balances (user_id, asset, chain, balance)
        VALUES (?,?,?,?)
        ON CONFLICT(user_id, asset, chain) DO UPDATE SET balance=excluded.balance, updated_at=datetime('now')
    """, (user_id, asset.upper(), chain, amount))
    conn.commit()
    conn.close()

def add_paper_balance(user_id, asset, chain, amount):
    current = get_paper_balance(user_id, asset, chain)
    set_paper_balance(user_id, asset, chain, current + amount)

def subtract_paper_balance(user_id, asset, chain, amount):
    current = get_paper_balance(user_id, asset, chain)
    if current < amount:
        raise ValueError(f"Insufficient paper balance: have {current:.6f}, need {amount:.6f}")
    set_paper_balance(user_id, asset, chain, current - amount)

def get_all_paper_balances(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM paper_balances WHERE user_id=? AND balance > 0 ORDER BY chain, asset",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Trades ────────────────────────────────────────────────────────────────────

def save_trade(data: dict):
    conn = get_conn()
    r = conn.execute("""
        INSERT INTO trades
        (user_id, wallet_id, chain, trade_type, mode, token_in, token_out,
         symbol_in, symbol_out, amount_in, amount_out, price_at_trade,
         tx_hash, status, strategy, dca_id, error_msg)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("user_id"), data.get("wallet_id"), data.get("chain"),
        data.get("trade_type"), data.get("mode", "paper"),
        data.get("token_in"), data.get("token_out"),
        data.get("symbol_in"), data.get("symbol_out"),
        data.get("amount_in"), data.get("amount_out"), data.get("price_at_trade"),
        data.get("tx_hash"), data.get("status", "success"),
        data.get("strategy"), data.get("dca_id"), data.get("error_msg"),
    ))
    conn.commit()
    tid = r.lastrowid
    conn.close()
    return tid

def get_trades(user_id, limit=20, mode=None):
    conn = get_conn()
    q = "SELECT * FROM trades WHERE user_id=?"
    params = [user_id]
    if mode:
        q += " AND mode=?"; params.append(mode)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── DCA Orders ────────────────────────────────────────────────────────────────

def create_dca(data: dict):
    from datetime import datetime, timedelta
    next_run = (datetime.utcnow() + timedelta(minutes=data["freq_minutes"])).isoformat()
    conn = get_conn()
    r = conn.execute("""
        INSERT INTO dca_orders
        (user_id, wallet_id, chain, mode, token_in, token_out, symbol_in, symbol_out,
         amount_per_order, freq_minutes, total_orders, next_run)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data["user_id"], data.get("wallet_id"), data["chain"], data.get("mode", "paper"),
        data["token_in"], data["token_out"], data.get("symbol_in"), data.get("symbol_out"),
        data["amount_per_order"], data["freq_minutes"], data.get("total_orders", 0), next_run
    ))
    conn.commit()
    oid = r.lastrowid
    conn.close()
    return oid

def get_due_dca_orders():
    conn = get_conn()
    rows = conn.execute("""
        SELECT d.*, w.address, w.enc_key, u.tg_id
        FROM dca_orders d
        LEFT JOIN wallets w ON d.wallet_id = w.id
        JOIN users u ON d.user_id = u.id
        WHERE d.status='active'
          AND d.next_run <= datetime('now')
          AND (d.total_orders=0 OR d.done_orders < d.total_orders)
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_dca(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM dca_orders WHERE user_id=? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_dca(order_id, **kwargs):
    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    conn.execute(f"UPDATE dca_orders SET {sets} WHERE id=?", (*kwargs.values(), order_id))
    conn.commit()
    conn.close()

def cancel_dca(order_id, user_id):
    conn = get_conn()
    conn.execute(
        "UPDATE dca_orders SET status='cancelled' WHERE id=? AND user_id=?", (order_id, user_id)
    )
    conn.commit()
    conn.close()

# ── Strategies ────────────────────────────────────────────────────────────────

def create_strategy(data: dict):
    conn = get_conn()
    r = conn.execute("""
        INSERT INTO strategies
        (user_id, name, chain, token_address, token_symbol, mode, wallet_id, params)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        data["user_id"], data["name"], data["chain"],
        data["token_address"], data.get("token_symbol"),
        data.get("mode", "paper"), data.get("wallet_id"),
        json.dumps(data.get("params", {}))
    ))
    conn.commit()
    sid = r.lastrowid
    conn.close()
    return sid

def get_active_strategies():
    conn = get_conn()
    rows = conn.execute("""
        SELECT s.*, w.address, w.enc_key, u.tg_id
        FROM strategies s
        LEFT JOIN wallets w ON s.wallet_id = w.id
        JOIN users u ON s.user_id = u.id
        WHERE s.status='active'
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_strategies(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM strategies WHERE user_id=? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def stop_strategy(sid, user_id):
    conn = get_conn()
    conn.execute(
        "UPDATE strategies SET status='stopped' WHERE id=? AND user_id=?", (sid, user_id)
    )
    conn.commit()
    conn.close()

def update_strategy_pnl(sid, pnl_delta):
    conn = get_conn()
    conn.execute("UPDATE strategies SET pnl=pnl+? WHERE id=?", (pnl_delta, sid))
    conn.commit()
    conn.close()

# ── Price Alerts ──────────────────────────────────────────────────────────────

def create_alert(data: dict):
    conn = get_conn()
    r = conn.execute("""
        INSERT INTO price_alerts
        (user_id, chain, token_address, token_symbol, condition, target_price)
        VALUES (?,?,?,?,?,?)
    """, (
        data["user_id"], data["chain"], data["token_address"],
        data.get("token_symbol"), data["condition"], data["target_price"]
    ))
    conn.commit()
    aid = r.lastrowid
    conn.close()
    return aid

def get_active_alerts():
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.*, u.tg_id FROM price_alerts p
        JOIN users u ON p.user_id = u.id
        WHERE p.status='active'
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def trigger_alert(alert_id):
    conn = get_conn()
    conn.execute("UPDATE price_alerts SET status='triggered' WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()

def get_user_alerts(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM price_alerts WHERE user_id=? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def cancel_alert(alert_id, user_id):
    conn = get_conn()
    conn.execute(
        "UPDATE price_alerts SET status='cancelled' WHERE id=? AND user_id=?", (alert_id, user_id)
    )
    conn.commit()
    conn.close()

# ── Encryption Config ─────────────────────────────────────────────────────────

def get_enc_key():
    conn = get_conn()
    row = conn.execute("SELECT value FROM enc_config WHERE key='enc_key'").fetchone()
    conn.close()
    return row["value"] if row else None

def set_enc_key(key_hex: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO enc_config (key, value) VALUES ('enc_key', ?)", (key_hex,)
    )
    conn.commit()
    conn.close()

# ── Trade Outcomes (for learning engine) ─────────────────────────────────────

def ensure_learning_tables():
    """Add learning tables and columns. Safe to call multiple times — never crashes on restart."""
    conn = get_conn()

    # Create tables (IF NOT EXISTS is safe)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS trade_outcomes (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id  INTEGER NOT NULL,
        trade_id     INTEGER,
        entry_price  REAL NOT NULL,
        exit_price   REAL NOT NULL,
        amount       REAL NOT NULL,
        pnl_pct      REAL NOT NULL,
        pnl_abs      REAL NOT NULL,
        won          INTEGER NOT NULL,
        signal_data  TEXT DEFAULT '{}',
        created_at   TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (strategy_id) REFERENCES strategies(id)
    );

    CREATE TABLE IF NOT EXISTS learning_logs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id   INTEGER NOT NULL,
        win_rate      REAL,
        avg_win_pct   REAL,
        avg_loss_pct  REAL,
        adjustments   TEXT DEFAULT '[]',
        params_before TEXT DEFAULT '{}',
        params_after  TEXT DEFAULT '{}',
        created_at    TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (strategy_id) REFERENCES strategies(id)
    );

    CREATE TABLE IF NOT EXISTS message_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id       TEXT NOT NULL,
        chat_id     TEXT NOT NULL,
        message_id  INTEGER NOT NULL,
        msg_type    TEXT DEFAULT 'signal',
        created_at  TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()

    # Add columns to trades table — each wrapped in try/except so
    # restarts never crash even if columns already exist
    new_columns = [
        ("pnl_abs",      "REAL DEFAULT 0.0"),
        ("entry_price",  "REAL DEFAULT 0.0"),
        ("exit_price",   "REAL DEFAULT 0.0"),
    ]
    for col_name, col_def in new_columns:
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_def}")
            conn.commit()
        except Exception:
            pass  # Column already exists — safe to ignore

    conn.close()

def save_trade_outcome(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO trade_outcomes
        (strategy_id, trade_id, entry_price, exit_price, amount,
         pnl_pct, pnl_abs, won, signal_data)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        data["strategy_id"], data.get("trade_id"),
        data["entry_price"],  data["exit_price"], data["amount"],
        data["pnl_pct"],      data["pnl_abs"],    data["won"],
        data.get("signal_data", "{}")
    ))
    conn.commit()
    conn.close()

def get_strategy_outcomes(strategy_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trade_outcomes WHERE strategy_id=? ORDER BY created_at ASC",
        (strategy_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_learning_log(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO learning_logs
        (strategy_id, win_rate, avg_win_pct, avg_loss_pct,
         adjustments, params_before, params_after)
        VALUES (?,?,?,?,?,?,?)
    """, (
        data["strategy_id"], data["win_rate"],
        data["avg_win_pct"], data["avg_loss_pct"],
        data["adjustments"], data["params_before"], data["params_after"]
    ))
    conn.commit()
    conn.close()

def get_learning_logs(strategy_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM learning_logs WHERE strategy_id=? ORDER BY created_at DESC LIMIT 20",
        (strategy_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_strategy_params(strategy_id: int, new_params: dict):
    conn = get_conn()
    conn.execute(
        "UPDATE strategies SET params=? WHERE id=?",
        (json.dumps(new_params), strategy_id)
    )
    conn.commit()
    conn.close()

def get_user_strategies_by_id(strategy_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM strategies WHERE id=?", (strategy_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_trades_since(user_id: int, since_iso: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades WHERE user_id=? AND created_at >= ? ORDER BY created_at DESC",
        (user_id, since_iso)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Message Log (for cleanup) ─────────────────────────────────────────────────

def log_message(tg_id: str, chat_id: str, message_id: int, msg_type: str = "signal"):
    conn = get_conn()
    conn.execute(
        "INSERT INTO message_log (tg_id, chat_id, message_id, msg_type) VALUES (?,?,?,?)",
        (str(tg_id), str(chat_id), message_id, msg_type)
    )
    conn.commit()
    conn.close()

def get_old_messages(older_than_iso: str, msg_type: str = None) -> list:
    conn = get_conn()
    q = "SELECT * FROM message_log WHERE created_at < ?"
    params = [older_than_iso]
    if msg_type:
        q += " AND msg_type=?"; params.append(msg_type)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_message_log_entries(ids: list):
    if not ids:
        return
    conn = get_conn()
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM message_log WHERE id IN ({placeholders})", ids)
    conn.commit()
    conn.close()

def get_last_weekly_report(tg_id: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM message_log WHERE tg_id=? AND msg_type='weekly_report' ORDER BY created_at DESC LIMIT 1",
        (str(tg_id),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

# ── User Reset (manual only — triggered by /reset command) ───────────────────

def reset_user_data(user_id: int, what: list):
    """
    Selectively wipe a user's data. 'what' is a list of keys:
    'paper'      — paper balances only
    'trades'     — trade history
    'strategies' — stop and delete all strategies + learning data
    'dca'        — cancel all DCA orders
    'alerts'     — cancel all alerts
    'wallets'    — delete all wallets (DANGEROUS)
    'all'        — everything above
    """
    conn = get_conn()
    targets = set(what)
    if "all" in targets:
        targets = {"paper","trades","strategies","dca","alerts","wallets"}

    if "paper" in targets:
        conn.execute("DELETE FROM paper_balances WHERE user_id=?", (user_id,))

    if "trades" in targets:
        conn.execute("DELETE FROM trades WHERE user_id=?", (user_id,))
        conn.execute(
            "DELETE FROM trade_outcomes WHERE strategy_id IN "
            "(SELECT id FROM strategies WHERE user_id=?)", (user_id,)
        )

    if "strategies" in targets:
        conn.execute(
            "DELETE FROM learning_logs WHERE strategy_id IN "
            "(SELECT id FROM strategies WHERE user_id=?)", (user_id,)
        )
        conn.execute(
            "DELETE FROM trade_outcomes WHERE strategy_id IN "
            "(SELECT id FROM strategies WHERE user_id=?)", (user_id,)
        )
        conn.execute("DELETE FROM strategies WHERE user_id=?", (user_id,))

    if "dca" in targets:
        conn.execute("DELETE FROM dca_orders WHERE user_id=?", (user_id,))

    if "alerts" in targets:
        conn.execute("DELETE FROM price_alerts WHERE user_id=?", (user_id,))

    if "wallets" in targets:
        conn.execute("DELETE FROM wallets WHERE user_id=?", (user_id,))

    conn.commit()
    conn.close()
    return list(targets)

# 🤖 CryptoBot — Python Telegram Bot

Full-featured multi-chain trading bot in Python. One file to edit, then run.

## ⚡ Quick Start (3 Steps)

### Step 1 — Get a Bot Token
1. Open Telegram → search **@BotFather**
2. Send `/newbot` → follow prompts → copy the token

### Step 2 — Add Your Token
Open `config/secrets.py` and replace the placeholder:
```python
BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ"  # ← paste here
```
That's the **only file you need to edit**.

### Step 3 — Install & Run
```bash
cd python_bot
pip install -r requirements.txt
python bot.py
```
Open Telegram → find your bot → send `/start` 🎉

---

## 📱 What You Can Do

### 📝 Paper Trading (Virtual Money — No Risk)
- Generate a paper wallet (auto-topped up with 1 ETH/BNB/SOL to start)
- Top up your paper balance anytime from the menu
- Buy and sell tokens at real market prices
- Track your paper portfolio and P&L

### 💎 Live Trading (Real Crypto)
- Import your existing wallet via private key
- Fund it by sending crypto to your address
- Execute real swaps via 1inch + Uniswap/PancakeSwap/Jupiter
- Full trade history on-chain

### 🤖 Auto-Trading Strategies (Paper & Live)
| Strategy | How It Works |
|----------|-------------|
| **RSI Oversold** | Buys when RSI < 30, sells when RSI > 70 |
| **MA Crossover** | Buys on golden cross, sells on death cross |
| **Momentum** | Buys on +2% surge, sells on -2% drop |
| **Bollinger Bands** | Buys at lower band, sells at upper band |
| **MACD** | Trades on MACD signal crossovers |
| **Auto DCA** | Fixed purchases on your schedule |
| **Grid Trading** | Profits from volatility in a price range |

### 📊 DCA Bots
Automatically buy tokens at regular intervals:
```
/newdca ethereum 0xTokenAddress 0.01 1440
```
→ Buys 0.01 ETH of that token every day (1440 min)

### 🔔 Price Alerts
```
/alert ethereum native above 5000
/alert solana TokenMint below 0.001
```
Notified instantly when price hits your target.

---

## 💬 All Commands

```
/start        Main menu (use this for everything!)
/price        Live prices for all chains
/price [chain] [address]   Price for any token
/pbuy [chain] [token] [amount]    Paper buy
/psell [chain] [token] [amount]   Paper sell
/newdca [chain] [token] [amount] [minutes]   Create DCA
/dcalist      View DCA orders
/alert [chain] [token] [above|below] [price]  Set alert
/alerts       View & cancel alerts
/mystrats     View running strategies
/help         Full command reference
```

---

## ⛓️ Supported Chains
`ethereum` `bsc` `polygon` `arbitrum` `base` `avalanche` `solana`

Use aliases: `eth`, `bnb`, `poly`, `arb`, `avax`, `sol`

---

## 🔐 Security Notes
- Private keys encrypted with **AES-256-GCM** before storage
- Encryption key auto-generated and stored in local DB on first run
- Import messages are **auto-deleted** from Telegram
- `config/secrets.py` is in `.gitignore` — never committed
- ⚠️ Run on your own VPS/machine, not shared hosting

---

## 📁 File Structure
```
python_bot/
├── bot.py              ← Main bot (run this)
├── requirements.txt    ← pip install -r requirements.txt
├── config/
│   ├── secrets.py      ← ADD YOUR TOKEN HERE (only file to edit)
│   └── chains.py       ← Chain/DEX configs
├── utils/
│   ├── database.py     ← SQLite (auto-created)
│   ├── encryption.py   ← AES-256 key storage
│   └── prices.py       ← CoinGecko + DexScreener
├── wallet/
│   ├── generator.py    ← HD wallet generation
│   └── balances.py     ← On-chain balance queries
├── trading/
│   ├── paper_trade.py  ← Simulated trading
│   └── evm_swap.py     ← Real swap execution
├── strategies/
│   └── engine.py       ← All trading strategies + signals
└── data/               ← SQLite DB stored here (auto-created)
```

---

## 🌐 Optional API Keys (Free Tiers)
Edit `config/secrets.py` to add these for better performance:

| Key | Where to Get | Benefit |
|-----|-------------|---------|
| `COINGECKO_API_KEY` | [coingecko.com/api](https://coingecko.com/api) | Higher rate limits |
| `ONEINCH_API_KEY` | [portal.1inch.dev](https://portal.1inch.dev) | Better swap routing |

---

## ☁️ Run 24/7 on a VPS (Optional)
```bash
# Install screen or tmux
sudo apt install screen

# Start in background
screen -S cryptobot
cd python_bot && python bot.py

# Detach: Ctrl+A then D
# Reattach: screen -r cryptobot
```

Or use systemd for auto-restart on reboot.

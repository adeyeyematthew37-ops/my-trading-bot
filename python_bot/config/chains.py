# config/chains.py  —  All supported blockchain configurations

CHAINS = {
    "ethereum": {
        "id": 1, "name": "Ethereum", "symbol": "ETH",
        "emoji": "⟠", "type": "evm",
        "explorer": "https://etherscan.io",
        "native": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "wrapped": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "router": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        "coingecko_id": "ethereum",
    },
    "bsc": {
        "id": 56, "name": "BNB Chain", "symbol": "BNB",
        "emoji": "🔶", "type": "evm",
        "explorer": "https://bscscan.com",
        "native": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "wrapped": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "router": "0x10ED43C718714eb63d5aA57B78B54704E256024E",
        "coingecko_id": "binancecoin",
    },
    "polygon": {
        "id": 137, "name": "Polygon", "symbol": "MATIC",
        "emoji": "🟣", "type": "evm",
        "explorer": "https://polygonscan.com",
        "native": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "wrapped": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "router": "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",
        "coingecko_id": "matic-network",
    },
    "arbitrum": {
        "id": 42161, "name": "Arbitrum", "symbol": "ETH",
        "emoji": "🔵", "type": "evm",
        "explorer": "https://arbiscan.io",
        "native": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "wrapped": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "router": "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506",
        "coingecko_id": "ethereum",
    },
    "base": {
        "id": 8453, "name": "Base", "symbol": "ETH",
        "emoji": "🔷", "type": "evm",
        "explorer": "https://basescan.org",
        "native": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "wrapped": "0x4200000000000000000000000000000000000006",
        "router": "0x8357227D4eDc78991Db6FDB9bD6ADE250536dE1d",
        "coingecko_id": "ethereum",
    },
    "avalanche": {
        "id": 43114, "name": "Avalanche", "symbol": "AVAX",
        "emoji": "🔺", "type": "evm",
        "explorer": "https://snowtrace.io",
        "native": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        "wrapped": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
        "router": "0x60aE616a2155Ee3d9A68541Ba4544862310933d4",
        "coingecko_id": "avalanche-2",
    },
    "solana": {
        "id": "solana", "name": "Solana", "symbol": "SOL",
        "emoji": "◎", "type": "solana",
        "explorer": "https://solscan.io",
        "native": "So11111111111111111111111111111111111111112",
        "coingecko_id": "solana",
    },
    "near": {
        "id": "near", "name": "NEAR Protocol", "symbol": "NEAR",
        "emoji": "Ⓝ", "type": "near",
        "explorer": "https://nearblocks.io",
        "native": "near",
        "coingecko_id": "near",
        "wallet_app": "MyNearWallet / NEAR Wallet / HOT Wallet",
        # Perp & DeFi DEXs on NEAR
        "perp_dexs": {
            "rhea": {
                "name": "Rhea Finance",
                "url": "https://rhea.finance",
                "description": "NEAR-native perpetuals DEX",
                "markets_url": "https://rhea.finance/trade",
            },
            "aster": {
                "name": "Aster Marketplace",
                "url": "https://aster.fi",
                "description": "Perps + prediction markets on NEAR — up to 100x leverage",
                "markets_url": "https://aster.fi/trade",
                "predict_url": "https://aster.fi/predict",
            },
            "orderly": {
                "name": "Orderly Network",
                "url": "https://orderly.network",
                "api": "https://api-evm.orderly.org",
                "description": "Institutional-grade perp orderbook on NEAR",
            },
            "ref_finance": {
                "name": "Ref Finance",
                "url": "https://app.ref.finance",
                "description": "Main AMM DEX on NEAR — spot trading",
            },
        },
    },
    "hot": {
        "id": "hot", "name": "HOT Chain", "symbol": "HOT",
        "emoji": "🔥", "type": "near",  # HOT Chain is built on NEAR tech
        "explorer": "https://explorer.hot.io",
        "native": "hot.hot-labs.near",
        "coingecko_id": "hot-labs",
        "wallet_app": "HOT Wallet (app.hotdao.ai)",
        "description": (
            "HOT Chain is a Layer-2 network built by HOT Protocol on NEAR. "
            "Your HOT Wallet holds assets on NEAR and HOT Chain. "
            "Import using your NEAR private key or seed phrase."
        ),
        "perp_dexs": {
            "rhea": {
                "name": "Rhea Finance",
                "url": "https://rhea.finance",
                "description": "Trade perps with HOT wallet via NEAR integration",
                "markets_url": "https://rhea.finance/trade",
            },
            "aster": {
                "name": "Aster Marketplace",
                "url": "https://aster.fi",
                "description": "Perps + prediction markets via HOT/NEAR wallet",
                "markets_url": "https://aster.fi/trade",
                "predict_url": "https://aster.fi/predict",
            },
        },
    },
}

CHAIN_ALIASES = {
    "eth": "ethereum", "ether": "ethereum",
    "bnb": "bsc", "bnbchain": "bsc", "bscchain": "bsc",
    "poly": "polygon", "matic": "polygon",
    "arb": "arbitrum",
    "avax": "avalanche",
    "sol": "solana",
    "near protocol": "near",
    "hot chain": "hot",
    "hotchain": "hot",
    "hot wallet": "hot",
}


# Common tokens for quick reference
COMMON_TOKENS = {
    "ethereum": {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        "UNI":  "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
    },
    "bsc": {
        "USDT": "0x55d398326f99059fF775485246999027B3197955",
        "CAKE": "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
        "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
    },
}

def get_chain(name: str):
    key = name.lower().strip()
    key = CHAIN_ALIASES.get(key, key)
    return key, CHAINS.get(key)

def all_chains():
    return [(k, v) for k, v in CHAINS.items()]

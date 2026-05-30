# wallet/balances.py  —  Real blockchain balance queries

from web3 import Web3
from config.chains import CHAINS
from config.secrets import RPC_URLS

_providers: dict = {}

ERC20_ABI = [
    {"name": "balanceOf",  "type": "function", "inputs": [{"name": "a", "type": "address"}],
     "outputs": [{"type": "uint256"}], "stateMutability": "view"},
    {"name": "decimals",   "type": "function", "inputs": [],
     "outputs": [{"type": "uint8"}],  "stateMutability": "view"},
    {"name": "symbol",     "type": "function", "inputs": [],
     "outputs": [{"type": "string"}], "stateMutability": "view"},
    {"name": "name",       "type": "function", "inputs": [],
     "outputs": [{"type": "string"}], "stateMutability": "view"},
]

def get_w3(chain_key: str) -> Web3:
    if chain_key not in _providers:
        url = RPC_URLS.get(chain_key, "")
        if not url:
            raise ValueError(f"No RPC URL configured for {chain_key}")
        _providers[chain_key] = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
    return _providers[chain_key]

def get_native_balance(address: str, chain_key: str) -> float:
    """Get native token balance (ETH/BNB/MATIC etc)."""
    w3 = get_w3(chain_key)
    bal = w3.eth.get_balance(Web3.to_checksum_address(address))
    return float(Web3.from_wei(bal, "ether"))

def get_erc20_balance(address: str, token_address: str, chain_key: str) -> dict:
    """Get ERC20 token balance."""
    w3 = get_w3(chain_key)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI
    )
    raw = contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
    decimals = contract.functions.decimals().call()
    symbol = contract.functions.symbol().call()
    return {
        "balance": raw / (10 ** decimals),
        "raw": raw,
        "decimals": decimals,
        "symbol": symbol,
    }

def get_token_info(token_address: str, chain_key: str) -> dict:
    """Get basic ERC20 token metadata."""
    w3 = get_w3(chain_key)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI
    )
    return {
        "name": contract.functions.name().call(),
        "symbol": contract.functions.symbol().call(),
        "decimals": contract.functions.decimals().call(),
        "address": token_address,
    }

def get_solana_balance(address: str) -> float:
    """Get SOL balance."""
    import requests
    rpc = RPC_URLS.get("solana", "https://api.mainnet-beta.solana.com")
    try:
        r = requests.post(rpc, json={
            "jsonrpc": "2.0", "id": 1, "method": "getBalance",
            "params": [address]
        }, timeout=8)
        lamports = r.json()["result"]["value"]
        return lamports / 1_000_000_000
    except Exception:
        return 0.0

def get_gas_price(chain_key: str) -> dict:
    w3 = get_w3(chain_key)
    fee = w3.eth.fee_history(1, "latest", [50])
    base = fee["baseFeePerGas"][-1] if fee["baseFeePerGas"] else 0
    return {
        "gas_price_gwei": float(Web3.from_wei(base, "gwei")),
        "base_fee": base,
    }

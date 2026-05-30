# trading/evm_swap.py  —  Live EVM swaps via Uniswap V2 / 1inch

import json
from web3 import Web3
from wallet.balances import get_w3, ERC20_ABI
from wallet.generator import get_evm_signer
from config.chains import CHAINS
from config.secrets import ONEINCH_API_KEY
import requests

NATIVE = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

UNIV2_ROUTER_ABI = [
    {"name": "swapExactETHForTokens", "type": "function", "stateMutability": "payable",
     "inputs": [{"name": "amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},
                {"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],
     "outputs": [{"type": "uint256[]"}]},
    {"name": "swapExactTokensForETH", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},
                {"name":"path","type":"address[]"},{"name":"to","type":"address"},
                {"name":"deadline","type":"uint256"}],
     "outputs": [{"type": "uint256[]"}]},
    {"name": "swapExactTokensForTokens","type":"function","stateMutability":"nonpayable",
     "inputs": [{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},
                {"name":"path","type":"address[]"},{"name":"to","type":"address"},
                {"name":"deadline","type":"uint256"}],
     "outputs": [{"type": "uint256[]"}]},
    {"name": "getAmountsOut","type":"function","stateMutability":"view",
     "inputs": [{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],
     "outputs": [{"type": "uint256[]"}]},
]

def _get_1inch_swap(chain_id, token_in, token_out, amount, from_addr, slippage=1):
    if not ONEINCH_API_KEY:
        return None
    try:
        r = requests.get(
            f"https://api.1inch.dev/swap/v6.0/{chain_id}/swap",
            params={"src": token_in, "dst": token_out, "amount": str(amount),
                    "from": from_addr, "slippage": str(slippage)},
            headers={"Authorization": f"Bearer {ONEINCH_API_KEY}"},
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get("tx")
    except Exception:
        pass
    return None

def _ensure_approval(w3, signer, token_addr, spender, amount):
    contract = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
    allowance = contract.functions.allowance(signer.address, spender).call()
    if allowance < amount:
        tx = contract.functions.approve(spender, 2**256 - 1).build_transaction({
            "from": signer.address,
            "nonce": w3.eth.get_transaction_count(signer.address),
            "gasPrice": w3.eth.gas_price,
        })
        signed = signer.sign_transaction(tx)
        txh = w3.eth.send_raw_transaction(signed.raw_transaction)
        w3.eth.wait_for_transaction_receipt(txh)

def execute_evm_swap(chain_key: str, enc_key: str, token_in: str,
                     token_out: str, amount_wei: int, slippage: float = 1.0) -> dict:
    """Execute a real EVM swap. Returns {tx_hash, status}."""
    chain = CHAINS[chain_key]
    w3 = get_w3(chain_key)
    signer = get_evm_signer(enc_key)
    is_native_in = token_in.lower() == NATIVE.lower()
    is_native_out = token_out.lower() == NATIVE.lower()

    # Try 1inch first
    oneinch_tx = _get_1inch_swap(chain["id"], token_in, token_out, amount_wei, signer.address, slippage)
    if oneinch_tx:
        tx = {
            "to": oneinch_tx["to"],
            "data": oneinch_tx["data"],
            "value": int(oneinch_tx.get("value", 0)),
            "gas": int(oneinch_tx.get("gas", 300000) * 1.2),
            "gasPrice": w3.eth.gas_price,
            "nonce": w3.eth.get_transaction_count(signer.address),
            "chainId": chain["id"],
        }
        signed = signer.sign_transaction(tx)
        txh = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(txh, timeout=120)
        return {"tx_hash": txh.hex(), "status": "success" if receipt.status == 1 else "failed"}

    # Fallback: direct Uniswap V2 router
    router_addr = Web3.to_checksum_address(chain["router"])
    router = w3.eth.contract(address=router_addr, abi=UNIV2_ROUTER_ABI)
    deadline = w3.eth.get_block("latest")["timestamp"] + 1200
    actual_in = chain["wrapped"] if is_native_in else token_in
    actual_out = chain["wrapped"] if is_native_out else token_out
    path = [Web3.to_checksum_address(actual_in), Web3.to_checksum_address(actual_out)]

    amounts_out = router.functions.getAmountsOut(amount_wei, path).call()
    expected = amounts_out[-1]
    min_out = int(expected * (100 - slippage) / 100)

    nonce = w3.eth.get_transaction_count(signer.address)
    gas_price = w3.eth.gas_price

    if is_native_in:
        tx = router.functions.swapExactETHForTokens(
            min_out, path, signer.address, deadline
        ).build_transaction({"from": signer.address, "value": amount_wei,
                             "gas": 300000, "gasPrice": gas_price, "nonce": nonce, "chainId": chain["id"]})
    elif is_native_out:
        _ensure_approval(w3, signer, token_in, router_addr, amount_wei)
        tx = router.functions.swapExactTokensForETH(
            amount_wei, min_out, path, signer.address, deadline
        ).build_transaction({"from": signer.address, "value": 0,
                             "gas": 300000, "gasPrice": gas_price, "nonce": nonce, "chainId": chain["id"]})
    else:
        _ensure_approval(w3, signer, token_in, router_addr, amount_wei)
        tx = router.functions.swapExactTokensForTokens(
            amount_wei, min_out, path, signer.address, deadline
        ).build_transaction({"from": signer.address, "value": 0,
                             "gas": 400000, "gasPrice": gas_price, "nonce": nonce, "chainId": chain["id"]})

    signed = signer.sign_transaction(tx)
    txh = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(txh, timeout=120)
    return {"tx_hash": txh.hex(), "status": "success" if receipt.status == 1 else "failed",
            "amount_out": str(expected)}

def send_native(chain_key: str, enc_key: str, to: str, amount_ether: float) -> dict:
    w3 = get_w3(chain_key)
    signer = get_evm_signer(enc_key)
    amount_wei = Web3.to_wei(amount_ether, "ether")
    tx = {"to": Web3.to_checksum_address(to), "value": amount_wei,
          "gas": 21000, "gasPrice": w3.eth.gas_price,
          "nonce": w3.eth.get_transaction_count(signer.address),
          "chainId": CHAINS[chain_key]["id"]}
    signed = signer.sign_transaction(tx)
    txh = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(txh, timeout=120)
    return {"tx_hash": txh.hex(), "status": "success" if receipt.status == 1 else "failed"}

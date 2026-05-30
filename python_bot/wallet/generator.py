# wallet/generator.py  —  HD wallet generation for EVM + Solana

from eth_account import Account
from mnemonic import Mnemonic
from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
from utils.encryption import encrypt, decrypt

Account.enable_unaudited_hdwallet_features()

# ── EVM Wallets ───────────────────────────────────────────────────────────────

def generate_evm_wallet() -> dict:
    """Generate a brand-new EVM wallet with mnemonic."""
    account, mnemonic = Account.create_with_mnemonic()
    return {
        "address": account.address,
        "private_key": account.key.hex(),
        "mnemonic": mnemonic,
        "type": "evm",
    }

def evm_from_private_key(pk: str) -> dict:
    account = Account.from_key(pk)
    return {
        "address": account.address,
        "private_key": account.key.hex(),
        "mnemonic": None,
        "type": "evm",
    }

def evm_from_mnemonic(mnemonic: str, index: int = 0) -> dict:
    account = Account.from_mnemonic(mnemonic, account_path=f"m/44'/60'/0'/0/{index}")
    return {
        "address": account.address,
        "private_key": account.key.hex(),
        "mnemonic": mnemonic,
        "type": "evm",
    }

# ── Solana Wallets ────────────────────────────────────────────────────────────

def generate_solana_wallet() -> dict:
    """Generate a new Solana wallet."""
    import os, base58
    from solders.keypair import Keypair  # type: ignore
    kp = Keypair()
    sk_bytes = bytes(kp)          # 64-byte secret key
    pk_b58 = base58.b58encode(sk_bytes).decode()
    return {
        "address": str(kp.pubkey()),
        "private_key": pk_b58,
        "mnemonic": None,
        "type": "solana",
    }

def solana_from_private_key(pk_b58: str) -> dict:
    import base58
    from solders.keypair import Keypair  # type: ignore
    kp = Keypair.from_bytes(base58.b58decode(pk_b58))
    return {
        "address": str(kp.pubkey()),
        "private_key": pk_b58,
        "mnemonic": None,
        "type": "solana",
    }

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_evm_signer(enc_key: str):
    """Return an eth_account LocalAccount from encrypted private key."""
    pk = decrypt(enc_key)
    return Account.from_key(pk)

def get_solana_keypair(enc_key: str):
    """Return a solders Keypair from encrypted private key."""
    import base58
    from solders.keypair import Keypair  # type: ignore
    pk = decrypt(enc_key)
    return Keypair.from_bytes(base58.b58decode(pk))

def short_addr(address: str) -> str:
    return f"{address[:6]}...{address[-4:]}"

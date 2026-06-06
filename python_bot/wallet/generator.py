# wallet/generator.py
# Full multi-chain wallet generator
# Solana: Phantom-compatible (BIP39 mnemonic + ed25519 derivation)
# EVM: MetaMask-compatible (BIP44 HD wallet)
# Import: accepts base58 key, hex key, byte array, OR 12/24-word mnemonic

from eth_account import Account
from mnemonic import Mnemonic
from utils.encryption import encrypt, decrypt

Account.enable_unaudited_hdwallet_features()

# ── EVM Wallets (MetaMask-compatible) ─────────────────────────────────────────

def generate_evm_wallet() -> dict:
    """Generate BIP39 EVM wallet — works in MetaMask, Trust Wallet etc."""
    account, mnemonic = Account.create_with_mnemonic()
    return {
        "address":     account.address,
        "private_key": account.key.hex(),
        "mnemonic":    mnemonic,
        "type":        "evm",
    }

def evm_from_private_key(pk: str) -> dict:
    """Import EVM wallet from private key (hex with or without 0x prefix)."""
    pk = pk.strip()
    if not pk.startswith("0x"):
        pk = "0x" + pk
    account = Account.from_key(pk)
    return {
        "address":     account.address,
        "private_key": account.key.hex(),
        "mnemonic":    None,
        "type":        "evm",
    }

def evm_from_mnemonic(phrase: str, index: int = 0) -> dict:
    """Derive EVM wallet from seed phrase."""
    account = Account.from_mnemonic(
        phrase.strip(), account_path=f"m/44'/60'/0'/0/{index}"
    )
    return {
        "address":     account.address,
        "private_key": account.key.hex(),
        "mnemonic":    phrase.strip(),
        "type":        "evm",
    }

# ── Solana Wallets (Phantom-compatible) ───────────────────────────────────────

def generate_solana_wallet() -> dict:
    """
    Generate a Phantom-compatible Solana wallet.
    Uses BIP39 mnemonic + ed25519-slip derivation path m/44'/501'/0'/0'
    which is exactly what Phantom uses — you can import the seed phrase
    directly into Phantom and get the same wallet.
    """
    from solders.keypair import Keypair          # type: ignore
    from bip_utils import (
        Bip39MnemonicGenerator, Bip39SeedGenerator,
        Bip39WordsNum, Bip44, Bip44Coins, Bip44Changes
    )
    import base58

    # 1. Generate 12-word mnemonic (Phantom default)
    mnemonic = str(Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_12))

    # 2. Derive seed
    seed_bytes = bytes(Bip39SeedGenerator(mnemonic).Generate())

    # 3. Derive keypair using Phantom's exact path: m/44'/501'/0'/0'
    bip44_ctx = (
        Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
        .Purpose()
        .Coin()
        .Account(0)
        .Change(Bip44Changes.CHAIN_EXT)
    )
    raw_privkey = bip44_ctx.PrivateKey().Raw().ToBytes()  # 32 bytes

    # 4. Build keypair (solders wants 64 bytes: privkey + pubkey)
    kp = Keypair.from_seed(raw_privkey)

    # 5. Encode full 64-byte secret key as base58 (standard Solana format)
    full_secret = bytes(kp)  # 64 bytes
    private_key_b58 = base58.b58encode(full_secret).decode()

    return {
        "address":     str(kp.pubkey()),
        "private_key": private_key_b58,
        "mnemonic":    mnemonic,
        "type":        "solana",
        "derivation":  "m/44'/501'/0'/0' (Phantom compatible)",
    }

def solana_from_mnemonic(phrase: str, index: int = 0) -> dict:
    """
    Import Solana wallet from a seed phrase.
    Uses the same Phantom derivation path — so if you generated the
    wallet in Phantom and have the seed phrase, this recovers it exactly.
    """
    from solders.keypair import Keypair          # type: ignore
    from bip_utils import (
        Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
    )
    import base58

    phrase = phrase.strip()
    seed_bytes = bytes(Bip39SeedGenerator(phrase).Generate())
    bip44_ctx = (
        Bip44.FromSeed(seed_bytes, Bip44Coins.SOLANA)
        .Purpose()
        .Coin()
        .Account(index)
        .Change(Bip44Changes.CHAIN_EXT)
    )
    raw_privkey = bip44_ctx.PrivateKey().Raw().ToBytes()
    kp = Keypair.from_seed(raw_privkey)
    full_secret = bytes(kp)
    private_key_b58 = base58.b58encode(full_secret).decode()

    return {
        "address":     str(kp.pubkey()),
        "private_key": private_key_b58,
        "mnemonic":    phrase,
        "type":        "solana",
    }

def solana_from_private_key(key_input: str) -> dict:
    """
    Import Solana wallet from a private key.

    Accepts ALL common formats:
    - Base58 encoded 64-byte secret key  (most common — exported from Phantom/Solflare)
    - Base58 encoded 32-byte seed        (some wallets)
    - Hex string 64 bytes                (0x... or raw)
    - Comma/bracket separated byte array ([1,2,3,...] format)
    - 12 or 24 word mnemonic phrase      (seed phrase)
    """
    from solders.keypair import Keypair          # type: ignore
    import base58

    key_input = key_input.strip()

    # ── Case 1: Mnemonic phrase (12 or 24 words) ──────────────────────────────
    word_count = len(key_input.split())
    if word_count in (12, 24):
        return solana_from_mnemonic(key_input)

    # ── Case 2: Byte array format [1,2,3,...] or (1,2,3,...) ──────────────────
    if key_input.startswith("[") or key_input.startswith("("):
        import json
        clean = key_input.replace("(", "[").replace(")", "]")
        byte_list = json.loads(clean)
        key_bytes = bytes(byte_list)
        if len(key_bytes) == 64:
            kp = Keypair.from_bytes(key_bytes)
        elif len(key_bytes) == 32:
            kp = Keypair.from_seed(key_bytes)
        else:
            raise ValueError(f"Byte array must be 32 or 64 bytes, got {len(key_bytes)}")
        full_secret = bytes(kp)
        return {
            "address":     str(kp.pubkey()),
            "private_key": base58.b58encode(full_secret).decode(),
            "mnemonic":    None,
            "type":        "solana",
        }

    # ── Case 3: Hex string ─────────────────────────────────────────────────────
    hex_clean = key_input.lstrip("0x")
    if all(c in "0123456789abcdefABCDEF" for c in hex_clean) and len(hex_clean) in (64, 128):
        key_bytes = bytes.fromhex(hex_clean)
        if len(key_bytes) == 64:
            kp = Keypair.from_bytes(key_bytes)
        else:
            kp = Keypair.from_seed(key_bytes)
        full_secret = bytes(kp)
        return {
            "address":     str(kp.pubkey()),
            "private_key": base58.b58encode(full_secret).decode(),
            "mnemonic":    None,
            "type":        "solana",
        }

    # ── Case 4: Base58 (most common — what Phantom exports) ───────────────────
    try:
        key_bytes = base58.b58decode(key_input)
        if len(key_bytes) == 64:
            kp = Keypair.from_bytes(key_bytes)
        elif len(key_bytes) == 32:
            kp = Keypair.from_seed(key_bytes)
        else:
            raise ValueError(
                f"Decoded to {len(key_bytes)} bytes. "
                "Expected 64-byte secret key (what Phantom exports).\n\n"
                "In Phantom: Settings → Security & Privacy → Export Private Key"
            )
        full_secret = bytes(kp)
        return {
            "address":     str(kp.pubkey()),
            "private_key": base58.b58encode(full_secret).decode(),
            "mnemonic":    None,
            "type":        "solana",
        }
    except Exception as e:
        raise ValueError(
            f"Could not parse Solana key: {e}\n\n"
            "Supported formats:\n"
            "• Base58 private key (from Phantom → Export Private Key)\n"
            "• 12 or 24 word seed phrase\n"
            "• Byte array [1,2,3,...]\n"
            "• Hex string"
        )

# ── Universal import dispatcher ───────────────────────────────────────────────

def import_wallet(key_input: str, chain_type: str) -> dict:
    """
    Smart import — detects format automatically.
    chain_type: 'evm' or 'solana'
    """
    key_input = key_input.strip()

    if chain_type == "solana":
        return solana_from_private_key(key_input)

    # EVM — check if it's a mnemonic
    word_count = len(key_input.split())
    if word_count in (12, 24):
        return evm_from_mnemonic(key_input)
    return evm_from_private_key(key_input)

# ── Signer helpers (used by swap engine) ─────────────────────────────────────

def get_evm_signer(enc_key: str):
    pk = decrypt(enc_key)
    return Account.from_key(pk)

def get_solana_keypair(enc_key: str):
    import base58
    from solders.keypair import Keypair      # type: ignore
    pk_b58 = decrypt(enc_key)
    key_bytes = base58.b58decode(pk_b58)
    if len(key_bytes) == 64:
        return Keypair.from_bytes(key_bytes)
    return Keypair.from_seed(key_bytes)

def short_addr(address: str) -> str:
    if len(address) <= 12:
        return address
    return f"{address[:6]}...{address[-4:]}"

# utils/encryption.py  —  AES-256-GCM wallet key encryption

import os
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from utils.database import get_enc_key, set_enc_key

def _get_or_create_key() -> bytes:
    """Load encryption key from DB, or generate and store a new one."""
    stored = get_enc_key()
    if stored:
        return bytes.fromhex(stored)
    new_key = secrets.token_bytes(32)
    set_enc_key(new_key.hex())
    return new_key

def encrypt(plaintext: str) -> str:
    """Encrypt a private key string. Returns hex-encoded nonce+ciphertext."""
    key = _get_or_create_key()
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return (nonce + ct).hex()

def decrypt(enc_hex: str) -> str:
    """Decrypt an encrypted private key hex string."""
    key = _get_or_create_key()
    aesgcm = AESGCM(key)
    data = bytes.fromhex(enc_hex)
    nonce, ct = data[:12], data[12:]
    return aesgcm.decrypt(nonce, ct, None).decode()

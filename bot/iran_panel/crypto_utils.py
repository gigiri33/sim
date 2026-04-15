# -*- coding: utf-8 -*-
"""
Encryption / hashing helpers for Iran Panel management.

Sensitive fields stored in DB:
  - panel passwords         → Fernet-encrypted with key derived from BOT_TOKEN
  - registration tokens     → stored as plain text (short-lived, one-time)
  - agent session secrets   → SHA-256(salt:secret) stored in DB

No secret is ever logged.
"""
import base64
import hashlib
import secrets
import uuid as _uuid_mod

try:
    from cryptography.fernet import Fernet, InvalidToken as _InvalidToken
    _FERNET_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FERNET_AVAILABLE = False


# ── Key derivation ─────────────────────────────────────────────────────────────

def _derive_fernet_key(bot_token: str) -> bytes:
    """Derive a stable 32-byte Fernet key from the bot token."""
    raw = hashlib.sha256(("seamless-iran:" + bot_token).encode()).digest()
    return base64.urlsafe_b64encode(raw)  # Fernet needs url-safe base64


# ── Encryption ─────────────────────────────────────────────────────────────────

def encrypt_secret(plaintext: str, bot_token: str) -> str:
    """
    Encrypt a secret string with Fernet.
    Falls back to simple base64 obfuscation if cryptography package is absent
    (not recommended for production – install cryptography>=41.0).
    Returns a string safe to store in TEXT columns.
    """
    if not plaintext:
        return ""
    if _FERNET_AVAILABLE:
        key = _derive_fernet_key(bot_token)
        f   = Fernet(key)
        return "fernet:" + f.encrypt(plaintext.encode()).decode()
    # Fallback – base64 only (obfuscation, not security)
    return "b64:" + base64.urlsafe_b64encode(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str, bot_token: str) -> str:
    """Decrypt a value produced by encrypt_secret. Raises ValueError on failure."""
    if not ciphertext:
        return ""
    if ciphertext.startswith("b64:"):
        return base64.urlsafe_b64decode(ciphertext[4:]).decode()
    if ciphertext.startswith("fernet:"):
        if not _FERNET_AVAILABLE:
            raise ValueError(
                "cryptography package is required to decrypt this value. "
                "Run: pip install cryptography"
            )
        key = _derive_fernet_key(bot_token)
        f   = Fernet(key)
        try:
            return f.decrypt(ciphertext[7:].encode()).decode()
        except _InvalidToken:
            raise ValueError(
                "Decryption failed — invalid key or corrupted ciphertext. "
                "If BOT_TOKEN changed, passwords must be re-entered."
            )
    # Legacy: plain text stored without prefix (migrate on next save)
    return ciphertext


# ── Hashing ────────────────────────────────────────────────────────────────────

def generate_salt() -> str:
    """Generate a 16-byte hex salt."""
    return secrets.token_hex(16)


def hash_with_salt(value: str, salt: str) -> str:
    """SHA-256(salt:value). Returns hex digest."""
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def verify_hash(value: str, salt: str, stored_hash: str) -> bool:
    """Constant-time comparison against stored hash."""
    return secrets.compare_digest(
        hash_with_salt(value, salt),
        stored_hash,
    )


# ── Token generation ───────────────────────────────────────────────────────────

def generate_reg_token() -> str:
    """Generate a secure 40-char hex one-time registration token."""
    return secrets.token_hex(20)  # 40 hex chars


def generate_agent_secret() -> str:
    """Generate a 64-char hex persistent agent session secret."""
    return secrets.token_hex(32)


def generate_uuid() -> str:
    """Generate a random UUID string."""
    return str(_uuid_mod.uuid4())

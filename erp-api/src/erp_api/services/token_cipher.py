from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class TokenCipher:
    """Encrypts connector tokens with AES-256-GCM."""

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("Encryption keys must be at least 32 characters.")
        self._key = hashlib.sha256(secret.encode()).digest()

    def encrypt(self, plaintext: str) -> str:
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, plaintext.encode(), None)
        return ".".join(self._encode(value) for value in (nonce, ciphertext))

    def decrypt(self, envelope: str) -> str:
        try:
            nonce, ciphertext = (self._decode(value) for value in envelope.split("."))
        except (ValueError, TypeError):
            raise ValueError("Invalid encrypted token envelope.") from None
        try:
            return AESGCM(self._key).decrypt(nonce, ciphertext, None).decode()
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Invalid encrypted token envelope.")

    def fingerprint(self, namespace: str, value: str) -> str:
        normalized = value.strip().upper().encode()
        return hmac.new(
            self._key, f"{namespace}:".encode() + normalized, hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    @staticmethod
    def _decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

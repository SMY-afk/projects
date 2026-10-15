from erp_api.services.order_sync_repository import _mask, _mask_address, _mask_name
from erp_api.services.token_cipher import TokenCipher


def test_order_pii_uses_reversible_ciphertext_and_safe_masked_values() -> None:
    cipher = TokenCipher("test-only-order-pii-encryption-key-32-chars")
    encrypted = cipher.encrypt("1234567890")

    assert "1234567890" not in encrypted
    assert cipher.decrypt(encrypted) == "1234567890"
    assert cipher.fingerprint("tracking", " ab-123 ") == cipher.fingerprint(
        "tracking", "AB-123"
    )
    assert _mask("1234567890", 4) == "******7890"
    assert _mask_name("Buyer") == "B***"
    assert (
        _mask_address({"region_code": "US", "city": "Seattle", "line1": "Secret"})
        == "US Seattle ***"
    )

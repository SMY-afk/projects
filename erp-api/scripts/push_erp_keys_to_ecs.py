"""Transfer existing local ERP encryption keys to the ECS environment safely."""

import json
import subprocess

from erp_api.core.config import get_settings


def main() -> None:
    settings = get_settings()
    keys = {
        "TIKTOK_APP_KEY": settings.tiktok_app_key,
        "TIKTOK_SERVICE_ID": settings.tiktok_service_id,
        "TIKTOK_APP_SECRET": settings.tiktok_app_secret,
        "TIKTOK_301_APP_KEY": settings.tiktok_301_app_key,
        "TIKTOK_301_SERVICE_ID": settings.tiktok_301_service_id,
        "TIKTOK_301_APP_SECRET": settings.tiktok_301_app_secret,
        "TIKTOK_AUTHORIZATION_URL": settings.tiktok_authorization_url,
        "TIKTOK_TOKEN_URL": settings.tiktok_token_url,
        "TIKTOK_SHOP_IDENTITY_URL": settings.tiktok_shop_identity_url,
        "TIKTOK_CALLBACK_BASE_URL": "https://example.invalid/configure-resource",
        "TIKTOK_WEBHOOK_SIGNING_SECRET": settings.tiktok_webhook_signing_secret,
        "ORDER_PII_ENCRYPTION_KEY": settings.order_pii_encryption_key,
        "TIKTOK_TOKEN_ENCRYPTION_KEY": settings.tiktok_token_encryption_key,
    }
    if any(value is None for value in keys.values()):
        raise SystemExit("STOP_LOCAL_KEY_MISSING")
    payload = {
        key: value.get_secret_value() if hasattr(value, "get_secret_value") else value
        for key, value in keys.items()
    }
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "erp-ecs", "/usr/bin/python3", "/opt/erp/imports/20261007-preflight/ecs_update_erp_keys.py"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=20,
    )
    if result.returncode:
        raise SystemExit(f"STOP_ECS_KEY_UPDATE EXIT={result.returncode} ERROR={result.stderr[-300:]}")
    print(result.stdout.strip())


if __name__ == "__main__":
    main()

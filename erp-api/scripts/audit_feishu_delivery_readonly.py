"""Read back recent RDS notification message IDs using the active Feishu app."""

import asyncio
import hashlib
import json
import ssl
from pathlib import Path

import asyncpg
import httpx
from dotenv import dotenv_values

from scripts.check_rds_public_readonly import PUBLIC_HOST, load_rds_identity


async def main() -> None:
    user, password = load_rds_identity()
    context = ssl.create_default_context(cafile=str(Path("var/certs/ApsaraDB-CA-Chain.pem")))
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    db = await asyncpg.connect(
        host=PUBLIC_HOST, port=5432, user=user, password=password,
        database="wj_erp", ssl=context,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        rows = await db.fetch(
            "SELECT payload, sent_at FROM public.sample_notification_outbox "
            "WHERE status='sent' AND payload ? 'message_id' "
            "AND payload ? 'group_message_id' "
            "ORDER BY sent_at DESC LIMIT 3"
        )
    finally:
        await db.close()
    if not rows:
        raise SystemExit("NO_RECENT_DELIVERY_EVIDENCE")
    config = dotenv_values(".env")
    async with httpx.AsyncClient(base_url="https://example.invalid/configure-resource", timeout=20) as client:
        token_response = await client.post(
            "/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": config["FEISHU_APP_ID"], "app_secret": config["FEISHU_APP_SECRET"]},
        )
        token = token_response.json().get("tenant_access_token")
        if token_response.status_code != 200 or not isinstance(token, str):
            raise SystemExit("FEISHU_AUTH_FAILED")
        client.headers["Authorization"] = f"Bearer {token}"
        for row in rows:
            payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            for kind, key in (("DIRECT", "message_id"), ("GROUP", "group_message_id")):
                message_id = payload.get(key)
                if not isinstance(message_id, str) or not message_id:
                    raise SystemExit(f"MISSING_{kind}_MESSAGE_ID")
                response = await client.get(f"/open-apis/im/v1/messages/{message_id}")
                code = response.json().get("code") if response.status_code == 200 else None
                if response.status_code != 200 or code != 0:
                    raise SystemExit(f"MESSAGE_READ_FAILED KIND={kind} HTTP={response.status_code} CODE={code}")
                digest = hashlib.sha256(message_id.encode()).hexdigest()[:12]
                print(f"MESSAGE_READ_OK KIND={kind} ID_SHA12={digest} SENT_AT={row['sent_at']}")
    print("DELIVERY_EVIDENCE_READ_ONLY_OK")


if __name__ == "__main__":
    asyncio.run(main())

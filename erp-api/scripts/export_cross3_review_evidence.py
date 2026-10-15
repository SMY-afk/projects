"""Export credential-free current review deadlines from one persisted RAW batch."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from erp_api.services.hubstudio_sample_response_parser import parse_hubstudio_sample_response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.batch / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "processed" or not manifest["terminal_confirmed"]:
        raise RuntimeError("Review evidence requires a complete acknowledged batch.")
    records = {}
    for page_path in sorted(args.batch.glob("page-*.json")):
        page = json.loads(page_path.read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(page["response_observed_at"])
        parsed = parse_hubstudio_sample_response(
            page["payload"], platform_request_id=page["request_id"], observed_at=observed
        )
        for application in parsed.applications:
            records[application["id"]] = {
                "id": application["id"],
                "creator": application["creator"]["username"],
                "status": application["status"],
                "deadline": application.get("approve_expiration_time"),
                "source_item_ids": application.get("source_item_ids", []),
                "observed_at": observed.isoformat(),
            }
    print(json.dumps({"manifest": manifest, "records": list(records.values())}, ensure_ascii=True))


if __name__ == "__main__":
    main()

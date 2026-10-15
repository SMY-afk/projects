"""Keep complete, identity-bound profile progress across bounded paid windows."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / ".runtime/refundable-profile-cache"


class RefundableProfileCache:
    def __init__(self, *, root=ROOT):
        self.root = root

    def _path(self, shop, creator):
        key = hashlib.sha256(f"{shop}:{creator}".encode()).hexdigest()
        return self.root / f"{key}.json"

    def select_due(self, shop, items, *, limit=3, now=None):
        """Rotate expensive detail reads; never let a large scope starve later rows."""
        now = now or datetime.now(UTC)
        due = {}
        for item in items:
            creator = item["creator"]
            key = str(creator["creator_open_id"])
            if not item.get("product", {}).get("sku_image_url"):
                continue
            if self.load(shop, key, creator["username"], now=now) is not None:
                continue
            path = self._path(shop, key).with_suffix(".attempt.json")
            try:
                attempted = datetime.fromisoformat(json.loads(path.read_text())["at"])
            except (OSError, KeyError, ValueError, TypeError):
                attempted = datetime.min.replace(tzinfo=UTC)
            if (now - attempted).total_seconds() >= 600:
                due[key] = attempted
        return {key for key, _ in sorted(due.items(), key=lambda row: row[1])[:limit]}

    def mark_attempt(self, shop, creator):
        path = self._path(shop, creator).with_suffix(".attempt.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps({"at": datetime.now(UTC).isoformat()}))
        os.replace(temporary, path)

    @staticmethod
    def _validated(rows, creator, now):
        if not isinstance(rows, list):
            return None
        kinds = {}
        for row in rows:
            try:
                request = row["request"]
                profile_types = request["profile_types"]
                at = datetime.fromisoformat(row["observed_at"])
                age = (now - at).total_seconds()
                if (
                    str(request["creator_oec_id"]) != creator
                    or not isinstance(profile_types, list)
                    or len(profile_types) != 1
                    or type(profile_types[0]) is not int
                    or profile_types[0] not in range(1, 6)
                    or type(row["payload"].get("code")) is not int
                    or row["payload"].get("code") != 0
                    or not -5 <= age <= 900
                ):
                    return None
                kinds[profile_types[0]] = row
            except (KeyError, TypeError, ValueError, AttributeError):
                return None
        return (
            [kinds[k] for k in range(1, 6)] if set(kinds) == set(range(1, 6)) else None
        )

    def load(self, shop, creator, username, *, now=None):
        try:
            row = json.loads(self._path(shop, creator).read_text(encoding="utf-8"))
            if (
                row["shop"] != shop
                or row["creator"] != creator
                or row["username"] != username.casefold()
            ):
                return None
            if (
                row["profiles_sha256"]
                != hashlib.sha256(
                    json.dumps(row["profiles"], sort_keys=True).encode()
                ).hexdigest()
            ):
                return None
            return self._validated(row["profiles"], creator, now or datetime.now(UTC))
        except (OSError, KeyError, TypeError, ValueError):
            return None

    def save(self, shop, creator, username, rows, *, now=None):
        rows = self._validated(rows, creator, now or datetime.now(UTC))
        if rows is None:
            return False
        path = self._path(shop, creator)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "shop": shop,
                    "creator": creator,
                    "username": username.casefold(),
                    "profiles": rows,
                    "profiles_sha256": hashlib.sha256(
                        json.dumps(rows, sort_keys=True).encode()
                    ).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return True

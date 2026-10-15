"""Complete immutable cleanup evidence, persisted privately before deletion."""

import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scripts.daily_valid_creator_cleanup_plan import cleanup_preview
from scripts.daily_valid_creator_core import account_key, date_value
from scripts.daily_valid_creator_io import BASE, FIELD_TYPES, TABLE

SNAPSHOT_FORMAT = "daily-valid-creator-one-off-cleanup-v1"
EXPECTED_IDENTITY = {"app_token": BASE, "base_name": "样品--副本", "table_id": TABLE,
                     "table_name": "（每日更新）有效达人"}


def exclusive_json(directory, prefix, data):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = root / f"{prefix}-{stamp}-{uuid4().hex}.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name != "nt":
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    actual = path.read_bytes()
    if actual != payload.encode("utf-8") or json.loads(actual) != json.loads(payload):
        raise RuntimeError("Cleanup evidence backup readback mismatch")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RuntimeError("Cleanup evidence file permissions are unsafe")
    return {"path": path, "sha256": hashlib.sha256(actual).hexdigest()}


def _validate_scope(data):
    if data.get("format") != SNAPSHOT_FORMAT or data.get("identity") != EXPECTED_IDENTITY:
        raise ValueError("Cleanup snapshot identity or format differs from authorized scope")
    schema = data.get("schema")
    if not isinstance(schema, list) or len(schema) != len(FIELD_TYPES):
        raise ValueError("Cleanup snapshot field schema is incomplete")
    if {field.get("field_name"): field.get("type") for field in schema} != FIELD_TYPES:
        raise ValueError("Cleanup snapshot field schema differs from target")
    ids = [field.get("field_id") for field in schema]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Cleanup snapshot field metadata IDs are invalid")
    if not isinstance(data.get("source_evidence"), dict) or not data["source_evidence"]:
        raise ValueError("Cleanup snapshot source evidence is absent")
    _reject_auth_material(data["source_evidence"])


def _reject_auth_material(value):
    forbidden = {"authorization", "tenant_access_token", "user_access_token", "access_token",
                 "app_secret", "client_secret", "secret", "sign", "shop_cipher",
                 "x-erp-service-token", "x-erp-capture-token"}
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold().replace("_", "-") in {name.replace("_", "-") for name in forbidden}:
                raise ValueError("Authentication material is forbidden in cleanup source evidence")
            _reject_auth_material(item)
    elif isinstance(value, list):
        for item in value:
            _reject_auth_material(item)


def snapshot_projection(data):
    desired, base = {}, {}
    for field_name, target in (("desired", desired), ("base", base)):
        rows = data.get(field_name)
        if not isinstance(rows, list):
            raise TypeError("Cleanup snapshot projection proof is incomplete")
        for item in rows:
            key = tuple(item.get("key") or ())
            if len(key) != 2 or key in target:
                raise ValueError("Cleanup snapshot source identity is invalid or duplicated")
            target[key] = dict(item.get("fields") if field_name == "desired" else item.get("source"))
            if field_name == "base":
                raw_date = target[key].get("sample_day")
                target[key]["sample_day"] = date_value(raw_date)
                if raw_date and target[key]["sample_day"] is None:
                    raise ValueError("Cleanup snapshot source approval date is invalid")
    return desired, base


def _validate_projection(data, excluded):
    _validate_scope(data)
    if data.get("excluded_accounts") != sorted(excluded):
        raise ValueError("Cleanup snapshot protected account scope changed")
    desired, base = snapshot_projection(data)
    expected = cleanup_preview(data["current"], desired, base, excluded_accounts=excluded)
    if data.get("plan") != expected:
        raise ValueError("Cleanup snapshot plan differs from revalidated pure source projection")


def save_cleanup_snapshot(directory, *, identity, schema, current, plan, source_evidence,
                          desired, base, excluded_accounts=("yana_ok1",)):
    excluded = {account_key(value) for value in excluded_accounts} | {"yana_ok1"}
    data = {"format": SNAPSHOT_FORMAT, "created_at": datetime.now(UTC).isoformat(),
            "identity": identity, "schema": schema, "current": current, "plan": plan,
            "source_evidence": source_evidence, "excluded_accounts": sorted(excluded),
            "desired": [{"key": list(key), "fields": fields} for key, fields in sorted(desired.items())],
            "base": [{"key": list(key), "source": source} for key, source in sorted(base.items())]}
    normalized = json.loads(json.dumps(data, ensure_ascii=False, default=str))
    _validate_projection(normalized, excluded)
    receipt = exclusive_json(directory, "daily-creator-cleanup-snapshot", normalized)
    receipt["records"] = len(current)
    return receipt


def load_cleanup_snapshot(receipt, excluded_accounts=("yana_ok1",)):
    path = Path(receipt["path"])
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != receipt.get("sha256"):
        raise ValueError("Cleanup snapshot hash mismatch")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError("Cleanup snapshot permissions are unsafe")
    data = json.loads(payload)
    excluded = {account_key(value) for value in excluded_accounts} | {"yana_ok1"}
    _validate_projection(data, excluded)
    return data

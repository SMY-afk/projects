"""Durable single-capture outbox; restart never silently replays unknown writes."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def payload_hash(manifest, capture):
    return hashlib.sha256(json.dumps(
        {"manifest": manifest, "capture": capture}, sort_keys=True,
        ensure_ascii=False, separators=(",", ":"),
    ).encode()).hexdigest()


class MetadataCaptureState:
    def __init__(self, root):
        self.root = Path(root)
        self.alias = self.root / "pending.json"

    def _write(self, path, row):
        self.root.mkdir(parents=True, exist_ok=True)
        content = json.dumps(row, ensure_ascii=False, sort_keys=True).encode()
        temporary = self.root / f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.read_bytes() != content:
            raise RuntimeError("metadata_state_write_verification_failed")
        os.replace(temporary, path)

    def _load(self):
        if not self.alias.exists():
            return None
        try:
            attempt = json.loads(self.alias.read_text(encoding="utf-8"))["attempt_id"]
            if (not isinstance(attempt, str) or len(attempt) != 32
                    or any(c not in "0123456789abcdef" for c in attempt)):
                raise ValueError("Invalid attempt")
            row = json.loads((self.root / f"{attempt}.json").read_text(encoding="utf-8"))
            digest = payload_hash(row["manifest"], row["capture"])
            if (row["attempt_id"] != attempt or row["payload_hash"] != digest
                    or attempt != digest[:32] or row["phase"] not in {
                        "captured", "submitting", "completed", "audit_required", "superseded",
                    }):
                raise ValueError("Invalid state")
            return row
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise RuntimeError("metadata_state_invalid") from error

    def load_pending(self):
        row = self._load()
        return row if row and row["phase"] not in {"completed", "superseded"} else None

    def load_finalized(self):
        row = self._load()
        return row if row and row["phase"] in {"completed", "superseded"} else None

    def stage(self, manifest, capture, raw_batch_dir=None):
        digest = payload_hash(manifest, capture)
        existing = self._load()
        if existing and existing["phase"] not in {"completed", "superseded"}:
            if existing["payload_hash"] != digest:
                raise RuntimeError("metadata_pending_capture_must_not_be_overwritten")
            return existing
        row = {
            "attempt_id": digest[:32], "payload_hash": digest, "phase": "captured",
            "manifest": manifest, "capture": capture,
            "raw_batch_dir": str(raw_batch_dir) if raw_batch_dir else None,
        }
        target = self.root / f"{digest[:32]}.json"
        if target.exists():
            archived = json.loads(target.read_text(encoding="utf-8"))
            if archived["payload_hash"] != digest:
                raise RuntimeError("metadata_capture_identity_conflict")
            row = archived
        else:
            self._write(target, row)
        self._write(self.alias, {"attempt_id": row["attempt_id"]})
        return self._load()

    def _transition(self, attempt, phase, **fields):
        row = self._load()
        if row is None or row["attempt_id"] != attempt:
            raise RuntimeError("metadata_capture_identity_changed")
        if row["phase"] == "completed":
            raise RuntimeError("metadata_capture_already_completed")
        row.update(phase=phase, **fields)
        self._write(self.root / f"{attempt}.json", row)
        return self._load()

    def mark_submitting(self, attempt):
        row = self.load_pending()
        if row is None or row["phase"] not in {"captured", "submitting"}:
            raise RuntimeError("metadata_capture_requires_audit")
        return self._transition(attempt, "submitting")

    def mark_completed(self, attempt, receipt):
        if receipt.get("attempt_id") != attempt or receipt.get("status") != "completed":
            raise RuntimeError("metadata_receipt_identity_invalid")
        return self._transition(attempt, "completed", receipt=receipt)

    def mark_audit_required(self, attempt, reason):
        return self._transition(attempt, "audit_required", reason=reason)

    def mark_superseded(self, attempt, reason):
        row = self.load_pending()
        if row is None or row["phase"] != "captured":
            raise RuntimeError("metadata_uncertain_capture_cannot_be_superseded")
        return self._transition(attempt, "superseded", reason=reason)

    def mark_not_applied(self, attempt, receipt):
        row = self.load_pending()
        if (row is None or row["phase"] != "submitting"
                or receipt.get("no_metadata_write") is not True
                or receipt.get("attempt_id") != attempt
                or receipt.get("payload_hash") != row["payload_hash"]):
            raise RuntimeError("metadata_no_write_receipt_invalid")
        return self._transition(attempt, "captured", no_write_receipt=receipt)

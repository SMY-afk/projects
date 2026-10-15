"""Durable, exclusive pre-write snapshots for reversible creator reconciliation."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def save_snapshot(directory, baseline, plan):
    root = Path(directory)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    path = root / f"daily-creator-reconciliation-{stamp}-{uuid4().hex}.json"
    data = {"created_at": datetime.now(UTC).isoformat(), "baseline": baseline, "plan": plan}
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    if path.read_text(encoding="utf-8") != payload:
        raise RuntimeError("Creator reconciliation backup readback mismatch")
    return path

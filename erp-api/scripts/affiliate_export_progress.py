"""Store non-sensitive capture phase timing for one original workbook."""

import json
import os
from datetime import UTC, datetime


def mark_capture_phase(args, phase: str) -> None:
    path = getattr(args, "progress_file", None)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps({"phase": phase, "at": datetime.now(UTC).isoformat()}),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        pass  # Diagnostic timestamps must never interrupt an original export.

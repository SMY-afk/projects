"""Retain a rejected XLSX privately for schema inspection without DB writes."""

from pathlib import Path
from uuid import uuid4


def quarantine_workbook(directory: Path, content: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"quarantine-{uuid4()}.xlsx"
    with path.open("xb") as handle:
        handle.write(content)
    return path

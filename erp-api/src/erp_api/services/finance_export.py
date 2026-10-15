from __future__ import annotations

import csv
import io
from collections.abc import Iterable

_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_csv_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    candidate = value.lstrip(" ")
    return f"'{value}" if candidate.startswith(_DANGEROUS_PREFIXES) else value


def csv_row(values: Iterable[object]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([safe_csv_cell(value) for value in values])
    return buffer.getvalue()

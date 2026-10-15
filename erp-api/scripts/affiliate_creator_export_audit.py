"""Audit explicit missing-account exclusions in original creator XLSX files."""

from dataclasses import dataclass

from app.parsers.affiliate_creator_export_parser import (
    parse_affiliate_creator_export,
    read_first_worksheet,
)

_ACCOUNT_HEADERS = ("达人用户名", "Creator username", "Creator name")
_MISSING = {"", "-", "--", "n/a", "na", "null"}


@dataclass(frozen=True)
class CreatorExportAudit:
    source_total: int
    eligible_total: int
    excluded_missing_accounts: int


def audit_creator_export(
    content: bytes, currency: str, source_total: int, *, allow_missing: bool
) -> tuple[list[dict[str, object]], CreatorExportAudit]:
    sheet = read_first_worksheet(content)
    headers = [str(value or "").strip() for value in next(sheet)]
    matches = [headers.index(name) for name in _ACCOUNT_HEADERS if name in headers]
    if len(matches) != 1:
        raise ValueError("Creator XLSX account header is missing or ambiguous")
    account_index = matches[0]
    raw_rows = list(sheet)
    if len(raw_rows) != source_total:
        raise ValueError("Creator XLSX raw row count differs from live source total")
    missing = sum(
        str((row[account_index] if len(row) > account_index else "") or "")
        .strip()
        .casefold()
        in _MISSING
        for row in raw_rows
    )
    rows = parse_affiliate_creator_export(content, currency)
    unique = {str(row["username"]).strip().lstrip("@").casefold() for row in rows}
    if len(rows) + missing != source_total or len(unique) != len(rows):
        raise ValueError("Creator XLSX has unexplained skipped or duplicate accounts")
    if missing and not allow_missing:
        raise ValueError("Creator XLSX has missing account names")
    return rows, CreatorExportAudit(source_total, len(rows), missing)

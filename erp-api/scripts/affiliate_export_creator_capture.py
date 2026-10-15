"""Download and audit an original creator XLSX before remote ingestion."""

import hashlib
from pathlib import Path

from backend.app.services.tiktok_affiliate_creator_export_download import (
    _is_export_file_response,
    _is_export_response,
    delete_download,
    download_creator_export,
)
from backend.app.services.tiktok_affiliate_creator_identity_sample import (
    prepare_creator_identity_source,
)
from scripts.affiliate_creator_export_audit import (
    CreatorExportAudit,
    audit_creator_export,
)
from scripts.affiliate_export_quarantine import quarantine_workbook


async def capture_creator_export(
    page, trigger, currency: str, spool_dir: Path, *, allow_missing: bool,
    local_download_dir: Path | None = None, on_progress=None,
) -> tuple[bytes, str, CreatorExportAudit]:
    source = await prepare_creator_identity_source(page, trigger)
    if on_progress:
        on_progress("identity_verified")
    def observe(response):
        if on_progress and _is_export_response(response):
            on_progress("export_response_received")
        elif on_progress and _is_export_file_response(response):
            on_progress("file_response_received")

    if on_progress:
        page.on("response", observe)
    try:
        content, file_id, download, request_id = await download_creator_export(
            page, local_download_dir=local_download_dir
        )
    finally:
        if on_progress:
            page.remove_listener("response", observe)
    try:
        try:
            _rows, audit = audit_creator_export(
                content, currency, source.expected_total, allow_missing=allow_missing
            )
        except ValueError:
            quarantine_workbook(spool_dir, content)
            raise
    finally:
        await delete_download(download)
    resolved_request_id = request_id or (
        f"export:{hashlib.sha256(file_id.encode()).hexdigest()[:32]}"
    )
    return content, resolved_request_id, audit

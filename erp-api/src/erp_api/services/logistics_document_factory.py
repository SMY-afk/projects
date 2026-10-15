from erp_api.core.config import Settings
from erp_api.infrastructure.database import Database
from erp_api.services.logistics_document_repository import (
    LogisticsDocumentRepository,
)
from erp_api.services.logistics_document_service import LogisticsDocumentService
from erp_api.services.object_storage import S3ObjectStorage


def build_logistics_document_service(
    settings: Settings, database: Database
) -> LogisticsDocumentService | None:
    if not (
        settings.object_storage_access_key
        and settings.object_storage_secret_key
        and settings.object_storage_bucket
    ):
        return None
    storage = S3ObjectStorage(
        endpoint_url=settings.object_storage_endpoint_url,
        region=settings.object_storage_region,
        access_key=settings.object_storage_access_key.get_secret_value(),
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        bucket=settings.object_storage_bucket,
        force_path_style=settings.object_storage_force_path_style,
        key_prefix=settings.object_storage_key_prefix,
    )
    return LogisticsDocumentService(
        LogisticsDocumentRepository(database),
        storage,
        max_bytes=settings.logistics_document_max_bytes,
        presigned_ttl_seconds=settings.object_storage_presigned_ttl_seconds,
    )

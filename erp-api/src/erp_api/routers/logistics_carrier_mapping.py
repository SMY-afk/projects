from uuid import UUID

from fastapi import APIRouter, Depends, status

from erp_api.core.permissions import LOGISTICS_MANAGE, LOGISTICS_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.logistics_carrier_schemas import (
    PlatformCarrierMappingCreateRequest,
    PlatformCarrierMappingResponse,
    PlatformCarrierMappingUpdateRequest,
)
from erp_api.routers.logistics_shipping import (
    _carrier_repository,
    _raise_domain_error,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_carrier_repository import LogisticsCarrierRepository
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingNotFoundError,
    LogisticsShippingValidationError,
)

router = APIRouter()


@router.post(
    "/carriers/{carrier_id}/platform-mappings",
    response_model=PlatformCarrierMappingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_platform_carrier_mapping(
    carrier_id: UUID,
    payload: PlatformCarrierMappingCreateRequest,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_MANAGE)),
    repository: LogisticsCarrierRepository = Depends(_carrier_repository),
) -> PlatformCarrierMappingResponse:
    try:
        record = await repository.create_platform_mapping(
            session.tenant_id,
            carrier_id,
            store_id=payload.storeId,
            platform=payload.platform,
            region=payload.region,
            service_id=payload.serviceId,
            platform_carrier_id=payload.platformCarrierId,
            platform_carrier_code=payload.platformCarrierCode,
            platform_carrier_name=payload.platformCarrierName,
            delivery_option_id=payload.deliveryOptionId,
            raw_payload=payload.rawPayload,
        )
    except (
        LogisticsShippingNotFoundError,
        LogisticsShippingConflictError,
        LogisticsShippingValidationError,
    ) as error:
        _raise_domain_error(error)
    return PlatformCarrierMappingResponse.model_validate(record)


@router.patch(
    "/platform-carrier-mappings/{mapping_id}",
    response_model=PlatformCarrierMappingResponse,
)
async def update_platform_carrier_mapping(
    mapping_id: UUID,
    payload: PlatformCarrierMappingUpdateRequest,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_MANAGE)),
    repository: LogisticsCarrierRepository = Depends(_carrier_repository),
) -> PlatformCarrierMappingResponse:
    try:
        record = await repository.update_platform_mapping(
            session.tenant_id,
            mapping_id,
            version_id=payload.versionId,
            status=payload.status,
            platform_carrier_id=payload.platformCarrierId,
            platform_carrier_code=payload.platformCarrierCode,
            platform_carrier_name=payload.platformCarrierName,
            delivery_option_id=payload.deliveryOptionId,
            raw_payload=payload.rawPayload,
        )
    except (
        LogisticsShippingNotFoundError,
        LogisticsShippingConflictError,
    ) as error:
        _raise_domain_error(error)
    return PlatformCarrierMappingResponse.model_validate(record)

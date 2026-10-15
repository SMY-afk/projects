from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from erp_api.core.permissions import (
    LOGISTICS_DISPATCH,
    LOGISTICS_MANAGE,
    LOGISTICS_VIEW,
)
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.logistics_shipping_schemas import (
    CarrierAccountCreateRequest,
    CarrierAccountResponse,
    CarrierCreateRequest,
    CarrierResponse,
    CarrierServiceCreateRequest,
    CarrierServiceResponse,
    ShippingQuoteRequest,
    ShippingQuoteResponse,
    WaybillCancelRequest,
    WaybillCreateRequest,
    WaybillResponse,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_carrier_repository import LogisticsCarrierRepository
from erp_api.services.logistics_package_repository import LogisticsPackageRepository
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingNotFoundError,
    LogisticsShippingValidationError,
)
from erp_api.services.logistics_shipping_service import LogisticsShippingService

router = APIRouter()


def _shipping_repository(request: Request) -> LogisticsPackageRepository:
    repository = getattr(request.app.state, "logistics_package_repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _carrier_repository(request: Request) -> LogisticsCarrierRepository:
    repository = getattr(request.app.state, "logistics_carrier_repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _shipping_service(request: Request) -> LogisticsShippingService:
    service = getattr(request.app.state, "logistics_shipping_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


def _raise_domain_error(error: ValueError) -> None:
    if isinstance(error, LogisticsShippingNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(error, LogisticsShippingConflictError):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    raise HTTPException(status_code=code, detail=str(error)) from error


@router.get("/carriers", response_model=list[CarrierResponse])
async def list_carriers(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    repository: LogisticsCarrierRepository = Depends(_carrier_repository),
) -> list[CarrierResponse]:
    records = await repository.list_carriers(session.tenant_id)
    return [CarrierResponse.model_validate(item) for item in records]


@router.post(
    "/carriers",
    response_model=CarrierResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_carrier(
    payload: CarrierCreateRequest,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_MANAGE)),
    repository: LogisticsCarrierRepository = Depends(_carrier_repository),
) -> CarrierResponse:
    try:
        record = await repository.create_carrier(
            session.tenant_id,
            code=payload.code,
            name=payload.name,
            adapter_key=payload.adapterKey,
            tracking_url_template=payload.trackingUrlTemplate,
        )
    except LogisticsShippingConflictError as error:
        _raise_domain_error(error)
    return CarrierResponse.model_validate(record)


@router.post(
    "/carriers/{carrier_id}/services",
    response_model=CarrierServiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_carrier_service(
    carrier_id: UUID,
    payload: CarrierServiceCreateRequest,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_MANAGE)),
    repository: LogisticsCarrierRepository = Depends(_carrier_repository),
) -> CarrierServiceResponse:
    try:
        record = await repository.create_service(
            session.tenant_id,
            carrier_id,
            code=payload.code,
            name=payload.name,
            service_level=payload.serviceLevel,
            supported_countries=payload.supportedCountries,
            manual_pricing=(
                {
                    "base_fee_minor": payload.manualPricing.baseFeeMinor,
                    "per_kg_fee_minor": payload.manualPricing.perKgFeeMinor,
                    "currency": payload.manualPricing.currency.upper(),
                    "estimated_days_min": payload.manualPricing.estimatedDaysMin,
                    "estimated_days_max": payload.manualPricing.estimatedDaysMax,
                }
                if payload.manualPricing
                else None
            ),
            platform_provider_ids=payload.platformProviderIds,
            tracking_status_map=payload.trackingStatusMap,
        )
    except (LogisticsShippingNotFoundError, LogisticsShippingConflictError) as error:
        _raise_domain_error(error)
    return CarrierServiceResponse.model_validate(record)


@router.post(
    "/carriers/{carrier_id}/accounts",
    response_model=CarrierAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_carrier_account(
    carrier_id: UUID,
    payload: CarrierAccountCreateRequest,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_MANAGE)),
    repository: LogisticsCarrierRepository = Depends(_carrier_repository),
) -> CarrierAccountResponse:
    try:
        record = await repository.create_account(
            session.tenant_id,
            carrier_id,
            account_name=payload.accountName,
            account_identifier_masked=payload.accountIdentifierMasked,
            auth_type=payload.authType,
            secret_reference=payload.secretReference,
        )
    except (LogisticsShippingNotFoundError, LogisticsShippingConflictError) as error:
        _raise_domain_error(error)
    return CarrierAccountResponse.model_validate(record)


@router.get("/packages/{package_id}/waybills", response_model=list[WaybillResponse])
async def list_waybills(
    package_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    repository: LogisticsPackageRepository = Depends(_shipping_repository),
) -> list[WaybillResponse]:
    records = await repository.list_waybills(session.tenant_id, package_id)
    return [WaybillResponse.model_validate(item) for item in records]


@router.post(
    "/packages/{package_id}/shipping-quotes",
    response_model=list[ShippingQuoteResponse],
)
async def quote_package_shipping(
    package_id: UUID,
    payload: ShippingQuoteRequest,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_DISPATCH)),
    service: LogisticsShippingService = Depends(_shipping_service),
) -> list[ShippingQuoteResponse]:
    try:
        records = await service.quote(
            session.tenant_id,
            package_id,
            carrier_id=payload.carrierId,
            service_id=payload.serviceId,
            account_id=payload.accountId,
        )
    except (
        LogisticsShippingNotFoundError,
        LogisticsShippingConflictError,
        LogisticsShippingValidationError,
    ) as error:
        _raise_domain_error(error)
    return [ShippingQuoteResponse.model_validate(item) for item in records]


@router.post(
    "/packages/{package_id}/waybills",
    response_model=WaybillResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_waybill(
    package_id: UUID,
    payload: WaybillCreateRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(
        require_permissions(LOGISTICS_VIEW, LOGISTICS_DISPATCH)
    ),
    service: LogisticsShippingService = Depends(_shipping_service),
) -> WaybillResponse:
    try:
        record = await service.create_waybill(
            session.tenant_id,
            package_id,
            actor_user_id=user.id,
            carrier_id=payload.carrierId,
            service_id=payload.serviceId,
            account_id=payload.accountId,
            tracking_number=payload.trackingNumber,
            external_waybill_id=payload.externalWaybillId,
            label_url=None,
        )
    except (
        LogisticsShippingNotFoundError,
        LogisticsShippingConflictError,
        LogisticsShippingValidationError,
    ) as error:
        _raise_domain_error(error)
    return WaybillResponse.model_validate(record)


@router.post(
    "/waybills/{waybill_id}/cancel",
    response_model=WaybillResponse,
)
async def cancel_waybill(
    waybill_id: UUID,
    payload: WaybillCancelRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(
        require_permissions(LOGISTICS_VIEW, LOGISTICS_DISPATCH)
    ),
    service: LogisticsShippingService = Depends(_shipping_service),
) -> WaybillResponse:
    try:
        record = await service.cancel_waybill(
            session.tenant_id,
            waybill_id,
            actor_user_id=user.id,
            version_id=payload.versionId,
            reason=payload.reason,
        )
    except (
        LogisticsShippingNotFoundError,
        LogisticsShippingConflictError,
        LogisticsShippingValidationError,
    ) as error:
        _raise_domain_error(error)
    return WaybillResponse.model_validate(record)

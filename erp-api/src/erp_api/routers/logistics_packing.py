from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from erp_api.core.permissions import LOGISTICS_OPERATE, LOGISTICS_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.logistics_shipping_schemas import (
    PackageDraftCreateRequest,
    PackageDraftUpdateRequest,
    PackageResponse,
    PackageVersionRequest,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_package_repository import LogisticsPackageRepository
from erp_api.services.logistics_packing_repository import (
    LogisticsPackingRepository,
    PackageItemInput,
)
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingValidationError,
)

router = APIRouter()


def _package_repository(request: Request) -> LogisticsPackageRepository:
    repository = getattr(request.app.state, "logistics_package_repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _packing_repository(request: Request) -> LogisticsPackingRepository:
    repository = getattr(request.app.state, "logistics_packing_repository", None)
    if repository is not None:
        return repository
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return LogisticsPackingRepository(database)


def _raise_domain_error(error: ValueError) -> None:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(error, LogisticsShippingConflictError)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    raise HTTPException(status_code=code, detail=str(error)) from error


@router.get("/tasks/{task_id}/packages", response_model=list[PackageResponse])
async def list_packages(
    task_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    repository: LogisticsPackageRepository = Depends(_package_repository),
) -> list[PackageResponse]:
    records = await repository.list_packages(session.tenant_id, task_id)
    return [PackageResponse.model_validate(item) for item in records]


@router.post(
    "/tasks/{task_id}/packages",
    response_model=PackageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_package_draft(
    task_id: UUID,
    payload: PackageDraftCreateRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    repository: LogisticsPackingRepository = Depends(_packing_repository),
) -> PackageResponse:
    try:
        record = await repository.create_draft(
            session.tenant_id,
            task_id,
            actor_user_id=user.id,
            note=payload.note,
        )
    except (LogisticsShippingConflictError, LogisticsShippingValidationError) as error:
        _raise_domain_error(error)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return PackageResponse.model_validate(record)


@router.patch("/packages/{package_id}", response_model=PackageResponse)
async def update_package_draft(
    package_id: UUID,
    payload: PackageDraftUpdateRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    repository: LogisticsPackingRepository = Depends(_packing_repository),
) -> PackageResponse:
    try:
        record = await repository.update_draft(
            session.tenant_id,
            package_id,
            actor_user_id=user.id,
            version_id=payload.versionId,
            items=[
                PackageItemInput(item.taskItemId, item.quantity)
                for item in payload.items
            ],
            weight_grams=payload.weightGrams,
            length_mm=payload.lengthMm,
            width_mm=payload.widthMm,
            height_mm=payload.heightMm,
            note=payload.note,
        )
    except (LogisticsShippingConflictError, LogisticsShippingValidationError) as error:
        _raise_domain_error(error)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return PackageResponse.model_validate(record)


async def _change_sealing(
    package_id: UUID,
    payload: PackageVersionRequest,
    session: AuthSession,
    user: CurrentUser,
    repository: LogisticsPackingRepository,
    *,
    sealed: bool,
) -> PackageResponse:
    try:
        action = repository.seal if sealed else repository.unseal
        record = await action(
            session.tenant_id,
            package_id,
            actor_user_id=user.id,
            version_id=payload.versionId,
        )
    except (LogisticsShippingConflictError, LogisticsShippingValidationError) as error:
        _raise_domain_error(error)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return PackageResponse.model_validate(record)


@router.post("/packages/{package_id}/seal", response_model=PackageResponse)
async def seal_package(
    package_id: UUID,
    payload: PackageVersionRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    repository: LogisticsPackingRepository = Depends(_packing_repository),
) -> PackageResponse:
    return await _change_sealing(
        package_id, payload, session, user, repository, sealed=True
    )


@router.post("/packages/{package_id}/unseal", response_model=PackageResponse)
async def unseal_package(
    package_id: UUID,
    payload: PackageVersionRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    repository: LogisticsPackingRepository = Depends(_packing_repository),
) -> PackageResponse:
    return await _change_sealing(
        package_id, payload, session, user, repository, sealed=False
    )

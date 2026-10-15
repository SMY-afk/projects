from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from erp_api.models.logistics_carrier import LogisticsCarrier
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_operation import LogisticsTaskOperation
from erp_api.models.order_recipient import OrderRecipient
from erp_api.services.carrier_adapter import (
    AccountInput,
    CarrierInput,
    ParcelInput,
    ServiceInput,
)
from erp_api.services.logistics_shipping_context import ShippingContext
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingNotFoundError,
)


def carrier_select():
    return select(LogisticsCarrier).options(
        selectinload(LogisticsCarrier.services),
        selectinload(LogisticsCarrier.accounts),
    )


def build_contexts(package, destination, carriers, *, service_id, account_id):
    contexts: list[ShippingContext] = []
    for carrier in carriers:
        account = next(
            (item for item in carrier.accounts if item.id == account_id), None
        )
        if account_id is not None and (account is None or account.status != "active"):
            continue
        for service in carrier.services:
            if service.status != "active" or (service_id and service.id != service_id):
                continue
            contexts.append(
                ShippingContext(
                    ParcelInput(
                        package.id,
                        package.weight_grams,
                        package.length_mm,
                        package.width_mm,
                        package.height_mm,
                        destination,
                        f"{package.id}:{package.version_id}",
                    ),
                    carrier_input(carrier),
                    service_input(service),
                    account_input(account),
                )
            )
    return contexts


def carrier_input(carrier) -> CarrierInput:
    return CarrierInput(carrier.id, carrier.code, carrier.name, carrier.adapter_key)


def service_input(service) -> ServiceInput | None:
    if service is None:
        return None
    return ServiceInput(
        service.id,
        service.code,
        service.name,
        service.service_level,
        tuple(service.supported_countries),
        service.configuration,
    )


def account_input(account) -> AccountInput | None:
    if account is None:
        return None
    return AccountInput(account.id, account.auth_type, account.secret_reference)


async def destination_country(session, task_id):
    return await session.scalar(
        select(OrderRecipient.country_code)
        .join(LogisticsTask, LogisticsTask.order_id == OrderRecipient.order_id)
        .where(LogisticsTask.id == task_id)
    )


async def load_task(session, task_id):
    task = await session.get(LogisticsTask, task_id, with_for_update=True)
    if task is None:
        raise LogisticsShippingNotFoundError("Logistics task was not found.")
    return task


def mask_tracking(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 6:
        return f"{value[:1]}***{value[-1:]}"
    return f"{value[:2]}****{value[-4:]}"


def operation(tenant_id, task_id, actor_id, operation_type, before, after, details):
    return LogisticsTaskOperation(
        tenant_id=tenant_id,
        task_id=task_id,
        operation_type=operation_type,
        from_status=before,
        to_status=after,
        actor_user_id=actor_id,
        details=details,
    )


async def commit(session) -> None:
    try:
        await session.commit()
    except StaleDataError as error:
        raise LogisticsShippingConflictError(
            "Shipping data was changed by another operation."
        ) from error

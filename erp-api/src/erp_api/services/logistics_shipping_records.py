from erp_api.models.logistics_carrier import (
    LogisticsCarrier,
    LogisticsCarrierAccount,
    LogisticsCarrierService,
)
from erp_api.models.logistics_package import LogisticsPackage, LogisticsPackageItem
from erp_api.models.logistics_platform_carrier_mapping import (
    LogisticsPlatformCarrierMapping,
)
from erp_api.models.logistics_waybill import LogisticsWaybill


def package_record(package: LogisticsPackage) -> dict[str, object]:
    return {
        "id": package.id,
        "taskId": package.task_id,
        "packageNumber": package.package_number,
        "status": package.status,
        "weightGrams": package.weight_grams,
        "lengthMm": package.length_mm,
        "widthMm": package.width_mm,
        "heightMm": package.height_mm,
        "note": package.note,
        "createdByUserId": package.created_by_user_id,
        "sealedByUserId": package.sealed_by_user_id,
        "sealedAt": package.sealed_at,
        "createdAt": package.created_at,
        "updatedAt": package.updated_at,
        "versionId": package.version_id,
        "items": [_package_item_record(item) for item in package.items],
    }


def carrier_record(
    carrier: LogisticsCarrier,
    mappings: list[LogisticsPlatformCarrierMapping] | None = None,
) -> dict[str, object]:
    return {
        "id": carrier.id,
        "code": carrier.code,
        "name": carrier.name,
        "adapterKey": carrier.adapter_key,
        "status": carrier.status,
        "trackingUrlTemplate": carrier.tracking_url_template,
        "createdAt": carrier.created_at,
        "updatedAt": carrier.updated_at,
        "versionId": carrier.version_id,
        "services": [service_record(item) for item in carrier.services],
        "accounts": [account_record(item) for item in carrier.accounts],
        "platformMappings": [mapping_record(item) for item in mappings or []],
    }


def service_record(service: LogisticsCarrierService) -> dict[str, object]:
    suffix = "ShippingProviderId"
    return {
        "id": service.id,
        "carrierId": service.carrier_id,
        "code": service.code,
        "name": service.name,
        "serviceLevel": service.service_level,
        "supportedCountries": service.supported_countries,
        "platformProviderIds": {
            key[: -len(suffix)]: str(value)
            for key, value in service.configuration.items()
            if key.endswith(suffix) and value is not None
        },
        "trackingStatusMap": service.configuration.get("trackingStatusMap", {}),
        "status": service.status,
        "versionId": service.version_id,
    }


def account_record(account: LogisticsCarrierAccount) -> dict[str, object]:
    return {
        "id": account.id,
        "carrierId": account.carrier_id,
        "accountName": account.account_name,
        "accountIdentifierMasked": account.account_identifier_masked,
        "authType": account.auth_type,
        "status": account.status,
        "hasSecret": account.secret_reference is not None,
        "createdAt": account.created_at,
        "updatedAt": account.updated_at,
        "versionId": account.version_id,
    }


def mapping_record(mapping: LogisticsPlatformCarrierMapping) -> dict[str, object]:
    return {
        "id": mapping.id,
        "carrierId": mapping.carrier_id,
        "serviceId": mapping.service_id,
        "storeId": mapping.store_id,
        "platform": mapping.platform,
        "region": mapping.region,
        "platformCarrierId": mapping.platform_carrier_id,
        "platformCarrierCode": mapping.platform_carrier_code,
        "platformCarrierName": mapping.platform_carrier_name,
        "deliveryOptionId": mapping.delivery_option_id,
        "rawPayload": mapping.raw_payload,
        "status": mapping.status,
        "createdAt": mapping.created_at,
        "updatedAt": mapping.updated_at,
        "versionId": mapping.version_id,
    }


def waybill_record(waybill: LogisticsWaybill) -> dict[str, object]:
    return {
        "id": waybill.id,
        "packageId": waybill.package_id,
        "carrierId": waybill.carrier_id,
        "serviceId": waybill.service_id,
        "accountId": waybill.account_id,
        "waybillNumber": waybill.waybill_number,
        "externalWaybillId": waybill.external_waybill_id,
        "trackingNumberMasked": waybill.tracking_number_masked,
        "trackingStatus": waybill.tracking_status,
        "trackingOccurredAt": waybill.tracking_occurred_at,
        "trackingLastPolledAt": waybill.tracking_last_polled_at,
        "trackingPollErrorCode": waybill.tracking_poll_error_code,
        "labelUrl": waybill.label_url,
        "status": waybill.status,
        "isCurrent": waybill.is_current,
        "createdAt": waybill.created_at,
        "updatedAt": waybill.updated_at,
        "versionId": waybill.version_id,
    }


def _package_item_record(item: LogisticsPackageItem) -> dict[str, object]:
    return {
        "id": item.id,
        "taskItemId": item.task_item_id,
        "quantity": item.quantity,
    }

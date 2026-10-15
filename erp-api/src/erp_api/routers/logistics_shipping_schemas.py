from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from erp_api.routers.logistics_carrier_schemas import (
    PlatformCarrierMappingResponse,
)


class PackageItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taskItemId: UUID
    quantity: int = Field(ge=1)


class PackageDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(None, max_length=2000)


class PackageDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versionId: int = Field(ge=1)
    items: list[PackageItemCreate] = Field(min_length=1, max_length=500)
    weightGrams: int | None = Field(None, ge=1)
    lengthMm: int | None = Field(None, ge=1)
    widthMm: int | None = Field(None, ge=1)
    heightMm: int | None = Field(None, ge=1)
    note: str | None = Field(None, max_length=2000)


class PackageVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versionId: int = Field(ge=1)


class PackageItemResponse(BaseModel):
    id: UUID
    taskItemId: UUID
    quantity: int


class PackageResponse(BaseModel):
    id: UUID
    taskId: UUID
    packageNumber: str
    status: str
    weightGrams: int | None
    lengthMm: int | None
    widthMm: int | None
    heightMm: int | None
    note: str | None
    createdByUserId: UUID
    sealedByUserId: UUID | None
    sealedAt: datetime | None
    createdAt: datetime
    updatedAt: datetime
    versionId: int
    items: list[PackageItemResponse]


class CarrierCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=128)
    adapterKey: str = Field(
        default="manual", min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$"
    )
    trackingUrlTemplate: str | None = Field(None, max_length=1000)


class ManualPricingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseFeeMinor: int = Field(ge=0)
    perKgFeeMinor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    estimatedDaysMin: int | None = Field(None, ge=0)
    estimatedDaysMax: int | None = Field(None, ge=0)


class CarrierServiceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=128)
    serviceLevel: str | None = Field(None, max_length=64)
    supportedCountries: list[str] = Field(default_factory=list, max_length=250)
    manualPricing: ManualPricingRequest | None = None
    platformProviderIds: dict[str, str] = Field(default_factory=dict)
    trackingStatusMap: dict[
        str,
        Literal[
            "info_received",
            "picked_up",
            "in_transit",
            "out_for_delivery",
            "delivered",
            "exception",
            "returned",
            "cancelled",
        ],
    ] = Field(default_factory=dict)

    @field_validator("platformProviderIds")
    @classmethod
    def validate_platform_provider_ids(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("At most 20 platform provider IDs are allowed.")
        normalized: dict[str, str] = {}
        for platform, provider_id in value.items():
            platform_key = platform.strip().lower()
            provider_value = provider_id.strip()
            if not platform_key or not all(
                char.isascii() and (char.isalnum() or char in "_-")
                for char in platform_key
            ):
                raise ValueError("Platform keys must contain letters, digits, _ or -.")
            if not provider_value or len(provider_value) > 128:
                raise ValueError(
                    "Platform provider IDs must contain 1 to 128 characters."
                )
            normalized[platform_key] = provider_value
        return normalized


class CarrierAccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accountName: str = Field(min_length=1, max_length=128)
    accountIdentifierMasked: str | None = Field(None, max_length=256)
    authType: str = Field(default="manual", min_length=1, max_length=32)
    secretReference: str | None = Field(
        None,
        max_length=1000,
        pattern=r"^(env|vault|secret|aws-secrets|azure-keyvault|gcp-secret)://.+$",
    )


class CarrierServiceResponse(BaseModel):
    id: UUID
    carrierId: UUID
    code: str
    name: str
    serviceLevel: str | None
    supportedCountries: list[str]
    platformProviderIds: dict[str, str]
    trackingStatusMap: dict[str, str]
    status: str
    versionId: int


class CarrierAccountResponse(BaseModel):
    id: UUID
    carrierId: UUID
    accountName: str
    accountIdentifierMasked: str | None
    authType: str
    status: str
    hasSecret: bool
    createdAt: datetime
    updatedAt: datetime
    versionId: int


class CarrierResponse(BaseModel):
    id: UUID
    code: str
    name: str
    adapterKey: str
    status: str
    trackingUrlTemplate: str | None
    createdAt: datetime
    updatedAt: datetime
    versionId: int
    services: list[CarrierServiceResponse]
    accounts: list[CarrierAccountResponse]
    platformMappings: list[PlatformCarrierMappingResponse] = Field(default_factory=list)


class WaybillCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    carrierId: UUID
    serviceId: UUID
    accountId: UUID | None = None
    externalWaybillId: str | None = Field(None, max_length=128)
    trackingNumber: str | None = Field(None, min_length=1, max_length=128)


class ShippingQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    carrierId: UUID | None = None
    serviceId: UUID | None = None
    accountId: UUID | None = None


class ShippingQuoteResponse(BaseModel):
    carrierId: UUID
    carrierName: str
    serviceId: UUID
    serviceName: str
    accountId: UUID | None
    amountMinor: int | None
    currency: str | None
    estimatedDaysMin: int | None
    estimatedDaysMax: int | None
    quoteType: Literal["calculated", "manual"]
    warnings: list[str]


class WaybillCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versionId: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class WaybillResponse(BaseModel):
    id: UUID
    packageId: UUID
    carrierId: UUID
    serviceId: UUID | None
    accountId: UUID | None
    waybillNumber: str
    externalWaybillId: str | None
    trackingNumberMasked: str | None
    trackingStatus: str | None = None
    trackingOccurredAt: datetime | None = None
    trackingLastPolledAt: datetime | None = None
    trackingPollErrorCode: str | None = None
    labelUrl: str | None
    status: Literal[
        "created",
        "label_ready",
        "shipped",
        "in_transit",
        "delivered",
        "exception",
        "cancelled",
    ]
    isCurrent: bool
    createdAt: datetime
    updatedAt: datetime
    versionId: int

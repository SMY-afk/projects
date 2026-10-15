from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlatformCarrierMappingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storeId: UUID
    platform: str = Field(min_length=1, max_length=64)
    region: str = Field(default="GLOBAL", min_length=1, max_length=32)
    serviceId: UUID | None = None
    platformCarrierId: str = Field(min_length=1, max_length=128)
    platformCarrierCode: str | None = Field(None, max_length=128)
    platformCarrierName: str | None = Field(None, max_length=128)
    deliveryOptionId: str | None = Field(None, max_length=128)
    rawPayload: dict[str, object] = Field(default_factory=dict)

    @field_validator("platform")
    @classmethod
    def normalize_platform(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not all(
            char.isascii() and (char.isalnum() or char in "_-") for char in normalized
        ):
            raise ValueError("Platform must contain letters, digits, _ or -.")
        return normalized

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not all(
            char.isascii() and (char.isalnum() or char in "_-") for char in normalized
        ):
            raise ValueError("Region must contain letters, digits, _ or -.")
        return normalized

    @field_validator("platformCarrierId")
    @classmethod
    def strip_required_mapping_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Platform carrier ID cannot be blank.")
        return normalized

    @field_validator("platformCarrierCode", "platformCarrierName", "deliveryOptionId")
    @classmethod
    def strip_optional_mapping_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class PlatformCarrierMappingUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versionId: int = Field(ge=1)
    status: Literal["active", "inactive"] | None = None
    platformCarrierId: str | None = Field(None, min_length=1, max_length=128)
    platformCarrierCode: str | None = Field(None, max_length=128)
    platformCarrierName: str | None = Field(None, max_length=128)
    deliveryOptionId: str | None = Field(None, max_length=128)
    rawPayload: dict[str, object] | None = None

    @field_validator("platformCarrierId")
    @classmethod
    def strip_mapping_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Platform carrier ID cannot be blank.")
        return normalized

    @field_validator("platformCarrierCode", "platformCarrierName", "deliveryOptionId")
    @classmethod
    def strip_mapping_name(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class PlatformCarrierMappingResponse(BaseModel):
    id: UUID
    carrierId: UUID
    serviceId: UUID | None
    storeId: UUID
    platform: str
    region: str
    platformCarrierId: str
    platformCarrierCode: str | None
    platformCarrierName: str | None
    deliveryOptionId: str | None
    rawPayload: dict[str, object]
    status: str
    createdAt: datetime
    updatedAt: datetime
    versionId: int

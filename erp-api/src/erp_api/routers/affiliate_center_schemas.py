from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AffiliateResource = Literal["creators", "videos"]


def _external_sync_schema(schema: dict[str, object]) -> None:
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        return
    for internal, external in (
        ("shop_id", "shopId"),
        ("window_start", "from"),
        ("window_end", "to"),
    ):
        properties[external] = properties.pop(internal)
        required[required.index(internal)] = external


class AffiliateSyncRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra=_external_sync_schema)

    shop_id: UUID
    window_start: date
    window_end: date
    currency: str = Field(min_length=3, max_length=3)
    resources: list[AffiliateResource] = Field(
        default_factory=lambda: ["creators", "videos"], min_length=1
    )

    @model_validator(mode="before")
    @classmethod
    def accept_external_names(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for external, internal in (
            ("shopId", "shop_id"),
            ("from", "window_start"),
            ("to", "window_end"),
        ):
            if external in normalized and internal not in normalized:
                normalized[internal] = normalized[external]
        return normalized

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha():
            raise ValueError("currency must be a three-letter code")
        return normalized

    @model_validator(mode="after")
    def validate_window_and_resources(self):
        if self.window_end < self.window_start:
            raise ValueError("to cannot be earlier than from")
        self.resources = list(dict.fromkeys(self.resources))
        return self

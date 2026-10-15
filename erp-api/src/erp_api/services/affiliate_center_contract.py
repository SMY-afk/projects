from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from hashlib import sha256
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_FILTER_JSON_BYTES = 16_384
SENSITIVE_FILTER_KEYS = frozenset(
    {
        "accesstoken",
        "refreshtoken",
        "authorization",
        "cookie",
        "oauthcode",
        "secret",
        "signature",
    }
)


class AffiliateCenterQueryError(ValueError):
    pass


class AffiliateCenterResource(StrEnum):
    CREATORS = "creators"
    VIDEOS = "videos"


@dataclass(frozen=True)
class AffiliateCenterQuery:
    resource: AffiliateCenterResource
    shop_id: UUID
    window_start: date
    window_end: date
    shop_timezone: str
    currency: str
    filters: Mapping[str, object]

    def __post_init__(self) -> None:
        try:
            resource = AffiliateCenterResource(self.resource)
        except ValueError as error:
            raise AffiliateCenterQueryError(
                "联盟中心资源必须是 creators 或 videos。"
            ) from error
        if not isinstance(self.shop_id, UUID):
            raise AffiliateCenterQueryError("shopId 必须是有效 UUID。")
        if not isinstance(self.window_start, date) or isinstance(
            self.window_start, datetime
        ):
            raise AffiliateCenterQueryError("windowStart 必须是店铺本地日期。")
        if not isinstance(self.window_end, date) or isinstance(
            self.window_end, datetime
        ):
            raise AffiliateCenterQueryError("windowEnd 必须是店铺本地日期。")
        if self.window_end < self.window_start:
            raise AffiliateCenterQueryError("结束日期不能早于开始日期。")
        timezone = self.shop_timezone.strip()
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise AffiliateCenterQueryError(
                "shopTimezone 必须是有效 IANA 时区。"
            ) from error
        currency = self.currency.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise AffiliateCenterQueryError("币种必须是三位 ISO 4217 代码。")
        filters = _normalize_filters(self.filters)
        encoded = json.dumps(
            filters, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        if len(encoded) > MAX_FILTER_JSON_BYTES:
            raise AffiliateCenterQueryError("filters 不能超过 16 KB。")
        object.__setattr__(self, "resource", resource)
        object.__setattr__(self, "shop_timezone", timezone)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "filters", filters)

    def canonical_dimensions(self) -> dict[str, object]:
        return {
            "shopId": str(self.shop_id),
            "windowStart": self.window_start.isoformat(),
            "windowEnd": self.window_end.isoformat(),
            "shopTimezone": self.shop_timezone,
            "currency": self.currency,
            "filters": self.filters,
        }

    @property
    def fingerprint(self) -> str:
        payload = {"resource": self.resource.value, **self.canonical_dimensions()}
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        return sha256(encoded).hexdigest()

    def utc_window(self) -> tuple[datetime, datetime]:
        timezone = ZoneInfo(self.shop_timezone)
        start = datetime.combine(self.window_start, time.min, timezone)
        end = datetime.combine(self.window_end + timedelta(days=1), time.min, timezone)
        return start.astimezone(UTC), end.astimezone(UTC)

    def with_resource(self, resource: AffiliateCenterResource) -> AffiliateCenterQuery:
        return replace(self, resource=resource)


def parse_filter_json(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AffiliateCenterQueryError("filters 必须是有效 JSON 对象。") from error
    return _normalize_filters(value)


def _normalize_filters(value: object, depth: int = 0) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AffiliateCenterQueryError("filters 必须是 JSON 对象。")
    return {
        key: _normalize_filter_value(item, depth + 1)
        for key, item in sorted(value.items())
        if _validate_filter_key(key)
    }


def _normalize_filter_value(value: object, depth: int) -> object:
    if depth > 5:
        raise AffiliateCenterQueryError("filters 嵌套不能超过五层。")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Mapping):
        return _normalize_filters(value, depth)
    if isinstance(value, (list, tuple)):
        return [_normalize_filter_value(item, depth + 1) for item in value]
    raise AffiliateCenterQueryError("filters 只能包含 JSON 标量、数组或对象。")


def _validate_filter_key(key: object) -> bool:
    if not isinstance(key, str) or not key or len(key) > 100:
        raise AffiliateCenterQueryError("filters 键必须是 1 到 100 个字符的字符串。")
    normalized = re.sub(r"[^a-z]", "", key.casefold())
    if normalized in SENSITIVE_FILTER_KEYS:
        raise AffiliateCenterQueryError("filters 不允许包含凭证或签名等敏感字段。")
    return True

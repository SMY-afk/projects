from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

CaptureHealthState = Literal[
    "browser_offline",
    "connecting",
    "online",
    "session_expired",
    "captcha",
]
BLOCKED_STATES = frozenset({"browser_offline", "session_expired", "captcha"})
HEALTH_TTL_SECONDS = 45
# Keep the last directly observed availability date for one operating shift.
# Browser and authenticated-session health retain their short heartbeat TTL,
# so this does not turn an old date into proof that the browser is still online.
OBSERVATION_TTL_SECONDS = 6 * 60 * 60
_UNSET = object()


@dataclass(frozen=True)
class AffiliateCaptureHealth:
    state: CaptureHealthState
    cdp_available: bool
    session_available: bool
    updated_at: datetime
    recovered_at: datetime | None = None
    latest_available_date: date | None = None
    latest_available_dates: dict[str, date] = field(default_factory=dict)

    def date_for(self, resource: str) -> date | None:
        return self.latest_available_dates.get(resource)

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "cdpAvailable": self.cdp_available,
            "sessionAvailable": self.session_available,
            "updatedAt": self.updated_at.isoformat(),
            "recoveredAt": (
                self.recovered_at.isoformat() if self.recovered_at else None
            ),
            "latestAvailableDate": (
                self.latest_available_date.isoformat()
                if self.latest_available_date
                else None
            ),
            "latestAvailableDates": {
                resource: value.isoformat()
                for resource, value in self.latest_available_dates.items()
            },
        }


class AffiliateCaptureHealthRepository:
    def __init__(self, redis) -> None:
        self._redis = redis
        self._write_lock = asyncio.Lock()

    async def get(self, tenant_id: UUID, shop_id: UUID) -> AffiliateCaptureHealth:
        stored = await self._load(tenant_id, shop_id)
        return stored or _health("browser_offline", datetime.now(UTC))

    async def record_observation(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        resource: str,
        day: date,
        *,
        now: datetime | None = None,
    ) -> None:
        if resource not in {"creators", "videos", "liveAccounts"}:
            raise ValueError("Unsupported TK availability resource")
        timestamp = _utc(now or datetime.now(UTC))
        previous = await self.observed_date_for(
            tenant_id, shop_id, resource, now=timestamp
        )
        if previous is not None and day < previous:
            raise ValueError(f"TK {resource} availability date regressed")
        await self._redis.set(
            _observation_key(tenant_id, shop_id, resource),
            json.dumps({"date": day.isoformat(), "observedAt": timestamp.isoformat()}),
            ex=OBSERVATION_TTL_SECONDS,
        )

    async def observed_date_for(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        resource: str,
        *,
        now: datetime | None = None,
    ) -> date | None:
        observation = await self.observed_evidence_for(
            tenant_id, shop_id, resource, now=now
        )
        return observation[0] if observation is not None else None

    async def observed_evidence_for(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        resource: str,
        *,
        now: datetime | None = None,
    ) -> tuple[date, datetime] | None:
        if resource not in {"creators", "videos", "liveAccounts"}:
            return None
        raw = await self._redis.get(_observation_key(tenant_id, shop_id, resource))
        if raw is None:
            return None
        try:
            value = json.loads(raw)
            observed_at = _utc(datetime.fromisoformat(value["observedAt"]))
            age = _utc(now or datetime.now(UTC)) - observed_at
            if not timedelta(0) <= age <= timedelta(seconds=OBSERVATION_TTL_SECONDS):
                return None
            return date.fromisoformat(value["date"]), observed_at
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    async def record(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        state: CaptureHealthState,
        *,
        now: datetime | None = None,
        latest_available_date: date | None | object = _UNSET,
        latest_available_dates: dict[str, date] | object = _UNSET,
    ) -> AffiliateCaptureHealth:
        async with self._write_lock:
            return await self._record_unlocked(
                tenant_id,
                shop_id,
                state,
                now=now,
                latest_available_date=latest_available_date,
                latest_available_dates=latest_available_dates,
            )

    async def _record_unlocked(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        state: CaptureHealthState,
        *,
        now: datetime | None = None,
        latest_available_date: date | None | object = _UNSET,
        latest_available_dates: dict[str, date] | object = _UNSET,
    ) -> AffiliateCaptureHealth:
        timestamp = _utc(now or datetime.now(UTC))
        previous = await self._load(tenant_id, shop_id)
        recovered_at = previous.recovered_at if previous else None
        if (
            state == "online"
            and previous is not None
            and previous.state in BLOCKED_STATES
        ):
            recovered_at = timestamp
        if latest_available_date is _UNSET:
            resolved_latest = previous.latest_available_date if previous else None
        else:
            resolved_latest = (
                latest_available_date
                if isinstance(latest_available_date, date)
                else None
            )
        if latest_available_dates is _UNSET:
            resolved_dates = dict(previous.latest_available_dates) if previous else {}
        else:
            resolved_dates = (
                dict(latest_available_dates)
                if isinstance(latest_available_dates, dict)
                else {}
            )
        health = _health(
            state,
            timestamp,
            recovered_at=recovered_at,
            latest_available_date=resolved_latest,
            latest_available_dates=resolved_dates,
        )
        await self._redis.set(
            _key(tenant_id, shop_id),
            json.dumps(health.as_dict(), separators=(",", ":")),
            ex=HEALTH_TTL_SECONDS,
        )
        return health

    async def _load(
        self, tenant_id: UUID, shop_id: UUID
    ) -> AffiliateCaptureHealth | None:
        raw = await self._redis.get(_key(tenant_id, shop_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            value = json.loads(raw)
            state = value["state"]
            if state not in {
                "browser_offline",
                "connecting",
                "online",
                "session_expired",
                "captcha",
            }:
                return None
            recovered = value.get("recoveredAt")
            latest = value.get("latestAvailableDate")
            latest_dates = value.get("latestAvailableDates")
            return AffiliateCaptureHealth(
                state=state,
                cdp_available=bool(value["cdpAvailable"]),
                session_available=bool(value["sessionAvailable"]),
                updated_at=_utc(datetime.fromisoformat(value["updatedAt"])),
                recovered_at=(
                    _utc(datetime.fromisoformat(recovered)) if recovered else None
                ),
                latest_available_date=(date.fromisoformat(latest) if latest else None),
                latest_available_dates=_parse_dates(latest_dates),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None


def _health(
    state: CaptureHealthState,
    updated_at: datetime,
    *,
    recovered_at: datetime | None = None,
    latest_available_date: date | None = None,
    latest_available_dates: dict[str, date] | None = None,
) -> AffiliateCaptureHealth:
    cdp_available = state in {"online", "session_expired", "captcha"}
    return AffiliateCaptureHealth(
        state=state,
        cdp_available=cdp_available,
        session_available=state == "online",
        updated_at=_utc(updated_at),
        recovered_at=_utc(recovered_at) if recovered_at else None,
        latest_available_date=latest_available_date,
        latest_available_dates=latest_available_dates or {},
    )


def _parse_dates(value: object) -> dict[str, date]:
    if not isinstance(value, dict):
        return {}
    return {
        resource: date.fromisoformat(day)
        for resource, day in value.items()
        if resource in {"creators", "videos", "liveAccounts"} and isinstance(day, str)
    }


def _key(tenant_id: UUID, shop_id: UUID) -> str:
    return f"affiliate:capture-health:{tenant_id}:{shop_id}"


def _observation_key(tenant_id: UUID, shop_id: UUID, resource: str) -> str:
    return f"affiliate:tk-observation:{tenant_id}:{shop_id}:{resource}"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Capture health timestamps must include a UTC offset.")
    return value.astimezone(UTC)

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from erp_api.services.sample_bd_invitation_ai_times import (
    AiInvitationTimes,
    read_ai_invitation_times,
)

AI_INVITATION_SAME_CHECK_WINDOW = timedelta(seconds=90)


@dataclass(frozen=True)
class AiInvitationSnapshot:
    observed_at: datetime
    creator_ids: frozenset[str]


class AiInvitationSnapshotStore:
    def __init__(self, redis, *, spreadsheet_token: str, sheet_id: str) -> None:
        if not spreadsheet_token or not sheet_id:
            raise ValueError("AI invitation snapshot source is required.")
        source_hash = hashlib.sha256(
            f"{spreadsheet_token}/{sheet_id}".encode()
        ).hexdigest()[:24]
        self._redis = redis
        self.key = f"sample:bd_invitation:ai_snapshot:v1:{source_hash}"

    async def load(self) -> AiInvitationSnapshot | None:
        raw = await self._redis.get(self.key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            observed_at = datetime.fromisoformat(data["observed_at"])
            creator_ids = data["creator_ids"]
            if (
                observed_at.utcoffset() is None
                or not isinstance(creator_ids, list)
                or any(not isinstance(value, str) or not value for value in creator_ids)
                or len(set(creator_ids)) != len(creator_ids)
            ):
                raise ValueError("invalid snapshot")
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise RuntimeError("AI invitation snapshot is invalid.") from exc
        return AiInvitationSnapshot(observed_at.astimezone(UTC), frozenset(creator_ids))

    async def save(self, snapshot: AiInvitationSnapshot) -> None:
        if snapshot.observed_at.utcoffset() is None:
            raise ValueError("AI invitation snapshot time must be timezone-aware.")
        payload = json.dumps(
            {
                "observed_at": snapshot.observed_at.astimezone(UTC).isoformat(),
                "creator_ids": sorted(snapshot.creator_ids),
            },
            separators=(",", ":"),
        )
        await self._redis.set(self.key, payload)


@dataclass(frozen=True)
class AiInvitationCheckWindow:
    store: AiInvitationSnapshotStore
    previous: AiInvitationSnapshot | None
    current: AiInvitationSnapshot
    invitation_times: AiInvitationTimes

    @classmethod
    async def capture(cls, store, client, now: datetime) -> AiInvitationCheckWindow:
        previous = await store.load()
        invitations = await read_ai_invitation_times(client, now=now)
        return cls(
            store,
            previous,
            AiInvitationSnapshot(now, invitations.creator_ids),
            invitations,
        )

    def classify(self, creator_id: str, submitted_at: datetime):
        return self.invitation_times.classify(creator_id, submitted_at)

    def both_new(self, creator_id: str, bd_created_at: datetime) -> bool:
        previous = self.previous
        if previous is None:
            return False
        elapsed = self.current.observed_at - previous.observed_at
        return (
            timedelta(0) < elapsed <= AI_INVITATION_SAME_CHECK_WINDOW
            and bd_created_at.astimezone(UTC) > previous.observed_at
            and creator_id not in previous.creator_ids
            and creator_id in self.current.creator_ids
        )

    async def save(self) -> None:
        await self.store.save(self.current)

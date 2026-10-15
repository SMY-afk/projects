from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from erp_api.services.sample_ai_invitation_mirror import (
    AI_INVITATION_CREATOR_FIELD,
    AI_INVITATION_TIME_FIELD,
)
from erp_api.services.sample_cooperation_parsing import (
    CHINA_TIMEZONE,
    normalize_account_name,
    plain_text,
)

AI_INVITATION_HIT_WINDOW = timedelta(days=7)
AiInvitationMatch = Literal["hit", "miss", "pending"]
AI_INVITATION_TIME_PENDING_REMARK = "AI邀约时间待核验；不授予新BD保护；保留记录待核验"


def parse_invitation_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        # Bitable dates are epoch milliseconds; never guess Sheet serial numbers.
        if abs(value) < 1_000_000_000:
            return None
        seconds = value / 1000 if abs(value) >= 100_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, UTC)
        except (ValueError, OverflowError, OSError):
            return None
    else:
        text = plain_text(value)
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("/", "-"))
        except ValueError:
            return None
    if parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=CHINA_TIMEZONE)
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class AiInvitationTimes:
    invitations: dict[str, tuple[datetime, ...]]
    unverified_ids: frozenset[str]

    @property
    def creator_ids(self) -> frozenset[str]:
        return frozenset(self.invitations) | self.unverified_ids

    @classmethod
    def from_rows(cls, rows, *, now: datetime) -> AiInvitationTimes:
        if now.utcoffset() is None:
            raise ValueError("AI invitation observation time must include a timezone.")
        now = now.astimezone(UTC)
        invitations: dict[str, set[datetime]] = {}
        unverified: set[str] = set()
        for account, raw_time in rows:
            creator_id = normalize_account_name(account)
            if not creator_id:
                continue
            invited_at = parse_invitation_time(raw_time)
            if invited_at is None or invited_at > now:
                unverified.add(creator_id)
            else:
                invitations.setdefault(creator_id, set()).add(invited_at)
        return cls(
            {key: tuple(sorted(values)) for key, values in invitations.items()},
            frozenset(unverified),
        )

    def classify(self, creator_id: str, submitted_at: datetime) -> AiInvitationMatch:
        if submitted_at.utcoffset() is None:
            raise ValueError("BD invitation submission time must include a timezone.")
        creator_id = normalize_account_name(creator_id)
        if creator_id in self.unverified_ids:
            return "pending"
        submitted_at = submitted_at.astimezone(UTC)
        return (
            "hit"
            if any(
                invited_at <= submitted_at < invited_at + AI_INVITATION_HIT_WINDOW
                for invited_at in self.invitations.get(creator_id, ())
            )
            else "miss"
        )


async def read_ai_invitation_times(client, *, now: datetime) -> AiInvitationTimes:
    sheet_reader = getattr(client, "list_invitation_rows", None)
    if sheet_reader is not None:
        rows = await sheet_reader()
    else:
        records = await client.list_record_snapshots(
            field_names=(AI_INVITATION_CREATOR_FIELD, AI_INVITATION_TIME_FIELD)
        )
        rows = tuple(
            (
                record.snapshot.fields.get(AI_INVITATION_CREATOR_FIELD),
                record.snapshot.fields.get(AI_INVITATION_TIME_FIELD),
            )
            for record in records
        )
    return AiInvitationTimes.from_rows(rows, now=now)

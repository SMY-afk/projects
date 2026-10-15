from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from erp_api.services.sample_bd_invitation_ai_priority import AiInvitationCheckWindow
from erp_api.services.sample_bd_invitation_ai_times import (
    read_ai_invitation_times,
)
from erp_api.services.sample_bd_invitation_remarks import (
    _protection_remark,
    _unverified_ai_remark,
    _was_bd_protected,
)
from erp_api.services.sample_bd_invitation_submission import (
    BD_INVITATION_CREATOR_FIELD,
    BD_INVITATION_ORIGINAL_SUBMITTER_FIELD,
    BD_INVITATION_OWNER_FIELD,
    BD_INVITATION_REMARK_FIELD,
    business_records,
    split_batch_submissions,
)
from erp_api.services.sample_cooperation_parsing import (
    normalize_account_name,
    plain_text,
)
from erp_api.services.sample_cooperation_rules import BdInvitationProtection

BD_INVITATION_HIT_RETENTION = timedelta(hours=24)
BD_INVITATION_RETENTION = timedelta(days=7)


@dataclass(frozen=True)
class BdInvitationLookupSource:
    label: str
    client: object
    creator_field: str


@dataclass(frozen=True)
class BdInvitationProtectionRefresh:
    active: dict[str, BdInvitationProtection]
    deleted_count: int
    updated_count: int
    pending_creator_ids: frozenset[str] = frozenset()


class SampleBdInvitationProtectionService:
    def __init__(
        self,
        client,
        *,
        lookup_sources: tuple[BdInvitationLookupSource, ...] = (),
        unavailable_sources: tuple[str, ...] = (),
        ai_snapshot_store=None,
        retention: timedelta = BD_INVITATION_RETENTION,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        if retention <= timedelta(0):
            raise ValueError("BD invitation protection retention must be positive.")
        self._client = client
        self._lookup_sources = lookup_sources
        self._unavailable_sources = unavailable_sources
        self._ai_snapshot_store = ai_snapshot_store
        self._retention = retention
        self._clock = clock
        labels = tuple(source.label for source in lookup_sources) + unavailable_sources
        if any(not label.strip() for label in labels) or len(set(labels)) != len(
            labels
        ):
            raise ValueError("BD invitation lookup source labels must be unique.")

    async def validate(self) -> None:
        fields = await self._client.list_field_metadata()
        expected = {
            BD_INVITATION_CREATOR_FIELD: 1,
            BD_INVITATION_OWNER_FIELD: 3,
            BD_INVITATION_REMARK_FIELD: 1,
            BD_INVITATION_ORIGINAL_SUBMITTER_FIELD: 1,
        }
        invalid = {
            name: None if fields.get(name) is None else fields[name].field_type
            for name, field_type in expected.items()
            if fields.get(name) is None or fields[name].field_type != field_type
        }
        if invalid:
            raise RuntimeError(
                f"BD invitation protection fields are invalid: {invalid}."
            )
        for source in self._lookup_sources:
            source_fields = await source.client.list_field_metadata()
            metadata = source_fields.get(source.creator_field)
            if metadata is None or metadata.field_type != 1:
                raise RuntimeError(
                    f"BD invitation lookup field is invalid: {source.label}."
                )

    async def refresh(
        self, *, save_ai_snapshot: bool = False
    ) -> BdInvitationProtectionRefresh:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("BD invitation protection clock must include a timezone.")
        now = now.astimezone(UTC)
        ai_source = next(
            (source for source in self._lookup_sources if source.label == "AI邀约表"),
            None,
        )
        ai_window = (
            await AiInvitationCheckWindow.capture(
                self._ai_snapshot_store, ai_source.client, now
            )
            if self._ai_snapshot_store is not None and ai_source is not None
            else None
        )
        ai_times = (
            ai_window.invitation_times
            if ai_window is not None
            else await read_ai_invitation_times(ai_source.client, now=now)
            if ai_source is not None
            else None
        )
        records = await self._client.list_record_snapshots(
            field_names=(
                BD_INVITATION_CREATOR_FIELD,
                BD_INVITATION_OWNER_FIELD,
                BD_INVITATION_REMARK_FIELD,
                BD_INVITATION_ORIGINAL_SUBMITTER_FIELD,
            ),
        )
        records = business_records(records)
        if await split_batch_submissions(self._client, records):
            records = await self._client.list_record_snapshots(
                field_names=(
                    BD_INVITATION_CREATOR_FIELD,
                    BD_INVITATION_OWNER_FIELD,
                    BD_INVITATION_REMARK_FIELD,
                    BD_INVITATION_ORIGINAL_SUBMITTER_FIELD,
                ),
            )
            records = business_records(records)
        creator_ids = frozenset(
            creator_id
            for record in records
            if (
                creator_id := normalize_account_name(
                    record.snapshot.fields.get(BD_INVITATION_CREATOR_FIELD)
                )
            )
        )
        source_matches = await asyncio.gather(
            *(
                source.client.match_creator_ids(
                    creator_ids,
                    field_name=source.creator_field,
                )
                for source in self._lookup_sources
                if source.label != "AI邀约表"
            )
        )
        source_creator_ids = {
            source.label: matches
            for source, matches in zip(
                (
                    source
                    for source in self._lookup_sources
                    if source.label != "AI邀约表"
                ),
                source_matches,
                strict=True,
            )
        }
        active: dict[str, BdInvitationProtection] = {}
        pending_creator_ids: set[str] = set()
        expired_ids: list[str] = []
        remark_updates: list[tuple[str, str]] = []
        for record in records:
            created_at = record.snapshot.created_at
            if created_at is None:
                raise RuntimeError(
                    "BD invitation protection record is missing created time."
                )
            fields = record.snapshot.fields
            creator_id = normalize_account_name(fields.get(BD_INVITATION_CREATOR_FIELD))
            bd_name = plain_text(fields.get(BD_INVITATION_OWNER_FIELD))
            if not creator_id or not bd_name:
                raise RuntimeError(
                    "BD invitation protection record requires creator ID and BD owner."
                )
            ai_match = ai_times.classify(creator_id, created_at) if ai_times else "miss"
            if ai_match == "pending":
                pending_creator_ids.add(creator_id)
                prior_remark = plain_text(fields.get(BD_INVITATION_REMARK_FIELD))
                non_ai_hits = tuple(
                    source.label
                    for source in self._lookup_sources
                    if source.label != "AI邀约表"
                    and creator_id in source_creator_ids[source.label]
                )
                remark = _unverified_ai_remark(non_ai_hits, prior_remark)
                if prior_remark != remark:
                    remark_updates.append((record.record_id, remark))
                continue
            matched_sources = tuple(
                source.label
                for source in self._lookup_sources
                if (
                    ai_match == "hit"
                    if source.label == "AI邀约表"
                    else creator_id in source_creator_ids[source.label]
                )
            )
            prior_remark = plain_text(fields.get(BD_INVITATION_REMARK_FIELD))
            simultaneous = (
                not prior_remark
                and ai_window is not None
                and ai_window.both_new(creator_id, created_at)
            )
            bd_first = (
                _was_bd_protected(prior_remark) or not matched_sources or simultaneous
            )
            effective_sources = tuple(
                source
                for source in matched_sources
                if not (bd_first and source == "AI邀约表")
            )
            retention = (
                BD_INVITATION_HIT_RETENTION if effective_sources else self._retention
            )
            expires_at = created_at.astimezone(UTC) + retention
            if expires_at <= now:
                expired_ids.append(record.record_id)
                continue
            remark = _protection_remark(
                effective_sources,
                tuple(source.label for source in self._lookup_sources),
                self._unavailable_sources,
            )
            if bd_first and "AI邀约表" in matched_sources and not effective_sources:
                remark = (
                    "同轮新增，BD优先；AI邀约表后续命中不影响原BD保护；按创建时间保存7天"
                    if simultaneous or "同轮新增，BD优先" in prior_remark
                    else "BD先提交；后续命中AI邀约表不影响原BD保护；按创建时间保存7天"
                )
            elif bd_first and (
                effective_sources
                or "BD先提交" in prior_remark
                or "同轮新增，BD优先" in prior_remark
            ):
                marker = (
                    "同轮新增，BD优先"
                    if simultaneous or "同轮新增，BD优先" in prior_remark
                    else "BD先提交"
                )
                remark = f"{remark}；{marker}"
            if prior_remark != remark:
                remark_updates.append((record.record_id, remark))
            if effective_sources:
                continue
            previous = active.get(creator_id)
            if previous is not None and previous.bd_name != bd_name:
                raise RuntimeError(
                    f"BD invitation protection creator ID is duplicated: {creator_id}."
                )
            if previous is None or previous.expires_at < expires_at:
                active[creator_id] = BdInvitationProtection(
                    record.record_id,
                    creator_id,
                    bd_name,
                    expires_at,
                )
        for offset in range(0, len(expired_ids), 500):
            await self._client.batch_delete_records(expired_ids[offset : offset + 500])
        for offset in range(0, len(remark_updates), 500):
            await self._client.batch_update_remarks(
                remark_updates[offset : offset + 500]
            )
        if save_ai_snapshot and ai_window is not None:
            await ai_window.save()
        return BdInvitationProtectionRefresh(
            active,
            len(expired_ids),
            len(remark_updates),
            frozenset(pending_creator_ids),
        )

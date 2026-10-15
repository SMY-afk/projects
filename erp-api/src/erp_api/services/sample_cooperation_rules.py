from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from erp_api.services.sample_cooperation_decision_builder import (
    decision_for_rows as _decision,
)
from erp_api.services.sample_cooperation_parsing import (
    is_blank_approved_date,
    is_current_bd_owner,
    normalize_account_name,
    normalize_bd_name,
    parse_approved_date,
    split_bd_owners,
)
from erp_api.services.sample_creator_assignment_ownership import (
    CreatorAssignmentOwner,
    assignment_owner_protection_reason,
)
from erp_api.services.sample_daily_valid_bd_rule import (
    daily_valid_decision,
    reconcile_daily_recipients,
    scope_daily_valid_creators,
)

COOPERATION_ALLOWED_EVENT = "sample_cooperation_allowed"
COOPERATION_RECENT_EVENT = "sample_cooperation_recent"
COOPERATION_ACTIVE_CREATOR_EVENT = "sample_cooperation_active_creator"
COOPERATION_BD_INVITATION_EVENT = "sample_bd_invitation_protected"
COOPERATION_OWNER_PROTECTED_EVENT = "sample_creator_assignment_owner_protected"
COOPERATION_EXCEPTION_EVENT = "sample_cooperation_exception"
COOPERATION_DECISION_EVENTS = frozenset(
    {
        COOPERATION_ALLOWED_EVENT,
        COOPERATION_RECENT_EVENT,
        COOPERATION_ACTIVE_CREATOR_EVENT,
        COOPERATION_BD_INVITATION_EVENT,
        COOPERATION_OWNER_PROTECTED_EVENT,
        COOPERATION_EXCEPTION_EVENT,
    }
)
COOPERATION_EVENT_SOURCE = "feishu_cooperation_precheck"
@dataclass(frozen=True)
class CooperationCandidate:
    application_id: UUID
    platform_application_id: str
    creator_id: str | None
    shop_name: str
    applied_at: datetime | None = None
@dataclass(frozen=True)
class CooperationRecipient:
    name: str
    open_id: str
@dataclass(frozen=True)
class CooperationRow:
    source: str
    record_id: str
    account_name: Any
    bd_owner: Any
    approved_date: Any
@dataclass(frozen=True)
class BdInvitationProtection:
    record_id: str
    creator_id: str
    bd_name: str
    expires_at: datetime | None
@dataclass(frozen=True)
class CooperationSnapshot:
    rows: tuple[CooperationRow, ...]
    recipients: dict[str, CooperationRecipient]
    current_bd_names: frozenset[str] = frozenset()
    valid_creator_ids: frozenset[str] = frozenset()
    ai_invitation_creator_ids: frozenset[str] = frozenset()
    assignment_owners: dict[str, CreatorAssignmentOwner] | None = None
    protected_creators: dict[str, BdInvitationProtection] | None = None
    daily_valid_rows: tuple[CooperationRow, ...] = ()
@dataclass(frozen=True)
class CooperationDecision:
    candidate: CooperationCandidate
    event_type: str
    reason: str
    matched_count: int = 0
    recent_date: date | None = None
    sources: tuple[str, ...] = ()
    recipients: tuple[CooperationRecipient, ...] = ()
    protected_bd_name: str | None = None
    protected_until: datetime | None = None
    owner_bd_name: str | None = None
    owner_assigned_at: datetime | None = None

    @property
    def blocks_assignment(self) -> bool:
        return self.event_type != COOPERATION_ALLOWED_EVENT
def decide_cooperation(
    candidate: CooperationCandidate,
    snapshot: CooperationSnapshot,
    *,
    today: date,
    now: datetime | None = None,
) -> CooperationDecision:
    creator_id = normalize_account_name(candidate.creator_id)
    if not creator_id:
        return CooperationDecision(candidate, COOPERATION_EXCEPTION_EVENT, "creator_id_missing")
    snapshot = scope_daily_valid_creators(candidate, snapshot)
    current_bd_names = snapshot.current_bd_names or frozenset(snapshot.recipients)
    owner = (snapshot.assignment_owners or {}).get(creator_id)
    if owner is not None and is_current_bd_owner(owner.bd_name, current_bd_names):
        owner_decision = _assignment_owner_decision(
            candidate,
            snapshot,
            owner,
            now=now or datetime.combine(today, datetime.max.time(), tzinfo=UTC),
        )
        if owner_decision is not None:
            return owner_decision
    protection = (snapshot.protected_creators or {}).get(creator_id)
    if protection is not None:
        return CooperationDecision(
            candidate,
            COOPERATION_BD_INVITATION_EVENT,
            "bd_invitation_protected",
            matched_count=1,
            sources=("BD自主邀约收集表",),
            protected_bd_name=protection.bd_name,
            protected_until=protection.expires_at,
        )
    account_matches = tuple(
        row
        for row in snapshot.rows
        if normalize_account_name(row.account_name) == creator_id
    )
    if any(not split_bd_owners(row.bd_owner) for row in account_matches):
        return _decision(candidate, COOPERATION_EXCEPTION_EVENT, "bd_owner_missing", account_matches)
    matches = tuple(
        row
        for row in account_matches
        if any(
            is_current_bd_owner(owner, current_bd_names)
            for owner in split_bd_owners(row.bd_owner)
        )
    )
    if not matches:
        daily_decision = daily_valid_decision(candidate, snapshot)
        if daily_decision is not None:
            return daily_decision
        if account_matches:
            return _decision(
                candidate,
                COOPERATION_ALLOWED_EVENT,
                "no_current_bd_owner",
                account_matches,
            )
        if creator_id in snapshot.valid_creator_ids:
            return CooperationDecision(
                candidate, COOPERATION_EXCEPTION_EVENT, "active_creator_bd_unavailable"
            )
        return CooperationDecision(
            candidate, COOPERATION_ALLOWED_EVENT, "not_registered"
        )
    dated: list[tuple[CooperationRow, date]] = []
    invalid_date = False
    for row in matches:
        if is_blank_approved_date(row.approved_date):
            continue
        approved = parse_approved_date(row.approved_date, today=today)
        if approved is None:
            invalid_date = True
        else:
            dated.append((row, approved))
    if invalid_date:
        return _decision(
            candidate,
            COOPERATION_EXCEPTION_EVENT,
            "sample_approved_date_invalid",
            matches,
        )
    if not dated and creator_id not in snapshot.valid_creator_ids:
        return _decision(
            candidate, COOPERATION_ALLOWED_EVENT, "no_completed_collaboration", matches
        )
    if dated:
        recent_start = today - timedelta(days=2)
        recent = tuple(
            (row, approved)
            for row, approved in dated
            if recent_start <= approved <= today
        )
        if not recent and creator_id not in snapshot.valid_creator_ids:
            return _decision(
                candidate,
                COOPERATION_ALLOWED_EVENT,
                "registered_before_recent_window",
                matches,
            )
        selected = recent or tuple(dated)
        selected_rows = tuple(row for row, _approved in selected)
        event_type = (
            COOPERATION_RECENT_EVENT if recent else COOPERATION_ACTIVE_CREATOR_EVENT
        )
        reason = (
            "recent_registration" if recent else "active_creator_after_recent_window"
        )
        recent_date = max(approved for _row, approved in selected)
    else:
        selected_rows = matches
        event_type = COOPERATION_ACTIVE_CREATOR_EVENT
        reason = "active_creator_without_approved_date"
        recent_date = None
    recipients: dict[str, CooperationRecipient] = {}
    unresolved = False
    for row in selected_rows:
        owners = split_bd_owners(row.bd_owner)
        if not owners:
            unresolved = True
        for owner in owners:
            if not is_current_bd_owner(owner, current_bd_names):
                continue
            recipient = resolve_bd_recipient(owner, snapshot.recipients)
            if recipient is None:
                unresolved = True
            else:
                recipients[recipient.open_id] = recipient
    if not unresolved and (daily_issue := reconcile_daily_recipients(candidate, snapshot, recipients)):
        return daily_issue
    return _decision(
        candidate,
        COOPERATION_EXCEPTION_EVENT if unresolved else event_type,
        "bd_recipient_unresolved" if unresolved else reason,
        matches,
        recent_date=recent_date,
        recipients=tuple(sorted(recipients.values(), key=lambda item: item.name)),
    )
def resolve_bd_recipient(
    owner: Any,
    recipients: dict[str, CooperationRecipient],
) -> CooperationRecipient | None:
    normalized = normalize_bd_name(owner)
    if not normalized:
        return None
    exact = recipients.get(normalized)
    if exact is not None:
        return exact
    if len(normalized) < 2:
        return None
    matches = {
        recipient.open_id: recipient
        for roster_name, recipient in recipients.items()
        if normalized in roster_name or roster_name in normalized
    }
    return next(iter(matches.values())) if len(matches) == 1 else None
def _assignment_owner_decision(
    candidate: CooperationCandidate,
    snapshot: CooperationSnapshot,
    owner: CreatorAssignmentOwner,
    *,
    now: datetime,
) -> CooperationDecision | None:
    reason = assignment_owner_protection_reason(
        owner,
        valid_creator_ids=snapshot.valid_creator_ids,
        ai_invitation_creator_ids=snapshot.ai_invitation_creator_ids,
        now=now,
    )
    if reason is None:
        return None
    if reason in {"assignment_owner_time_missing", "assignment_owner_ambiguous"}:
        return CooperationDecision(
            candidate,
            COOPERATION_EXCEPTION_EVENT,
            reason,
            owner_bd_name=owner.bd_name,
            owner_assigned_at=owner.assigned_at,
        )
    recipient = resolve_bd_recipient(owner.bd_name, snapshot.recipients)
    if recipient is None:
        return CooperationDecision(
            candidate,
            COOPERATION_EXCEPTION_EVENT,
            "assignment_owner_bd_unresolved",
            owner_bd_name=owner.bd_name,
            owner_assigned_at=owner.assigned_at,
        )
    return CooperationDecision(
        candidate,
        COOPERATION_OWNER_PROTECTED_EVENT,
        reason,
        matched_count=1,
        sources=("达人分配表",),
        recipients=(recipient,),
        owner_bd_name=owner.bd_name,
        owner_assigned_at=owner.assigned_at,
    )



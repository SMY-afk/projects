from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from erp_api.services.sample_cooperation_parsing import CHINA_TIMEZONE
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ACTIVE_CREATOR_EVENT,
    COOPERATION_BD_INVITATION_EVENT,
    COOPERATION_OWNER_PROTECTED_EVENT,
    COOPERATION_RECENT_EVENT,
    CooperationDecision,
    CooperationRecipient,
)


@dataclass(frozen=True)
class StoredCooperationAction:
    application_id: UUID
    shop_id: UUID
    platform_application_id: str
    creator_id: str | None
    shop_name: str
    applied_at: datetime | None
    feishu_record_id: str
    event_type: str
    reason: str
    matched_count: int
    recent_date: date | None
    sources: tuple[str, ...]
    recipients: tuple[CooperationRecipient, ...]
    owner_bd_name: str | None
    owner_assigned_at: datetime | None


def decision_payload(decision: CooperationDecision) -> dict[str, object]:
    return {
        "reason": decision.reason,
        "creator_id": decision.candidate.creator_id,
        "platform_application_id": decision.candidate.platform_application_id,
        "shop_name": decision.candidate.shop_name,
        "applied_at": (
            decision.candidate.applied_at.isoformat()
            if decision.candidate.applied_at is not None
            else None
        ),
        "matched_count": decision.matched_count,
        "recent_date": decision.recent_date.isoformat()
        if decision.recent_date
        else None,
        "sources": list(decision.sources),
        "recipients": [
            {"name": item.name, "open_id": item.open_id} for item in decision.recipients
        ],
        "protected_bd_name": decision.protected_bd_name,
        "protected_until": (
            decision.protected_until.isoformat()
            if decision.protected_until is not None
            else None
        ),
        "owner_bd_name": decision.owner_bd_name,
        "owner_assigned_at": (
            decision.owner_assigned_at.isoformat()
            if decision.owner_assigned_at is not None
            else None
        ),
    }


def stored_action(event, application, workflow, shop_name) -> StoredCooperationAction:
    payload = event.after_data if isinstance(event.after_data, dict) else {}
    recipients = tuple(
        CooperationRecipient(item["name"], item["open_id"])
        for item in payload.get("recipients", [])
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("open_id"), str)
    )
    recent_text = payload.get("recent_date")
    applied_text = payload.get("applied_at")
    creator_id = payload.get("creator_id")
    owner_assigned_text = payload.get("owner_assigned_at")
    owner_bd_name = payload.get("owner_bd_name")
    return StoredCooperationAction(
        application_id=application.id,
        shop_id=application.shop_id,
        platform_application_id=application.platform_application_id,
        creator_id=creator_id if isinstance(creator_id, str) else None,
        shop_name=shop_name,
        applied_at=(
            datetime.fromisoformat(applied_text)
            if isinstance(applied_text, str)
            else None
        ),
        feishu_record_id=workflow.feishu_record_id,
        event_type=event.event_type,
        reason=str(payload.get("reason") or "precheck_invalid"),
        matched_count=int(payload.get("matched_count") or 0),
        recent_date=(
            date.fromisoformat(recent_text) if isinstance(recent_text, str) else None
        ),
        sources=tuple(
            item for item in payload.get("sources", []) if isinstance(item, str)
        ),
        recipients=recipients,
        owner_bd_name=(owner_bd_name if isinstance(owner_bd_name, str) else None),
        owner_assigned_at=(
            datetime.fromisoformat(owner_assigned_text)
            if isinstance(owner_assigned_text, str)
            else None
        ),
    )


def processing_result(event_type: str) -> str:
    if event_type == COOPERATION_BD_INVITATION_EVENT:
        return "BD自主邀约保护中，不进入分配记录"
    if event_type == COOPERATION_RECENT_EVENT:
        return "近三天已有样品登记，不进入分配记录"
    if event_type == COOPERATION_ACTIVE_CREATOR_EVENT:
        return "达人仍在每日有效达人表，不重新分配BD"
    if event_type == COOPERATION_OWNER_PROTECTED_EVENT:
        return "已有7天BD归属，不重新分配BD"
    return "前置检查异常，不进入分配记录"


def business_note(decision: CooperationDecision) -> str:
    details = [f"前置检查原因：{decision.reason}"]
    if decision.recent_date:
        details.append(f"最近同意样品日期：{decision.recent_date.isoformat()}")
    if decision.sources:
        details.append(f"登记来源：{'、'.join(decision.sources)}")
    if decision.protected_bd_name:
        details.append(f"保护BD：{decision.protected_bd_name}")
    if decision.protected_until:
        details.append(
            "保护名单到期："
            f"{decision.protected_until.astimezone(CHINA_TIMEZONE).isoformat()}"
        )
    if decision.owner_bd_name:
        details.append(f"原分配BD：{decision.owner_bd_name}")
    if decision.owner_assigned_at:
        details.append(
            "原分配时间："
            f"{decision.owner_assigned_at.astimezone(CHINA_TIMEZONE).isoformat()}"
        )
    return "；".join(details)

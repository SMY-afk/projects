from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from erp_api.services.sample_cooperation_parsing import (
    CHINA_TIMEZONE,
    normalize_account_name,
)
from erp_api.services.sample_cooperation_repository import StoredCooperationAction
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ACTIVE_CREATOR_EVENT,
    COOPERATION_EXCEPTION_EVENT,
    COOPERATION_OWNER_PROTECTED_EVENT,
    decide_cooperation,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SampleCooperationPrecheckResult:
    evaluated_count: int
    recorded_count: int


@dataclass(frozen=True)
class SampleCooperationActionResult:
    completed_count: int
    failed_count: int


class SampleCooperationPrecheckService:
    def __init__(
        self,
        repository,
        reader,
        notifications,
        record_clients,
        *,
        exception_chat_id: str | None,
        delivery_enabled: bool = True,
        assignment_ownership=None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._reader = reader
        self._notifications = notifications
        self._record_clients = record_clients
        self._exception_chat_id = exception_chat_id
        self._delivery_enabled = delivery_enabled
        self._assignment_ownership = assignment_ownership
        self._clock = clock

    async def has_pending(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        application_ids: frozenset[UUID] | None,
    ) -> bool:
        candidates = await self._repository.list_candidates(
            tenant_id,
            shop_id,
            application_ids=application_ids,
        )
        if candidates:
            return True
        return bool(await self._repository.list_due_actions(tenant_id, shop_id))

    async def evaluate(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        application_ids: frozenset[UUID] | None,
    ) -> SampleCooperationPrecheckResult:
        candidates = await self._repository.list_candidates(
            tenant_id,
            shop_id,
            application_ids=application_ids,
        )
        if not candidates:
            return SampleCooperationPrecheckResult(0, 0)
        creator_ids = frozenset(
            creator_id
            for candidate in candidates
            if (creator_id := normalize_account_name(candidate.creator_id))
        )
        snapshot_task = self._reader.read(creator_ids=creator_ids)
        ownership_task = (
            self._assignment_ownership.read(tenant_id, creator_ids)
            if self._assignment_ownership is not None
            else _empty_ownership()
        )
        snapshot, assignment_owners = await asyncio.gather(
            snapshot_task,
            ownership_task,
        )
        snapshot = replace(snapshot, assignment_owners=assignment_owners)
        now = self._clock()
        today = now.astimezone(CHINA_TIMEZONE).date()
        decisions = tuple(
            decide_cooperation(candidate, snapshot, today=today, now=now)
            for candidate in candidates
        )
        recorded = await self._repository.record_decisions(decisions)
        return SampleCooperationPrecheckResult(len(decisions), recorded)

    async def complete_due(
        self, tenant_id: UUID, shop_id: UUID
    ) -> SampleCooperationActionResult:
        actions = await self._repository.list_due_actions(tenant_id, shop_id)
        completed = 0
        failed = 0
        for action in actions:
            try:
                message_ids = await self._complete_action(action)
                await self._repository.complete_action(action, message_ids=message_ids)
                completed += 1
            except Exception as error:  # noqa: BLE001 -- durable event stays pending
                failed += 1
                logger.warning(
                    "sample_cooperation_action_failed",
                    extra={
                        "shop_id": str(shop_id),
                        "application_id": str(action.application_id),
                        "error_type": type(error).__name__,
                        "error_code": getattr(error, "error_code", None),
                    },
                )
        return SampleCooperationActionResult(completed, failed)

    async def _complete_action(
        self, action: StoredCooperationAction
    ) -> tuple[str, ...]:
        recipients = []
        for recipient in action.recipients:
            if (
                action.event_type == COOPERATION_OWNER_PROTECTED_EVENT
                and action.owner_bd_name != recipient.name
            ):
                raise RuntimeError("Protected BD recipient does not match owner.")
            current = await self._reader.resolve_current_recipient(recipient)
            if current is None:
                raise RuntimeError("Cooperation recipient is missing or ambiguous.")
            recipients.append(current)
        client = (
            self._record_clients.for_shop(action.shop_id)
            if hasattr(self._record_clients, "for_shop")
            else self._record_clients
        )
        await client.update_business_fields(
            action.feishu_record_id,
            {
                "处理结果": _processing_result(action),
                "备注": _business_note(action),
            },
        )
        if not self._delivery_enabled:
            raise RuntimeError("Sample cooperation notification delivery is disabled.")
        message_ids = []
        for recipient in recipients:
            message_ids.append(
                await self._notifications.send_text(
                    recipient_open_id=recipient.open_id,
                    text=_direct_message(action),
                    idempotency_key=_delivery_key(action, recipient.open_id),
                )
            )
        if action.event_type == COOPERATION_EXCEPTION_EVENT:
            if not self._exception_chat_id:
                raise RuntimeError("Sample cooperation exception chat is unavailable.")
            message_ids.append(
                await self._notifications.send_text_to_chat(
                    chat_id=self._exception_chat_id,
                    text=_exception_message(action),
                    idempotency_key=_delivery_key(action, self._exception_chat_id),
                )
            )
        return tuple(message_ids)


def _processing_result(action: StoredCooperationAction) -> str:
    if action.event_type == COOPERATION_EXCEPTION_EVENT:
        return "前置检查异常，不进入分配记录"
    if action.event_type == COOPERATION_ACTIVE_CREATOR_EVENT:
        return "达人仍在每日有效达人表，不重新分配BD"
    if action.event_type == COOPERATION_OWNER_PROTECTED_EVENT:
        return "本次申请仍由原分配BD跟进，未新增分配记录"
    return "近三天已有样品登记，不进入分配记录"


def _business_note(action: StoredCooperationAction) -> str:
    details = [f"前置检查原因：{action.reason}"]
    if action.recent_date:
        details.append(f"最近同意样品日期：{action.recent_date.isoformat()}")
    if action.sources:
        details.append(f"登记来源：{'、'.join(action.sources)}")
    if action.owner_bd_name:
        details.append(f"原分配BD：{action.owner_bd_name}")
    if action.owner_assigned_at:
        details.append(f"原分配时间：{_display_time(action.owner_assigned_at)}")
    return "；".join(details)


def _direct_message(action: StoredCooperationAction) -> str:
    if action.event_type == COOPERATION_OWNER_PROTECTED_EVENT:
        return "\n".join(
            (
                "【新样品申请提醒｜请原BD跟进】",
                "",
                f"达人ID：{action.creator_id or '缺失'}",
                f"本次申请店铺：{action.shop_name}",
                f"本次申请时间：{_display_time(action.applied_at)}",
                f"原分配BD：{action.owner_bd_name or '无法识别'}",
                f"原分配时间：{_display_time(action.owner_assigned_at)}",
                "处理结果：本次申请仍由您跟进，系统未新增分配记录。",
                "请查看并处理这次新样品申请。",
            )
        )
    active_creator = action.event_type == COOPERATION_ACTIVE_CREATOR_EVENT
    title = (
        "【达人仍有效｜不重新分配】"
        if active_creator
        else "【近3天已有样品登记｜不重新分配】"
    )
    result = (
        "达人仍在（每日更新）有效达人表，已保留原合作BD，不重新分配。"
        if active_creator
        else "近3天已有样品登记，已保留原合作BD，不重新分配。"
    )
    return "\n".join(
        (
            title,
            "",
            f"达人ID：{action.creator_id or '缺失'}",
            f"本次申请店铺：{action.shop_name}",
            f"本次申请时间：{_display_time(action.applied_at)}",
            f"最近同意样品日期：{action.recent_date or '无法识别'}",
            f"登记来源：{'、'.join(action.sources) or '未知'}",
            f"处理结果：{result}",
        )
    )


def _exception_message(action: StoredCooperationAction) -> str:
    return "\n".join(
        (
            "【样品分配前置检查异常】",
            "",
            f"达人ID：{action.creator_id or '缺失'}",
            f"申请店铺：{action.shop_name}",
            f"申请编号：{action.platform_application_id}",
            f"异常原因：{action.reason}",
            "处理结果：已写入我的样品表，已暂停分配，请人工检查。",
        )
    )


def _display_time(value: datetime | None) -> str:
    if value is None:
        return "缺失"
    localized = value.astimezone(CHINA_TIMEZONE) if value.tzinfo else value
    return localized.strftime("%Y-%m-%d %H:%M")


def _delivery_key(action: StoredCooperationAction, recipient: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"sample-cooperation:{action.application_id}:{recipient}",
        )
    )


async def _empty_ownership() -> dict:
    return {}

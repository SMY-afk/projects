"""Resolve daily collaboration ownership by matched shop and unique account."""

from dataclasses import replace

from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.services.sample_cooperation_parsing import (
    is_current_bd_owner,
    normalize_account_name,
    split_bd_owners,
)

DAILY_SOURCE = "（每日更新）有效达人"


def scoped_daily_rows(candidate, snapshot):
    creator = normalize_account_name(candidate.creator_id)
    matched_shop = next((shop.business_name for shop in TARGET_SHOPS
                 if candidate.shop_name in (shop.source_name, shop.business_name)), None)
    if candidate.shop_name in {"本土2", "本土2店"}:
        matched_shop = "本土店"
    rows = tuple(row for row in snapshot.daily_valid_rows
                 if normalize_account_name(row.account_name) == creator)
    known = tuple(row for row in rows if _shop_label(row.source))
    return tuple(row for row in rows
        if _shop_label(row.source) == matched_shop
        or (not known and not row.source)
        or (row.source and _shop_label(row.source) is None))


def _shop_label(value):
    label = str(value or "").strip()
    if label in {"本土2", "本土2店"}:
        return "本土店"
    return label if label in {shop.business_name for shop in TARGET_SHOPS} else None


def scope_daily_valid_creators(candidate, snapshot):
    if not snapshot.daily_valid_rows:
        return snapshot
    current = snapshot.current_bd_names
    valid = frozenset(normalize_account_name(row.account_name)
                      for row in scoped_daily_rows(candidate, snapshot)
                      if _shop_label(row.source) and any(is_current_bd_owner(owner, current)
                          for owner in split_bd_owners(row.bd_owner)))
    return replace(snapshot, valid_creator_ids=valid)


def daily_valid_decision(candidate, snapshot):
    from erp_api.services.sample_cooperation_rules import (
        COOPERATION_ACTIVE_CREATOR_EVENT,
        COOPERATION_ALLOWED_EVENT,
        COOPERATION_EXCEPTION_EVENT,
        CooperationDecision,
        resolve_bd_recipient,
    )

    rows = scoped_daily_rows(candidate, snapshot)
    if not rows:
        return None

    def result(event, reason, recipients=()):
        return CooperationDecision(candidate, event, reason, matched_count=len(rows),
            sources=(DAILY_SOURCE,), recipients=recipients,
            owner_bd_name=recipients[0].name if len(recipients) == 1 else None)

    if any(not row.source for row in rows):
        return result(COOPERATION_EXCEPTION_EVENT, "active_creator_shop_missing")
    if any(_shop_label(row.source) is None for row in rows):
        return result(COOPERATION_EXCEPTION_EVENT, "active_creator_shop_invalid")
    if any(not split_bd_owners(row.bd_owner) for row in rows):
        return result(COOPERATION_EXCEPTION_EVENT, "active_creator_bd_missing")
    owners = tuple(owner for row in rows for owner in split_bd_owners(row.bd_owner)
                   if is_current_bd_owner(owner, snapshot.current_bd_names))
    if not owners:
        return result(COOPERATION_ALLOWED_EVENT, "no_current_daily_bd_owner")
    resolved = [resolve_bd_recipient(owner, snapshot.recipients) for owner in owners]
    if any(recipient is None for recipient in resolved):
        return result(COOPERATION_EXCEPTION_EVENT, "active_creator_bd_unresolved")
    unique = {recipient.open_id: recipient for recipient in resolved}
    if len(unique) != 1:
        return result(COOPERATION_EXCEPTION_EVENT, "active_creator_bd_ambiguous")
    return result(COOPERATION_ACTIVE_CREATOR_EVENT, "active_creator_daily_bd_verified",
                  tuple(unique.values()))


def reconcile_daily_recipients(candidate, snapshot, recipients):
    from erp_api.services.sample_cooperation_rules import (
        COOPERATION_ACTIVE_CREATOR_EVENT,
        COOPERATION_EXCEPTION_EVENT,
    )
    daily = daily_valid_decision(candidate, snapshot)
    if daily is None:
        return None
    if daily.event_type == COOPERATION_EXCEPTION_EVENT:
        return daily
    if daily.event_type == COOPERATION_ACTIVE_CREATOR_EVENT and set(recipients) != {
        recipient.open_id for recipient in daily.recipients
    }:
        return replace(daily, event_type=COOPERATION_EXCEPTION_EVENT,
                       reason="active_creator_bd_conflict", recipients=())
    return None

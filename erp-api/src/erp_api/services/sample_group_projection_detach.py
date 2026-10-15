"""Retain source history while detaching links absent from the current RAW group."""

from erp_api.models.sample_application_event import SampleApplicationEvent


def detach_obsolete_group_links(
    rows, projection, session, *, tenant_id, shop_id, observed_at
):
    changed = set()
    parent_id = projection["parent_application_id"]
    current_ids = set(projection["source_item_ids"])
    for member in rows:
        raw = dict(member.raw_payload or {})
        previous = raw.get("ziniao_group_projection")
        if member.platform_application_id in current_ids or not isinstance(
            previous, dict
        ):
            continue
        if previous.get("parent_application_id") != parent_id:
            continue
        raw.pop("ziniao_group_projection")
        member.raw_payload = raw
        member.is_current_projection = False
        changed.add(member.id)
        session.add(
            SampleApplicationEvent(
                tenant_id=tenant_id,
                shop_id=shop_id,
                sample_application_id=member.id,
                event_type="sample_group_projection_detached",
                event_source="tiktok_ziniao_cdp",
                before_data=previous,
                after_data={
                    "reason": "absent_from_current_raw_group",
                    "source_history_retained": True,
                },
                occurred_at=observed_at,
            )
        )
    return changed

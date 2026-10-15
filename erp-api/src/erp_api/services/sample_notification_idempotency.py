from uuid import NAMESPACE_URL, uuid5


def notification_delivery_key(task, *, channel: str, target_id: str) -> str:
    source_event_id = task.payload.get("source_event_id")
    logical_event = (
        source_event_id.strip()
        if isinstance(source_event_id, str) and source_event_id.strip()
        else str(task.id)
    )
    return str(
        uuid5(
            NAMESPACE_URL,
            f"sample-notification:{logical_event}:{channel}:{target_id}",
        )
    )

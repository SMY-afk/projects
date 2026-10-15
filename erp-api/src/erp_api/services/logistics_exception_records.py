def exception_action_record(action) -> dict[str, object]:
    return {
        "id": action.id,
        "actionType": action.action_type,
        "actorUserId": action.actor_user_id,
        "fromStatus": action.from_status,
        "toStatus": action.to_status,
        "note": action.note,
        "details": action.details,
        "createdAt": action.created_at,
    }


def exception_record(exception, task, carrier, waybill) -> dict[str, object]:
    return {
        "id": exception.id,
        "exceptionNumber": exception.exception_number,
        "waybillId": exception.waybill_id,
        "packageId": exception.package_id,
        "taskId": exception.task_id,
        "taskNumber": task.task_number,
        "sourceNumber": task.source_number,
        "carrierName": carrier.name,
        "trackingNumberMasked": waybill.tracking_number_masked,
        "exceptionType": exception.exception_type,
        "status": exception.status,
        "severity": exception.severity,
        "source": exception.source,
        "title": exception.title,
        "description": exception.description,
        "assignedToUserId": exception.assigned_to_user_id,
        "resolution": exception.resolution,
        "firstDetectedAt": exception.first_detected_at,
        "lastDetectedAt": exception.last_detected_at,
        "occurrenceCount": exception.occurrence_count,
        "resolvedAt": exception.resolved_at,
        "closedAt": exception.closed_at,
        "updatedAt": exception.updated_at,
        "versionId": exception.version_id,
        "actions": [exception_action_record(item) for item in exception.actions],
    }

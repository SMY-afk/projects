from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_item import LogisticsTaskItem
from erp_api.models.logistics_task_operation import LogisticsTaskOperation
from erp_api.models.logistics_task_review import LogisticsTaskReview


def task_record(task: LogisticsTask) -> dict[str, object]:
    return {
        "id": task.id,
        "taskNumber": task.task_number,
        "sourceType": task.source_type,
        "direction": task.direction,
        "sourceId": task.source_reference_id,
        "sourceNumber": task.source_number,
        "orderId": task.order_id,
        "rmaId": task.return_rma_id,
        "shopId": task.shop_id,
        "priority": task.priority,
        "status": task.status,
        "note": task.note,
        "createdByUserId": task.created_by_user_id,
        "createdAt": task.created_at,
        "updatedAt": task.updated_at,
        "versionId": task.version_id,
        "items": [_item_record(item) for item in task.items],
        "operations": [_operation_record(item) for item in task.operations],
        "reviews": [_review_record(item) for item in task.reviews],
    }


def _item_record(item: LogisticsTaskItem) -> dict[str, object]:
    return {
        "id": item.id,
        "sourceLineId": item.source_line_id,
        "orderLineId": item.order_line_id,
        "platformProductId": item.platform_product_id,
        "platformSkuId": item.platform_sku_id,
        "sellerSku": item.seller_sku,
        "productName": item.product_name,
        "skuName": item.sku_name,
        "plannedQuantity": item.planned_quantity,
        "packedQuantity": item.packed_quantity,
        "shippedQuantity": item.shipped_quantity,
    }


def _operation_record(item: LogisticsTaskOperation) -> dict[str, object]:
    return {
        "id": item.id,
        "operationType": item.operation_type,
        "fromStatus": item.from_status,
        "toStatus": item.to_status,
        "actorUserId": item.actor_user_id,
        "note": item.note,
        "details": item.details,
        "createdAt": item.created_at,
    }


def _review_record(item: LogisticsTaskReview) -> dict[str, object]:
    return {
        "id": item.id,
        "result": item.result,
        "expectedQuantity": item.expected_quantity,
        "actualQuantity": item.actual_quantity,
        "differences": item.differences,
        "note": item.note,
        "reviewerUserId": item.reviewer_user_id,
        "reviewedAt": item.reviewed_at,
    }

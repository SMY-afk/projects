from erp_api.models.return_request import ReturnRequest, ReturnRequestItem


def return_request_record(request: ReturnRequest) -> dict[str, object]:
    rma = request.rma
    return {
        "id": request.id,
        "requestNumber": request.request_number,
        "orderId": request.order_id,
        "orderNumber": request.order.order_number,
        "shopId": request.shop_id,
        "source": request.source,
        "platform": request.platform,
        "platformReturnId": request.platform_return_id,
        "platformStatus": request.platform_status,
        "platformReasonText": request.platform_reason_text,
        "platformCreatedAt": request.platform_created_at,
        "platformUpdatedAt": request.platform_updated_at,
        "refundCurrency": request.refund_currency,
        "refundAmountMinor": request.refund_amount_minor,
        "requestType": request.request_type,
        "status": request.status,
        "reasonCode": request.reason_code,
        "customerNote": request.customer_note,
        "createdByUserId": request.created_by_user_id,
        "reviewedByUserId": request.reviewed_by_user_id,
        "reviewNote": request.review_note,
        "reviewedAt": request.reviewed_at,
        "createdAt": request.created_at,
        "updatedAt": request.updated_at,
        "versionId": request.version_id,
        "items": [_item_record(item) for item in request.items],
        "rma": (
            {
                "id": rma.id,
                "rmaNumber": rma.rma_number,
                "status": rma.status,
                "reverseTaskId": rma.reverse_task.id if rma.reverse_task else None,
                "generatedAt": rma.generated_at,
            }
            if rma
            else None
        ),
    }


def _item_record(item: ReturnRequestItem) -> dict[str, object]:
    line = item.order_line
    return {
        "id": item.id,
        "orderLineId": item.order_line_id,
        "platformReturnLineId": item.platform_return_line_id,
        "sellerSku": line.seller_sku,
        "productName": line.product_name,
        "skuName": line.sku_name,
        "requestedQuantity": item.requested_quantity,
        "reasonCode": item.reason_code,
        "note": item.note,
    }

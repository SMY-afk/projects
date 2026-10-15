from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, status

from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_event_processor import (
    FeishuSampleEventProcessingError,
    FeishuSampleEventProcessor,
)
from erp_api.services.feishu_sample_event_receiver import (
    FeishuEventAuthenticationError,
    FeishuEventPayloadError,
    FeishuSampleEventReceiver,
)

MAX_FEISHU_EVENT_BYTES = 256 * 1024

router = APIRouter(
    prefix="/webhooks/feishu/sample-applications",
    tags=["feishu-sample-events"],
)


def _receiver(request: Request) -> FeishuSampleEventReceiver:
    receiver = getattr(request.app.state, "feishu_sample_event_receiver", None)
    if receiver is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return receiver


def _processor(request: Request) -> FeishuSampleEventProcessor:
    processor = getattr(request.app.state, "feishu_sample_event_processor", None)
    if processor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "60"},
        )
    return processor


@router.post("")
async def receive_feishu_sample_event(request: Request) -> dict[str, object]:
    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdecimal()
        and int(content_length) > MAX_FEISHU_EVENT_BYTES
    ):
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    body = await request.body()
    if len(body) > MAX_FEISHU_EVENT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    receiver = _receiver(request)
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from error
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feishu callback payload must be an object.",
        )
    if payload.get("type") != "url_verification":
        try:
            receiver.verify_request(
                body,
                timestamp=request.headers.get("X-Lark-Request-Timestamp"),
                nonce=request.headers.get("X-Lark-Request-Nonce"),
                signature=request.headers.get("X-Lark-Signature"),
            )
        except FeishuEventAuthenticationError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)
            ) from error
    try:
        receipt = receiver.receive(payload)
    except FeishuEventAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)
        ) from error
    except FeishuEventPayloadError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    if receipt.kind == "challenge":
        return {"challenge": receipt.challenge or ""}
    try:
        result = await _processor(request).process(receipt)
    except FeishuEventPayloadError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    except LookupError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feishu record is not mapped to a workflow.",
        ) from error
    except (FeishuSampleError, FeishuSampleEventProcessingError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Feishu event processing failed.",
            headers={"Retry-After": "60"},
        ) from error
    return {
        "code": 0,
        "applied": result.applied_count,
        "duplicate": result.duplicate_count,
        "unchanged": result.unchanged_count,
        "ignored": result.ignored_count,
    }

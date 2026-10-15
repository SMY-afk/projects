from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

_PROFILE_PATH = "/api/v1/oec/affiliate/creator/marketplace/profile"
_REQUEST_ID_HEADERS = ("request-id", "x-request-id", "x-tt-logid", "x-tt-trace-id")


@dataclass(frozen=True)
class CapturedSummaryResponse:
    url: str
    request_body: Mapping[str, object]
    payload: Mapping[str, object]
    request_id: str
    observed_at: datetime


class CreatorSummaryPerformanceBuffer:
    def __init__(self) -> None:
        self._requests: dict[str, Mapping[str, object]] = {}
        self._responses: dict[str, Mapping[str, object]] = {}

    def consume(
        self,
        entries: Sequence[Mapping[str, object]],
        get_body: Callable[[str], Mapping[str, object]],
        *,
        observed_at: datetime,
    ) -> list[CapturedSummaryResponse]:
        completed = []
        for entry in entries:
            message = _message(entry)
            method = message.get("method")
            params = message.get("params")
            if not isinstance(params, Mapping):
                continue
            request_id = params.get("requestId")
            if not isinstance(request_id, str):
                continue
            if method == "Network.requestWillBeSent":
                request = params.get("request")
                if _is_summary_request(request):
                    self._requests[request_id] = request
            elif method == "Network.responseReceived" and request_id in self._requests:
                response = params.get("response")
                if isinstance(response, Mapping) and response.get("status") == 200:
                    self._responses[request_id] = response
            elif method == "Network.loadingFinished" and request_id in self._responses:
                completed.append(
                    self._complete(request_id, get_body(request_id), observed_at)
                )
        return completed

    def _complete(
        self,
        request_id: str,
        body: Mapping[str, object],
        observed_at: datetime,
    ) -> CapturedSummaryResponse:
        request = self._requests.pop(request_id)
        response = self._responses.pop(request_id)
        request_body = _json_mapping(request.get("postData"))
        payload = _response_payload(body)
        external_id = _request_id(response.get("headers"))
        if not external_id:
            raise ValueError("Creator details response request ID is missing.")
        return CapturedSummaryResponse(
            url=str(response.get("url") or ""),
            request_body=request_body,
            payload=payload,
            request_id=external_id,
            observed_at=observed_at,
        )


def captured_profile_types(responses: Sequence[CapturedSummaryResponse]) -> set[int]:
    return {
        value for response in responses for value in response_profile_types(response)
    }


def response_profile_types(response: CapturedSummaryResponse) -> set[int]:
    values = response.request_body.get("profile_types")
    return (
        {value for value in values if isinstance(value, int)}
        if isinstance(values, list)
        else set()
    )


def _message(entry: Mapping[str, object]) -> Mapping[str, object]:
    raw = entry.get("message")
    if not isinstance(raw, str):
        return {}
    outer = json.loads(raw)
    message = outer.get("message")
    return message if isinstance(message, Mapping) else {}


def _is_summary_request(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("method") == "POST"
        and urlsplit(str(value.get("url") or "")).path == _PROFILE_PATH
    )


def _json_mapping(value: object) -> Mapping[str, object]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, Mapping):
        raise TypeError("Creator details JSON object is unavailable.")
    return parsed


def _response_payload(body: Mapping[str, object]) -> Mapping[str, object]:
    value = body.get("body")
    if not isinstance(value, str):
        raise TypeError("Creator details response body is unavailable.")
    if body.get("base64Encoded") is True:
        value = base64.b64decode(value).decode("utf-8")
    return _json_mapping(value)


def _request_id(headers: object) -> str | None:
    normalized = (
        {str(key).casefold(): str(value) for key, value in headers.items()}
        if isinstance(headers, Mapping)
        else {}
    )
    return next(
        (
            normalized[name][:128]
            for name in _REQUEST_ID_HEADERS
            if normalized.get(name)
        ),
        None,
    )

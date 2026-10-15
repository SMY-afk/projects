from __future__ import annotations

import base64
import json
import time
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlsplit

import websocket

from erp_api.services.hubstudio_sample_response_parser import (
    parse_hubstudio_sample_response,
)
from erp_api.services.tiktok_sample_application_payload import (
    TikTokSampleApplicationPage,
)

SAMPLE_REQUEST_PATH = "/affiliate/sample/sample-request"
SAMPLE_GROUP_LIST_PATH = "/api/v1/affiliate/sample/group/list"
ALLOWED_HOSTS = {
    "affiliate-us.tiktok.com",
    "affiliate.tiktokshopglobalselling.com",
}
_CLICK_VISIBLE_TEXT_SCRIPT = r"""
const labels = arguments[0];
const selector = arguments[1];
const prefix = arguments[2];
const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
const visible = element => { const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden';
};
const candidates = Array.from(document.querySelectorAll(selector)).filter(visible).filter(element => {
    const text = normalize(element.innerText || element.textContent);
    return labels.some(label => prefix ? text.startsWith(label) : text === label);
}).sort((left, right) => normalize(left.innerText).length - normalize(right.innerText).length);
if (!candidates.length) return false;
candidates[0].click();
return true;
"""


@dataclass(frozen=True)
class ZiniaoSampleListCapture:
    page: TikTokSampleApplicationPage
    observed_request_id: str


def activate_responsive_sample_page(debugging_port: int, platform_shop_id: str) -> str:
    if not 1 <= debugging_port <= 65_535 or not platform_shop_id.strip():
        raise ValueError("Ziniao sample page activation target is invalid.")
    candidates = [
        target
        for target in _cdp_page_targets(debugging_port)
        if _is_matching_sample_target(target, platform_shop_id)
    ]
    responsive = [target for target in candidates if _page_ready(target)]
    if responsive:
        responsive_ids = {str(target["id"]) for target in responsive}
        for target in candidates:
            target_id = str(target["id"])
            if target_id not in responsive_ids:
                _close_target(debugging_port, target_id)
        selected_id = str(responsive[0]["id"])
        _activate_target(debugging_port, selected_id)
        return selected_id
    raise RuntimeError("No responsive Akeleo Toys sample page was found.")


def capture_ziniao_sample_list(
    driver, platform_shop_id: str, *, timeout_seconds: float = 30
) -> ZiniaoSampleListCapture:
    if timeout_seconds <= 0:
        raise ValueError("Sample list capture timeout must be positive.")
    _validate_page(driver.current_url, platform_shop_id)
    driver.execute_cdp_cmd("Network.enable", {})
    driver.get_log("performance")
    driver.execute_cdp_cmd("Page.reload", {"ignoreCache": True})
    _prepare_review_request_date(driver, timeout_seconds=min(timeout_seconds, 10))
    deadline = time.monotonic() + timeout_seconds
    requests: dict[str, str | None] = {}
    responses: set[str] = set()
    finished: set[str] = set()
    while time.monotonic() < deadline:
        for entry in driver.get_log("performance"):
            _consume_entry(entry, requests, responses, finished)
        for request_id in responses & finished:
            body = requests.get(request_id)
            if not _is_review_request_date(body):
                responses.discard(request_id)
                continue
            try:
                response = driver.execute_cdp_cmd(
                    "Network.getResponseBody", {"requestId": request_id}
                )
                payload = _response_payload(response)
                page = parse_hubstudio_sample_response(
                    payload,
                    platform_request_id=request_id,
                    observed_at=datetime.now(UTC),
                )
            except Exception:  # noqa: BLE001 -- another response may still complete
                responses.discard(request_id)
                continue
            _validate_page(driver.current_url, platform_shop_id)
            return ZiniaoSampleListCapture(page, request_id)
        time.sleep(0.1)
    raise TimeoutError("TikTok sample list response was not captured.")


def _cdp_page_targets(debugging_port: int) -> list[dict[str, object]]:
    url = f"http://127.0.0.1:{debugging_port}/json/list"
    with urllib.request.urlopen(url, timeout=3) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise TypeError("Ziniao CDP target list is invalid.")
    return [dict(item) for item in payload if isinstance(item, Mapping)]


def _is_matching_sample_target(
    target: Mapping[str, object], platform_shop_id: str
) -> bool:
    url = target.get("url")
    split = urlsplit(url) if isinstance(url, str) else None
    return bool(
        target.get("type") == "page"
        and split is not None
        and split.hostname in ALLOWED_HOSTS
        and split.path == SAMPLE_REQUEST_PATH
        and parse_qs(split.query).get("shop_id") == [platform_shop_id]
        and isinstance(target.get("id"), str)
        and target.get("id")
    )


def _page_ready(target: Mapping[str, object]) -> bool:
    websocket_url = target.get("webSocketDebuggerUrl")
    split = urlsplit(websocket_url) if isinstance(websocket_url, str) else None
    if (
        split is None
        or split.scheme != "ws"
        or split.hostname not in {"127.0.0.1", "localhost"}
    ):
        return False
    connection = None
    try:
        connection = websocket.create_connection(
            websocket_url,
            timeout=2,
            suppress_origin=True,
        )
        connection.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": "document.readyState",
                        "returnByValue": True,
                    },
                }
            )
        )
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            reply = json.loads(connection.recv())
            if reply.get("id") != 1:
                continue
            value = reply.get("result", {}).get("result", {}).get("value")
            return value in {"interactive", "complete"}
    except Exception:  # noqa: BLE001 -- one duplicate page may be unresponsive
        return False
    finally:
        if connection is not None:
            connection.close()
    return False


def _activate_target(debugging_port: int, target_id: str) -> None:
    target = quote(target_id, safe="")
    url = f"http://127.0.0.1:{debugging_port}/json/activate/{target}"
    with urllib.request.urlopen(url, timeout=3):
        pass


def _close_target(debugging_port: int, target_id: str) -> None:
    target = quote(target_id, safe="")
    url = f"http://127.0.0.1:{debugging_port}/json/close/{target}"
    with urllib.request.urlopen(url, timeout=3):
        pass


def _consume_entry(entry, requests, responses, finished) -> None:
    try:
        message = json.loads(entry["message"])["message"]
        method = message["method"]
        params = message["params"]
        request_id = params["requestId"]
    except (KeyError, TypeError, ValueError):
        return
    if method == "Network.requestWillBeSent":
        request = params.get("request", {})
        if _is_sample_url(request.get("url")) and request.get("method") == "POST":
            requests[request_id] = request.get("postData")
    elif method == "Network.responseReceived":
        response = params.get("response", {})
        if (
            _is_sample_url(response.get("url"))
            and response.get("status") == 200
            and str(response.get("mimeType", ""))
            .casefold()
            .startswith("application/json")
        ):
            responses.add(request_id)
    elif method == "Network.loadingFinished":
        finished.add(request_id)


def _is_sample_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    split = urlsplit(value)
    return split.hostname in ALLOWED_HOSTS and split.path == SAMPLE_GROUP_LIST_PATH


def _is_review_request_date(value: str | None) -> bool:
    try:
        payload = json.loads(value or "")
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, Mapping) or payload.get("tab") != 10:
        return False
    search = payload.get("search_params", [])
    return (
        payload.get("order_params") == []
        and isinstance(search, list)
        and all(
            isinstance(item, Mapping) and item.get("value") in (None, "")
            for item in search
        )
    )


def _prepare_review_request_date(driver, *, timeout_seconds: float) -> None:
    _click_visible_text(
        driver,
        ["To review"],
        '[role="tab"],button,[class*="tab"]',
        prefix=True,
        timeout_seconds=timeout_seconds,
    )
    _click_visible_text(
        driver,
        ["Relevancy"],
        '[role="combobox"],button,[aria-haspopup="listbox"],[class*="select"]',
        prefix=False,
        timeout_seconds=timeout_seconds,
    )
    _click_visible_text(
        driver,
        ["Request date"],
        '[role="option"],li,[class*="option"],[class*="menu"]',
        prefix=False,
        timeout_seconds=timeout_seconds,
    )


def _click_visible_text(
    driver,
    labels: list[str],
    selector: str,
    *,
    prefix: bool,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if driver.execute_script(_CLICK_VISIBLE_TEXT_SCRIPT, labels, selector, prefix):
            return
        time.sleep(0.1)
    raise RuntimeError(f"sample_page_control_unavailable:{labels[0]}")


def _response_payload(response: object) -> object:
    if not isinstance(response, Mapping) or not isinstance(response.get("body"), str):
        raise TypeError("Sample response body is unavailable.")
    body = response["body"]
    if response.get("base64Encoded") is True:
        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body)


def _validate_page(url: str, platform_shop_id: str) -> None:
    split = urlsplit(url)
    if (
        split.hostname not in ALLOWED_HOSTS
        or split.path != SAMPLE_REQUEST_PATH
        or parse_qs(split.query).get("shop_id") != [platform_shop_id]
    ):
        raise RuntimeError("Ziniao sample page identity does not match.")

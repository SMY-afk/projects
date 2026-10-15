from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


class ZiniaoWebDriverError(RuntimeError):
    def __init__(self, status_code: str, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Ziniao WebDriver {status_code}: {_safe_message(message)}")


@dataclass(frozen=True)
class ZiniaoCredentials:
    company: str
    username: str
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        if not all(
            value.strip() for value in (self.company, self.username, self.password)
        ):
            raise ValueError("Ziniao WebDriver credentials must be complete.")


@dataclass(frozen=True)
class ZiniaoBrowser:
    oauth: str = field(repr=False)
    name: str
    site_id: str | None
    platform_id: str | None
    platform_name: str | None


@dataclass(frozen=True)
class ZiniaoBrowserSession:
    debugging_port: int
    core_version: str
    core_type: str
    download_path: Path | None
    browser_path: Path | None = None

    @property
    def debugger_address(self) -> str:
        return f"127.0.0.1:{self.debugging_port}"

    @property
    def core_major_version(self) -> int:
        match = re.match(r"(\d+)", self.core_version)
        if match is None:
            raise ValueError("Ziniao browser core version is invalid.")
        return int(match.group(1))


class ZiniaoWebDriverClient:
    def __init__(
        self,
        base_url: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 120,
    ) -> None:
        self._endpoint = _loopback_endpoint(base_url)
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args) -> None:
        await self.aclose()

    async def list_browsers(
        self, credentials: ZiniaoCredentials
    ) -> tuple[ZiniaoBrowser, ...]:
        payload = await self._request("getBrowserList", credentials)
        browser_list = payload.get("browserList")
        if not isinstance(browser_list, list):
            raise ZiniaoWebDriverError("invalid_response", "Browser list is missing")
        browsers = []
        for item in browser_list:
            if not isinstance(item, Mapping):
                continue
            oauth = item.get("browserOauth")
            name = item.get("browserName")
            if not isinstance(oauth, str) or not oauth or not isinstance(name, str):
                continue
            browsers.append(
                ZiniaoBrowser(
                    oauth=oauth,
                    name=name,
                    site_id=_optional_text(item.get("siteId")),
                    platform_id=_optional_text(item.get("platform_id")),
                    platform_name=_optional_text(item.get("platform_name")),
                )
            )
        return tuple(browsers)

    async def start_browser(
        self,
        credentials: ZiniaoCredentials,
        *,
        browser_oauth: str,
    ) -> ZiniaoBrowserSession:
        if not browser_oauth.strip():
            raise ValueError("Ziniao browser OAuth identifier is required.")
        payload = await self._request(
            "startBrowser",
            credentials,
            browserOauth=browser_oauth,
            isHeadless=False,
            privacyMode=False,
            cookieTypeLoad=0,
            cookieTypeSave=0,
            notPromptForDownload=1,
            windowRatio=100,
        )
        port = _debugging_port(payload.get("debuggingPort"))
        core_version = _required_text(
            payload.get("core_version") or payload.get("coreVersion")
        )
        browser_path = _optional_text(payload.get("browserPath"))
        core_type = _browser_core_type(
            payload.get("core_type") or payload.get("coreType"),
            browser_path,
        )
        download_path = _optional_text(payload.get("downloadPath"))
        return ZiniaoBrowserSession(
            debugging_port=port,
            core_version=core_version,
            core_type=core_type,
            download_path=Path(download_path) if download_path else None,
            browser_path=Path(browser_path) if browser_path else None,
        )

    async def stop_browser(
        self,
        credentials: ZiniaoCredentials,
        *,
        browser_oauth: str,
    ) -> None:
        if not browser_oauth.strip():
            raise ValueError("Ziniao browser OAuth identifier is required.")
        await self._request(
            "stopBrowser",
            credentials,
            browserOauth=browser_oauth,
            isHeadless=False,
        )

    async def _request(
        self,
        action: str,
        credentials: ZiniaoCredentials,
        **values: object,
    ) -> Mapping[str, object]:
        request = {
            "company": credentials.company,
            "username": credentials.username,
            "password": credentials.password,
            "action": action,
            "requestId": str(uuid4()),
            **values,
        }
        try:
            response = await self._http.post(self._endpoint, json=request)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ZiniaoWebDriverError(
                "transport_error", type(error).__name__
            ) from error
        if not isinstance(payload, Mapping):
            raise ZiniaoWebDriverError("invalid_response", "Response is not an object")
        status_code = str(payload.get("statusCode", ""))
        if status_code != "0":
            message = payload.get("err") or payload.get("LastError") or "Request failed"
            raise ZiniaoWebDriverError(status_code or "unknown", str(message))
        return payload


def _loopback_endpoint(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Ziniao WebDriver URL must use an HTTP loopback address.")
    if parsed.port is None:
        raise ValueError("Ziniao WebDriver URL must include a port.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Ziniao WebDriver URL must not include a path or query.")
    return f"http://{parsed.hostname}:{parsed.port}/"


def _debugging_port(value: object) -> int:
    try:
        port = int(str(value))
    except (TypeError, ValueError) as error:
        raise ZiniaoWebDriverError(
            "invalid_response", "Debugging port is invalid"
        ) from error
    if not 1 <= port <= 65_535:
        raise ZiniaoWebDriverError("invalid_response", "Debugging port is invalid")
    return port


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ZiniaoWebDriverError("invalid_response", "Required text is missing")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _browser_core_type(value: object, browser_path: str | None) -> str:
    explicit = _optional_text(value)
    if explicit:
        return explicit
    if browser_path and "chrome" in Path(browser_path).name.casefold():
        return "Chromium"
    raise ZiniaoWebDriverError("invalid_response", "Browser core type is missing")


def _safe_message(value: str) -> str:
    normalized = " ".join(value.replace("\x00", "").split())
    return normalized[:300] or "Request failed"

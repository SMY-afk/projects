from __future__ import annotations

import asyncio
import os
import re
import subprocess
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import parse_qs, urlsplit

import httpx

from backend.app.services.windows_background_process import background_process_options

_CDP_PORT = re.compile(r"--remote-debugging-port(?:=|\s+)(\d{1,5})")
CommandLineReader = Callable[[], Iterable[str]]
EndpointProbe = Callable[[str], Awaitable[bool]]
ShopEndpointProbe = Callable[[str, str], Awaitable[bool]]
CDP_SHOP_PROBE_TIMEOUT_SECONDS = 9


def parse_hubstudio_cdp_ports(command_lines: Iterable[str]) -> list[int]:
    ports = set()
    for command_line in command_lines:
        if "hubstudio.exe" not in command_line.casefold():
            continue
        match = _CDP_PORT.search(command_line)
        if match is None:
            continue
        port = int(match.group(1))
        if 1 <= port <= 65535:
            ports.add(port)
    return sorted(ports)


async def discover_hubstudio_cdp_url(
    *,
    current_url: str | None,
    expected_platform_shop_id: str | None = None,
    trust_current_url: bool = False,
    command_line_reader: CommandLineReader | None = None,
    probe: EndpointProbe | None = None,
    shop_probe: ShopEndpointProbe | None = None,
) -> str | None:
    read_commands = command_line_reader or read_hubstudio_command_lines
    endpoint_probe = probe or probe_cdp_endpoint
    expected_shop_probe = shop_probe or probe_cdp_shop_endpoint
    candidates = []
    normalized_current = normalize_loopback_cdp_url(current_url)
    if normalized_current:
        candidates.append(normalized_current)
    for port in parse_hubstudio_cdp_ports(read_commands()):
        candidate = f"http://127.0.0.1:{port}"
        if candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        if not await endpoint_probe(candidate):
            continue
        if trust_current_url and candidate == normalized_current:
            return candidate
        if expected_platform_shop_id:
            try:
                matched = await asyncio.wait_for(
                    expected_shop_probe(candidate, expected_platform_shop_id),
                    CDP_SHOP_PROBE_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                continue
            if not matched:
                continue
        return candidate
    return None


def normalize_loopback_cdp_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        return None
    return f"http://127.0.0.1:{port}"


def read_hubstudio_command_lines() -> list[str]:
    if os.name != "nt":
        return []
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "Get-CimInstance Win32_Process -Filter \"Name='hubstudio.exe'\" | "
        "ForEach-Object { if ($_.CommandLine -match "
        "'--remote-debugging-port(?:=|\\s+)(\\d+)') { "
        "'hubstudio.exe --remote-debugging-port=' + $Matches[1] } }"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            **background_process_options(),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


async def probe_cdp_endpoint(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(f"{url}/json/version")
            payload = response.json()
        return (
            response.status_code == 200
            and isinstance(payload, dict)
            and bool(payload.get("webSocketDebuggerUrl") or payload.get("Browser"))
        )
    except (httpx.HTTPError, ValueError):
        return False


async def probe_cdp_shop_endpoint(url: str, platform_shop_id: str) -> bool:
    return platform_shop_id in await read_cdp_platform_shop_ids(url)


async def read_cdp_platform_shop_ids(url: str) -> frozenset[str]:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(f"{url}/json/list")
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return frozenset()
    if response.status_code != 200 or not isinstance(payload, list):
        return frozenset()
    shop_ids: set[str] = set()
    has_seller_page = False
    for target in payload:
        if (
            not isinstance(target, dict)
            or target.get("type") not in (None, "page")
            or not isinstance(target_url := target.get("url"), str)
        ):
            continue
        has_seller_page |= (
            urlsplit(target_url).hostname == "seller.tiktokshopglobalselling.com"
        )
        query = parse_qs(urlsplit(target_url).query)
        for key in ("shop_id", "oec_seller_id"):
            shop_ids.update(
                value.strip() for value in query.get(key, []) if value.strip()
            )
    if has_seller_page and not shop_ids:
        shop_ids.update(await _read_seller_storage_shop_ids(url))
    return frozenset(shop_ids)


async def _read_seller_storage_shop_ids(url: str) -> frozenset[str]:
    """Read the active affiliate filter's shop ID; account keys may be stale."""
    from playwright.async_api import async_playwright

    shop_ids: set[str] = set()
    try:
        async with async_playwright() as playwright:
            browser = await asyncio.wait_for(
                playwright.chromium.connect_over_cdp(url, timeout=5000), 6
            )
            for context in browser.contexts:
                for page in context.pages:
                    if urlsplit(page.url).hostname != "seller.tiktokshopglobalselling.com":
                        continue
                    current_filter = await asyncio.wait_for(
                        page.evaluate("localStorage.getItem('filter_settings_storage_key')"), 2
                    )
                    if isinstance(current_filter, str):
                        query = parse_qs(current_filter.lstrip("?"))
                        shop_ids.update(
                            shop_id
                            for shop_id in query.get("shop_id", [])
                            if re.fullmatch(r"\d{15,20}", shop_id)
                        )
    except Exception:  # noqa: BLE001 -- unavailable CDP fails closed
        return frozenset()
    return frozenset(shop_ids)

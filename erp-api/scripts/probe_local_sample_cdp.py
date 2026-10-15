"""Bounded, read-only identity and attachment diagnostics for one collector."""

import argparse
import asyncio
import json
from time import monotonic
from urllib.parse import parse_qs, urlsplit

import httpx
import websockets
from playwright.async_api import async_playwright

from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.hubstudio_cdp import read_cdp_platform_shop_ids
from backend.app.services.sample_owned_cdp import owned_sample_cdp
from scripts.run_remote_sample_capture_loop import SHOPS


async def protocol_probe(port: int, shop_label: str, activate: bool, owned_probe: bool) -> None:
    async with httpx.AsyncClient(timeout=3) as client:
        version = (await client.get(f"http://127.0.0.1:{port}/json/version")).json()
    async with websockets.connect(version["webSocketDebuggerUrl"], open_timeout=5) as socket:
        sequence = 0

        async def command(method, params=None, session=None):
            nonlocal sequence
            sequence += 1
            request = {"id": sequence, "method": method, "params": params or {}}
            if session:
                request["sessionId"] = session
            await socket.send(json.dumps(request))
            while True:
                response = json.loads(await asyncio.wait_for(socket.recv(), 5))
                if response.get("id") == sequence:
                    if "error" in response:
                        raise RuntimeError("protocol_command_failed")
                    return response.get("result", {})

        targets = (await command("Target.getTargets"))["targetInfos"]
        pages = [target for target in targets if target["type"] == "page"]
        if owned_probe:
            owned_id = (await command("Target.createTarget", {"url": "about:blank"}))["targetId"]
            try:
                session = (await command("Target.attachToTarget", {
                    "targetId": owned_id, "flatten": True,
                }))["sessionId"]
                result = await command("Runtime.evaluate", {"expression": "1+1"}, session)
                print(f"OWNED_RENDERER_OK={result.get('result', {}).get('value') == 2}", flush=True)
            finally:
                await command("Target.closeTarget", {"targetId": owned_id})
            return
        if activate:
            expected = SHOPS[shop_label][2]
            sample_pages = [target for target in pages if (
                urlsplit(target["url"]).hostname == "affiliate.tiktokshopglobalselling.com"
                and urlsplit(target["url"]).path == "/affiliate/sample/sample-request"
                and parse_qs(urlsplit(target["url"]).query).get("shop_id") == [expected]
            )]
            if len(sample_pages) != 1:
                raise RuntimeError("sample_target_missing_or_ambiguous")
            await command("Target.activateTarget", {"targetId": sample_pages[0]["targetId"]})
            print("SAMPLE_TARGET_ACTIVATED", flush=True)
        print(f"PROTOCOL_OK PAGE_COUNT={len(pages)}", flush=True)
        for target in pages:
            session = None
            try:
                session = (await command("Target.attachToTarget", {
                    "targetId": target["targetId"], "flatten": True,
                }))["sessionId"]
                result = await command("Runtime.evaluate", {"expression": "1+1"}, session)
                if result.get("result", {}).get("value") != 2:
                    raise RuntimeError("renderer_probe_invalid")
                print(f"RENDERER={target['targetId']} STATUS=ok", flush=True)
            except Exception as error:  # noqa: BLE001 -- report untrusted protocol failures
                print(f"RENDERER={target['targetId']} STATUS=failed ERROR={type(error).__name__}", flush=True)
            finally:
                if session:
                    try:
                        await command("Target.detachFromTarget", {"sessionId": session})
                    except Exception:  # noqa: BLE001 -- best-effort session cleanup
                        print("DETACH_STATUS=failed", flush=True)


async def main(shop_label: str, port: int, timeout: float) -> None:
    url = f"http://127.0.0.1:{port}"
    for phase in ("identity", "attach"):
        started = monotonic()
        try:
            if phase == "identity":
                ids = await asyncio.wait_for(read_cdp_platform_shop_ids(url), 8)
                if ids != frozenset({SHOPS[shop_label][2]}):
                    raise RuntimeError("shop_identity_mismatch")
                detail = "verified"
            else:
                async with async_playwright() as playwright:
                    browser = await connect_attached_hubstudio_browser(
                        playwright, url, timeout_seconds=timeout
                    )
                    detail = f"contexts={len(browser.contexts)}"
            print(f"PHASE={phase} STATUS=ok DETAIL={detail}", flush=True)
        except Exception as error:  # noqa: BLE001 -- diagnostic boundary
            print(f"PHASE={phase} STATUS=failed ERROR={type(error).__name__}", flush=True)
        print(f"ELAPSED_SECONDS={monotonic() - started:.2f}", flush=True)


async def probe_owned_attachment(port: int) -> None:
    async with (
        owned_sample_cdp(f"http://127.0.0.1:{port}") as endpoint,
        async_playwright() as playwright,
    ):
        browser = await connect_attached_hubstudio_browser(playwright, endpoint, timeout_seconds=15)
        pages = [page for context in browser.contexts for page in context.pages]
        print(f"OWNED_ATTACH_OK={len(pages) == 1}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop", choices=SHOPS, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=8)
    parser.add_argument("--protocol-only", action="store_true")
    parser.add_argument("--activate-sample", action="store_true")
    parser.add_argument("--owned-probe", action="store_true")
    parser.add_argument("--owned-attach", action="store_true")
    arguments = parser.parse_args()
    if arguments.owned_attach:
        asyncio.run(probe_owned_attachment(arguments.port))
    elif arguments.protocol_only:
        asyncio.run(protocol_probe(arguments.port, arguments.shop, arguments.activate_sample, arguments.owned_probe))
    else:
        asyncio.run(main(arguments.shop, arguments.port, arguments.timeout))

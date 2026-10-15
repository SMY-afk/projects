"""Bounded passive CDP security probes without Playwright global target attachment."""

import asyncio
import json
from urllib.parse import urlsplit

import httpx
import websockets

HOSTS = {
    "affiliate.tiktokshopglobalselling.com",
    "affiliate-us.tiktok.com",
    "seller.tiktokshopglobalselling.com",
    "seller.us.tiktokshopglobalselling.com",
}
EXPRESSION = """(() => {
 const path = location.pathname.toLowerCase();
 if (path.includes('captcha')) return 'captcha';
 if (['/login','/passport','/signin','/auth/'].some(x => path.includes(x)))
   return 'session_expired';
 const nodes = document.querySelectorAll(
   'iframe[src*="captcha" i], [id*="captcha" i], [class*="captcha" i]');
 if (Array.from(nodes).some(x => {const r=x.getBoundingClientRect();
   return r.width>0 && r.height>0 && getComputedStyle(x).visibility!=='hidden';}))
   return 'captcha';
 return document.readyState === 'loading' ? 'connecting' : 'online';
})()"""


async def browser_security_state(endpoint):
    async with httpx.AsyncClient(timeout=3) as client:
        response = await client.get(f"{endpoint}/json/list")
        response.raise_for_status()
        targets = response.json()
    business = [
        target
        for target in targets
        if target.get("type") == "page"
        and urlsplit(target.get("url", "")).hostname in HOSTS
    ]
    if not business:
        return "connecting"
    results = await asyncio.gather(
        *(_page_state(target) for target in business),
        return_exceptions=True,
    )
    for state in ("captcha", "session_expired"):
        if state in results:
            return state
    if any(
        isinstance(result, BaseException) or result != "online" for result in results
    ):
        return "connecting"
    return "online"


async def _page_state(target):
    path = urlsplit(target.get("url", "")).path.casefold()
    if "captcha" in path:
        return "captcha"
    if any(marker in path for marker in ("/login", "/passport", "/signin", "/auth/")):
        return "session_expired"
    endpoint = target.get("webSocketDebuggerUrl")
    if not endpoint:
        return "connecting"
    async with websockets.connect(endpoint, open_timeout=3, close_timeout=1) as socket:
        await socket.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": EXPRESSION,
                        "returnByValue": True,
                        "timeout": 2000,
                    },
                }
            )
        )
        async with asyncio.timeout(3):
            while True:
                reply = json.loads(await socket.recv())
                if reply.get("id") == 1:
                    if "error" in reply or "exceptionDetails" in reply.get(
                        "result", {}
                    ):
                        return "connecting"
                    return (
                        reply.get("result", {})
                        .get("result", {})
                        .get("value", "connecting")
                    )

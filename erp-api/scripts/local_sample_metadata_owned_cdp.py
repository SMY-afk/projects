"""Expose the registered local target only; missing targets never create new pages."""

import json
import secrets
from contextlib import asynccontextmanager

import httpx
import websockets

from backend.app.services.sample_owned_cdp import _command, _relay
from backend.app.services.sample_persistent_target import PersistentSampleTarget
from scripts.local_sample_metadata_rules import PLATFORM_SHOP


def require_existing_target(registry, targets):
    try:
        ownership = json.loads(registry.path.read_text(encoding="utf-8")).get("ownership")
    except (OSError, ValueError) as error:
        raise RuntimeError("metadata_existing_owned_registry_missing") from error
    if ownership != "collector_created":
        raise RuntimeError("metadata_existing_target_ownership_invalid")
    target = registry.resolve(targets)
    if not target:
        raise RuntimeError("metadata_existing_owned_target_missing")
    return target


class ExistingTargetSocket:
    def __init__(self, socket, target_id):
        self.socket, self.target_id = socket, target_id

    async def send(self, raw):
        message = json.loads(raw)
        method, params = message.get("method", ""), message.get("params", {})
        if (method in {"Target.createTarget", "Target.closeTarget", "Browser.close",
                       "Target.createBrowserContext", "Target.disposeBrowserContext"}
                or "targetId" in params and params["targetId"] != self.target_id
                or method.startswith("Browser.") and method not in {
                    "Browser.getVersion", "Browser.getWindowForTarget", "Browser.getWindowBounds"}):
            raise PermissionError("metadata_cdp_mutation_outside_existing_target")
        await self.socket.send(raw)

    async def recv(self):
        return await self.socket.recv()

    def __aiter__(self):
        return self.socket.__aiter__()


@asynccontextmanager
async def existing_local_cdp(endpoint, *, registry_root=None):
    async with httpx.AsyncClient(timeout=3) as client:
        version_reply = await client.get(f"{endpoint}/json/version")
        target_reply = await client.get(f"{endpoint}/json/list")
        version_reply.raise_for_status()
        target_reply.raise_for_status()
        version, targets = version_reply.json(), target_reply.json()
    registry = PersistentSampleTarget((PLATFORM_SHOP, "refundable"),
                                      version["webSocketDebuggerUrl"], root=registry_root)
    target = require_existing_target(registry, targets)
    async with websockets.connect(version["webSocketDebuggerUrl"], open_timeout=5,
                                  max_size=20 * 1024 * 1024) as socket:
        info = await _command(socket, 999_999_996, "Target.getTargetInfo", {"targetId": target})
        actual = info.get("targetInfo", {})
        if (actual.get("targetId") != target or require_existing_target(registry, [
                {"id": target, "type": actual.get("type"), "url": actual.get("url")},
        ]) != target):
            raise RuntimeError("metadata_existing_target_changed")
        path, connected = "/" + secrets.token_urlsafe(24), False

        async def handler(client):
            nonlocal connected
            if connected or client.request.path != path:
                await client.close()
                return
            connected = True
            await _relay(client, ExistingTargetSocket(socket, target), target)

        async with websockets.serve(handler, "127.0.0.1", 0, close_timeout=2,
                                    max_size=20 * 1024 * 1024) as server:
            port = server.sockets[0].getsockname()[1]
            # Only close our WebSocket server/client, never the browser/target.
            yield f"ws://127.0.0.1:{port}{path}", target, registry

"""Expose only a collector-owned target from an externally owned CDP browser."""

from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager, suppress

import httpx
import websockets

from backend.app.services.sample_persistent_target import (
    PersistentSampleTarget,
    is_owned_error_page,
)


def safe_owned_command(message: dict, owned_id: str) -> dict | None:
    method = message.get("method")
    params = message.get("params", {})
    if method == "Browser.setDownloadBehavior":
        return None
    if method == "Browser.close" or (
        method in {"Target.closeTarget", "Target.activateTarget"}
        and params.get("targetId") != owned_id
    ):
        raise PermissionError("Collector may operate only on its own target")
    if method == "Target.setAutoAttach" and not message.get("sessionId"):
        # Unrelated newly opened tabs must never be paused by this connection.
        message = {**message, "params": {**params, "waitForDebuggerOnStart": False}}
    return message


def is_owned_attachment(message: dict, owned_id: str, sessions: set[str]) -> bool:
    params = message.get("params", {})
    return bool(
        message.get("sessionId") in sessions
        or params.get("targetInfo", {}).get("targetId") == owned_id
    )


async def _command(socket, request_id: int, method: str, params: dict) -> dict:
    await socket.send(
        json.dumps({"id": request_id, "method": method, "params": params})
    )
    async with asyncio.timeout(8):
        while True:
            message = json.loads(await socket.recv())
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError("Owned CDP command failed")
                return message.get("result", {})


async def _relay(client, remote, owned_id: str) -> None:
    sessions: set[str] = set()
    hidden_sessions: set[str] = set()
    internal_ids: set[int] = set()
    next_internal_id = 1_000_000_000

    async def upstream():
        async for raw in client:
            message = json.loads(raw)
            request_id = message["id"]
            try:
                message = safe_owned_command(message, owned_id)
            except PermissionError:
                await client.send(
                    json.dumps(
                        {
                            "id": message["id"],
                            "error": {
                                "code": -32000,
                                "message": "Target is externally owned",
                            },
                        }
                    )
                )
                continue
            if message is None:
                await client.send(json.dumps({"id": request_id, "result": {}}))
                continue
            await remote.send(json.dumps(message))

    async def downstream():
        nonlocal next_internal_id
        async for raw in remote:
            message = json.loads(raw)
            if message.get("id") in internal_ids:
                internal_ids.discard(message["id"])
                continue
            method = message.get("method")
            params = message.get("params", {})
            if method == "Target.attachedToTarget":
                session_id = params["sessionId"]
                if not is_owned_attachment(message, owned_id, sessions):
                    hidden_sessions.add(session_id)
                    next_internal_id += 1
                    internal_ids.add(next_internal_id)
                    await remote.send(
                        json.dumps(
                            {
                                "id": next_internal_id,
                                "method": "Target.detachFromTarget",
                                "params": {"sessionId": session_id},
                            }
                        )
                    )
                    continue
                sessions.add(session_id)
            elif method == "Target.detachedFromTarget":
                if params.get("sessionId") in hidden_sessions:
                    hidden_sessions.discard(params["sessionId"])
                    continue
                sessions.discard(params.get("sessionId"))
            if message.get("sessionId") in hidden_sessions:
                continue
            await client.send(json.dumps(message))

    tasks = [asyncio.create_task(upstream()), asyncio.create_task(downstream())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@asynccontextmanager
async def owned_sample_cdp(cdp_url: str, *, persistent_key=None, registry_root=None):
    """Expose one owned target; approved persistent pages survive disconnection."""
    async with httpx.AsyncClient(timeout=3) as client:
        version = (await client.get(f"{cdp_url}/json/version")).json()
        targets = (
            (await client.get(f"{cdp_url}/json/list")).json() if persistent_key else []
        )
    registry = (
        PersistentSampleTarget(
            persistent_key, version["webSocketDebuggerUrl"], root=registry_root
        )
        if persistent_key
        else None
    )
    async with websockets.connect(
        version["webSocketDebuggerUrl"], open_timeout=5, max_size=20 * 1024 * 1024
    ) as remote:
        owned_id = registry.resolve(targets) if registry else None
        if owned_id is None:
            if registry and sum(t.get("type") == "page" for t in targets) >= 8:
                raise RuntimeError("tab_limit_reached")
            result = await _command(
                remote, 999_999_998, "Target.createTarget", {"url": "about:blank"}
            )
            owned_id = result["targetId"]
            if registry:
                try:
                    registry.save(owned_id)
                except Exception:
                    await _command(
                        remote,
                        999_999_999,
                        "Target.closeTarget",
                        {"targetId": owned_id},
                    )
                    raise
        path = "/" + secrets.token_urlsafe(24)
        connected = False

        async def handler(client):
            nonlocal connected
            if connected or client.request.path != path:
                await client.close()
                return
            connected = True
            await _relay(client, remote, owned_id)

        try:
            async with websockets.serve(
                handler, "127.0.0.1", 0, max_size=20 * 1024 * 1024, close_timeout=2
            ) as server:
                port = server.sockets[0].getsockname()[1]
                yield f"ws://127.0.0.1:{port}{path}"
        finally:
            close_target = registry is None
            if registry and not registry.is_externally_owned():
                with suppress(Exception):
                    async with httpx.AsyncClient(timeout=3) as client:
                        targets = (await client.get(f"{cdp_url}/json/list")).json()
                    close_target = is_owned_error_page(targets, owned_id)
            if close_target:
                with suppress(Exception):
                    await _command(
                        remote,
                        999_999_999,
                        "Target.closeTarget",
                        {"targetId": owned_id},
                    )
                    if registry:
                        registry.save(None)

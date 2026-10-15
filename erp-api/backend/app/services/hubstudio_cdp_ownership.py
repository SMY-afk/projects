from __future__ import annotations

import json
import ntpath
import os
import subprocess
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from backend.app.services.hubstudio_cdp import normalize_loopback_cdp_url
from backend.app.services.windows_background_process import background_process_options

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
_COLLECTOR_PROFILE_MARKER = (
    r"C:\Users\DarenCollector\AppData\Roaming\hubstudio-client"
)
_COLLECTOR_LISTENER_MARKER = r"C:\Users\DarenCollector\AppData\Local\env-kit"


def assert_erp_hubstudio_cdp_url(
    cdp_url: str,
    *,
    expected_profile_root: str | None = None,
    runner: ProcessRunner = subprocess.run,
) -> str:
    normalized = normalize_loopback_cdp_url(cdp_url)
    if normalized is None:
        raise PermissionError("ERP HubStudio requires an explicit loopback CDP URL.")
    if os.name != "nt" and runner is subprocess.run:
        raise PermissionError("ERP HubStudio ownership verification requires Windows.")

    profile_root = expected_profile_root or _default_profile_root()
    if not profile_root:
        raise PermissionError("ERP HubStudio ownership could not be determined.")
    port = urlsplit(normalized).port
    if port is None:
        raise PermissionError("ERP HubStudio CDP port could not be determined.")

    payload = _read_process_snapshot(port, runner)
    listener_path = str(payload.get("listenerPath") or "").strip()
    if listener_path:
        _assert_listener_path_owner(listener_path, profile_root)
        return normalized
    processes = _process_index(payload.get("processes"))
    listener_pid = _positive_int(payload.get("listenerPid"))
    listener = processes.get(listener_pid)
    if listener is None or _process_name(listener) != "hubstudio.exe":
        raise PermissionError("The configured CDP listener is not HubStudio.")

    root_pid = _instance_root_pid(listener_pid, processes)
    servers = [
        process
        for process in processes.values()
        if "httpserver.cjs" in _command_line(process).casefold()
        and _has_ancestor(_positive_int(process.get("pid")), root_pid, processes)
    ]
    if any(
        _profile_in_command(_COLLECTOR_PROFILE_MARKER, _command_line(process))
        for process in servers
    ):
        raise PermissionError("DarenCollector HubStudio is isolated from ERP.")
    if len(servers) != 1 or not _profile_in_command(
        profile_root, _command_line(servers[0])
    ):
        raise PermissionError("ERP HubStudio ownership could not be verified.")
    return normalized


def _default_profile_root() -> str:
    appdata = os.environ.get("APPDATA", "").strip()
    return f"{appdata}\\hubstudio-client" if appdata else ""


def _read_process_snapshot(port: int, runner: ProcessRunner) -> dict[str, Any]:
    script = rf"""
$listenerLine = netstat -ano -p tcp |
  Where-Object {{ $_ -match '^\s*TCP\s+127\.0\.0\.1:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$' }} |
  Select-Object -First 1
$ownerPid = if ($listenerLine -and $listenerLine -match '(\d+)\s*$') {{
  [int]$Matches[1]
}} else {{ 0 }}
$listener = if ($ownerPid) {{
  Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
}} else {{ $null }}
[pscustomobject]@{{
  listenerPid = $ownerPid
  listenerPath = if ($listener) {{ [string]$listener.Path }} else {{ '' }}
  processes = @()
}} | ConvertTo-Json -Compress -Depth 4
"""
    try:
        completed = runner(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
            **background_process_options(),
        )
        if completed.returncode != 0:
            raise PermissionError("ERP HubStudio ownership check failed.")
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as error:
        raise PermissionError("ERP HubStudio ownership check failed.") from error
    if not isinstance(payload, dict):
        raise PermissionError("ERP HubStudio ownership check returned invalid data.")
    return payload


def _assert_listener_path_owner(listener_path: str, profile_root: str) -> None:
    normalized_path = ntpath.normpath(listener_path)
    if ntpath.basename(normalized_path).casefold() != "hubstudio.exe":
        raise PermissionError("The configured CDP listener is not HubStudio.")
    collector_root = ntpath.normpath(_COLLECTOR_LISTENER_MARKER)
    if _is_within(normalized_path, collector_root):
        raise PermissionError("DarenCollector HubStudio is isolated from ERP.")
    appdata_root = ntpath.dirname(ntpath.dirname(ntpath.normpath(profile_root)))
    expected_root = ntpath.join(appdata_root, "Local", "env-kit", "Core")
    if not _is_within(normalized_path, expected_root):
        raise PermissionError("ERP HubStudio ownership could not be verified.")


def _is_within(path: str, root: str) -> bool:
    try:
        return ntpath.commonpath([path, root]).casefold() == root.casefold()
    except ValueError:
        return False


def _process_index(value: object) -> dict[int, dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    return {
        pid: row
        for row in rows
        if isinstance(row, dict) and (pid := _positive_int(row.get("pid")))
    }


def _instance_root_pid(
    listener_pid: int, processes: dict[int, dict[str, Any]]
) -> int:
    root_pid = 0
    current_pid = listener_pid
    seen: set[int] = set()
    while current_pid and current_pid not in seen:
        seen.add(current_pid)
        process = processes.get(current_pid)
        if process is None:
            break
        if _process_name(process) == "hubstudio.exe":
            root_pid = current_pid
        current_pid = _positive_int(process.get("parentPid"))
    if not root_pid:
        raise PermissionError("The configured CDP listener is not HubStudio.")
    return root_pid


def _has_ancestor(
    process_pid: int, ancestor_pid: int, processes: dict[int, dict[str, Any]]
) -> bool:
    current_pid = process_pid
    seen: set[int] = set()
    while current_pid and current_pid not in seen:
        if current_pid == ancestor_pid:
            return True
        seen.add(current_pid)
        process = processes.get(current_pid)
        if process is None:
            return False
        current_pid = _positive_int(process.get("parentPid"))
    return False


def _process_name(process: dict[str, Any]) -> str:
    return str(process.get("name") or "").casefold()


def _command_line(process: dict[str, Any]) -> str:
    return str(process.get("commandLine") or "")


def _profile_in_command(profile_root: str, command_line: str) -> bool:
    expected = profile_root.replace("/", "\\").rstrip("\\").casefold()
    actual = command_line.replace("/", "\\").casefold()
    return bool(expected) and expected in actual


def _positive_int(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)

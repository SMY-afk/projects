import json
from types import SimpleNamespace

import pytest

from backend.app.services.hubstudio_cdp_ownership import (
    assert_erp_hubstudio_cdp_url,
)

EDY_PROFILE = r"C:\Users\EDY\AppData\Roaming\hubstudio-client"
COLLECTOR_PROFILE = r"C:\Users\DarenCollector\AppData\Roaming\hubstudio-client"


def _runner(profile_root: str | None, *, listener_name: str = "hubstudio.exe"):
    processes = [
        {
            "pid": 100,
            "parentPid": 50,
            "name": "Hubstudio.exe",
            "commandLine": r'"D:\zhiwen\Hubstudio\Hubstudio.exe"',
        },
        {
            "pid": 110,
            "parentPid": 100,
            "name": "env-kit.exe",
            "commandLine": r'"D:\zhiwen\Hubstudio\env-kit.exe"',
        },
        {
            "pid": 120,
            "parentPid": 110,
            "name": listener_name,
            "commandLine": (
                r'"D:\zhiwen\Hubstudio\Hubstudio.exe" '
                r"--remote-debugging-port=57705"
            ),
        },
    ]
    if profile_root is not None:
        processes.append(
            {
                "pid": 130,
                "parentPid": 100,
                "name": "Hubstudio.exe",
                "commandLine": f'"D:\\zhiwen\\Hubstudio\\Hubstudio.exe" '
                f'"{profile_root}\\httpServer.cjs" 9077',
            }
        )

    def run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"listenerPid": 120, "processes": processes}),
            stderr="",
        )

    return run


def test_allows_only_the_current_erp_hubstudio_instance() -> None:
    assert (
        assert_erp_hubstudio_cdp_url(
            "http://localhost:57705",
            expected_profile_root=EDY_PROFILE,
            runner=_runner(EDY_PROFILE),
        )
        == "http://127.0.0.1:57705"
    )


def test_refuses_darencollector_hubstudio_even_when_the_port_is_explicit() -> None:
    with pytest.raises(PermissionError, match="DarenCollector"):
        assert_erp_hubstudio_cdp_url(
            "http://127.0.0.1:55080",
            expected_profile_root=EDY_PROFILE,
            runner=_runner(COLLECTOR_PROFILE),
        )


def test_fails_closed_when_hubstudio_instance_ownership_is_unknown() -> None:
    with pytest.raises(PermissionError, match="ownership"):
        assert_erp_hubstudio_cdp_url(
            "http://127.0.0.1:57705",
            expected_profile_root=EDY_PROFILE,
            runner=_runner(None),
        )


def test_refuses_a_non_hubstudio_listener() -> None:
    with pytest.raises(PermissionError, match="HubStudio"):
        assert_erp_hubstudio_cdp_url(
            "http://127.0.0.1:57705",
            expected_profile_root=EDY_PROFILE,
            runner=_runner(EDY_PROFILE, listener_name="chrome.exe"),
        )


def _path_runner(listener_path: str):
    def run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "listenerPid": 120,
                    "listenerPath": listener_path,
                    "processes": [],
                }
            ),
            stderr="",
        )

    return run


def test_allows_wmi_free_snapshot_for_the_current_erp_user() -> None:
    assert (
        assert_erp_hubstudio_cdp_url(
            "http://127.0.0.1:57705",
            expected_profile_root=EDY_PROFILE,
            runner=_path_runner(
                r"C:\Users\EDY\AppData\Local\env-kit\Core\chrome_64\hubstudio.exe"
            ),
        )
        == "http://127.0.0.1:57705"
    )


def test_refuses_wmi_free_snapshot_for_darencollector() -> None:
    with pytest.raises(PermissionError, match="DarenCollector"):
        assert_erp_hubstudio_cdp_url(
            "http://127.0.0.1:55080",
            expected_profile_root=EDY_PROFILE,
            runner=_path_runner(
                r"C:\Users\DarenCollector\AppData\Local\env-kit\Core\chrome_64\hubstudio.exe"
            ),
        )


def test_fails_closed_for_an_unexpected_wmi_free_listener_path() -> None:
    with pytest.raises(PermissionError, match="ownership"):
        assert_erp_hubstudio_cdp_url(
            "http://127.0.0.1:57705",
            expected_profile_root=EDY_PROFILE,
            runner=_path_runner(r"D:\Portable\hubstudio.exe"),
        )

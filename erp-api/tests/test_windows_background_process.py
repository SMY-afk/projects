"""Background workers must not create visible descendant consoles."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.services import windows_background_process as quiet
from scripts import run_hidden_background as launcher


@pytest.mark.parametrize("hidden,flags", [(False, subprocess.CREATE_NO_WINDOW), (True, 0)])
def test_children_keep_a_hidden_console_or_start_without_one(monkeypatch, hidden, flags):
    monkeypatch.setattr(quiet, "has_hidden_console", lambda: hidden)
    options = quiet.background_process_options()
    assert options["creationflags"] == flags
    assert options["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert options["startupinfo"].wShowWindow == subprocess.SW_HIDE


def test_environment_marker_does_not_replace_real_console_verification(monkeypatch):
    monkeypatch.setenv("ERP_BACKGROUND_CONSOLE", "hidden-v1")
    monkeypatch.setattr(quiet, "has_hidden_console", lambda: False)
    assert quiet.background_process_options()["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_launcher_preserves_arguments_environment_cwd_and_exit_code(monkeypatch):
    seen = {}

    def run(command, **options):
        seen.update(command=command, options=options)
        return SimpleNamespace(returncode=17)

    monkeypatch.setattr(launcher, "run_managed", run)
    monkeypatch.setenv("BACKGROUND_TEST", "preserved")
    args = ["-u", "-m", "scripts.run_remote_sample_capture_loop", "--shop-label", "cross-border-7"]
    assert launcher.launch(args) == 17
    assert seen["command"][1:] == args
    assert Path(seen["command"][0]).name == "python.exe"
    assert seen["options"]["env"]["BACKGROUND_TEST"] == "preserved"
    assert seen["options"]["creationflags"] == subprocess.CREATE_NEW_CONSOLE
    assert seen["options"]["startupinfo"].wShowWindow == subprocess.SW_HIDE
    assert "cwd" not in seen["options"]
    assert not seen["options"].get("shell", False)


def test_launcher_rejects_empty_command():
    with pytest.raises(ValueError, match="Python arguments are required"):
        launcher.launch([])


def test_console_detection_never_uses_environment_as_proof(monkeypatch):
    monkeypatch.setenv("ERP_BACKGROUND_CONSOLE", "hidden-v1")
    assert isinstance(quiet.has_hidden_console(), bool)


@pytest.mark.parametrize("script", [
    "scripts/run_ziniao_sample_watch.py",
    "scripts/cache_affiliate_avatars_local.py",
    "scripts/start_cutover_worker.py",
])
def test_known_powershell_and_avatar_launches_set_background_options(script):
    source = (Path(__file__).parents[1] / script).read_text(encoding="utf-8")
    assert "background_process_options" in source


@pytest.mark.skipif(os.name != "nt", reason="Windows console inheritance contract")
def test_real_child_and_grandchild_share_the_hidden_console(tmp_path):
    report = tmp_path / "console.json"
    child_code = (
        "import ctypes,json;k=ctypes.WinDLL('kernel32');u=ctypes.WinDLL('user32');"
        "k.GetConsoleWindow.restype=ctypes.c_void_p;u.IsWindowVisible.argtypes=[ctypes.c_void_p];"
        "h=k.GetConsoleWindow();print(json.dumps({'console':h,'visible':bool(u.IsWindowVisible(h))}))"
    )
    code = (
        "import ctypes,json,subprocess,sys; "
        "k=ctypes.WinDLL('kernel32');u=ctypes.WinDLL('user32'); "
        "k.GetConsoleWindow.restype=ctypes.c_void_p; "
        "u.IsWindowVisible.argtypes=[ctypes.c_void_p]; "
        "h=k.GetConsoleWindow(); "
        f"child=subprocess.check_output([sys.executable,'-c',{child_code!r}],text=True); "
        "open(sys.argv[1],'w').write(json.dumps({'console':h,'visible':bool(u.IsWindowVisible(h)),"
        "'child':json.loads(child)}))"
    )
    assert launcher.launch(["-c", code, str(report)]) == 0
    result = json.loads(report.read_text())
    assert result["console"]
    assert not result["visible"]
    assert result["child"]["console"] == result["console"]
    assert not result["child"]["visible"]


@pytest.mark.parametrize("script", [
    "register_remote_sample_autostart.ps1",
    "register_remote_affiliate_heartbeat.ps1",
    "register_remote_affiliate_dates.ps1",
    "register-refundable-sample-watches.ps1",
])
def test_task_registration_retains_the_hidden_launch_chain(script):
    source = (Path(__file__).parents[1] / "scripts" / script).read_text(encoding="utf-8")
    assert "-m scripts.run_hidden_background -- " in source


def test_live_deployment_preserves_arguments_and_refuses_active_capture():
    source = (Path(__file__).parents[1] / "scripts/deploy_hidden_background_tasks.ps1").read_text()
    assert "$expectedArguments = $prefix + $originalArguments" in source
    assert "$handle.Lock(0, 1)" in source
    assert "'capturing', 'delivering', 'starting'" in source
    assert "Original task process tree has not stopped" in source
    assert "Export-ScheduledTask" in source
    assert "Never stop the replacement process" in source
    assert "$live.CreationDate -ne $old.CreationDate" in source
    assert "Stop-Process -Id $live.ProcessId" in source


@pytest.mark.skipif(os.name != "nt", reason="Windows descendants")
@pytest.mark.parametrize("bridge", ["powershell", "node"])
def test_real_shell_and_node_descendants_stay_hidden(tmp_path, bridge):
    from sys import executable

    from playwright._impl._driver import compute_driver_executable

    report = tmp_path / (bridge + ".json")
    probe = (
        "import ctypes,json;k=ctypes.WinDLL('kernel32');u=ctypes.WinDLL('user32');"
        "k.GetConsoleWindow.restype=ctypes.c_void_p;u.IsWindowVisible.argtypes=[ctypes.c_void_p];"
        "h=k.GetConsoleWindow();print(json.dumps({'console':h,'visible':bool(u.IsWindowVisible(h))}))"
    )
    python = str(Path(executable).with_name("python.exe"))
    if bridge == "powershell":
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                   "& $env:ERP_PROBE_PYTHON -c $env:ERP_PROBE_CODE"]
    else:
        node, _ = compute_driver_executable()
        js = (
            f"process.stdout.write(require('child_process').execFileSync({json.dumps(python)},"
            f"['-c',{json.dumps(probe)}]).toString())"
        )
        command = [str(node), "-e", js]
    code = (
        "import ctypes,json,os,subprocess,sys;"
        "from backend.app.services.windows_background_process import background_process_options;"
        "k=ctypes.WinDLL('kernel32');k.GetConsoleWindow.restype=ctypes.c_void_p;"
        f"env=dict(os.environ,ERP_PROBE_PYTHON={python!r},ERP_PROBE_CODE={probe!r});"
        f"child=json.loads(subprocess.check_output({command!r},env=env,text=True,"
        "**background_process_options()));"
        "open(sys.argv[1],'w').write(json.dumps({'console':k.GetConsoleWindow(),'child':child}))"
    )
    assert launcher.launch(["-c", code, str(report)]) == 0
    result = json.loads(report.read_text())
    assert result["console"] == result["child"]["console"]
    assert result["console"]
    assert not result["child"]["visible"]

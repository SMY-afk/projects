"""Kill-on-close ownership is restricted to newly spawned task children."""

import ctypes
import json
import os
from types import SimpleNamespace

import pytest

from backend.app.services import windows_background_job as jobs


def test_managed_child_is_assigned_before_wait_and_job_always_closes(monkeypatch):
    events = []

    class Job:
        def __enter__(self):
            events.append("job-open")
            return self

        def assign(self, process):
            events.append(("assigned", process))

        def __exit__(self, *args):
            events.append("job-close")

    process = SimpleNamespace(wait=lambda: events.append("wait") or 9)
    monkeypatch.setattr(jobs, "BackgroundJob", Job)
    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *args, **kwargs: process)
    result = jobs.run_managed(["python.exe", "-c", "pass"])
    assert result.returncode == 9
    assert events == ["job-open", ("assigned", process), "wait", "job-close"]


@pytest.mark.skipif(os.name != "nt", reason="Windows process job contract")
def test_real_job_close_removes_orphaned_grandchildren(tmp_path):
    from scripts.run_hidden_background import launch

    path = tmp_path / "child.json"
    code = (
        "import json,subprocess,sys;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        "open(sys.argv[1],'w').write(json.dumps({'pid':child.pid}))"
    )
    assert launch(["-c", code, str(path)]) == 0
    child_pid = json.loads(path.read_text())["pid"]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100001, False, child_pid)
    if handle:
        try:
            result = kernel.WaitForSingleObject(handle, 2_000)
            if result != 0:
                kernel.TerminateProcess(handle, 1)
            assert result == 0, "Task launcher's job must terminate its orphaned children"
        finally:
            kernel.CloseHandle(handle)

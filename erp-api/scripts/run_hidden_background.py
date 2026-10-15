"""Run an existing Python task under one hidden, inheritable Windows console."""

import os
import subprocess
import sys
from pathlib import Path

from backend.app.services.windows_background_job import run_managed
from backend.app.services.windows_background_process import hidden_startup_info


def launch(arguments: list[str]) -> int:
    if not arguments:
        raise ValueError("Python arguments are required")
    executable = Path(sys.executable)
    if os.name == "nt":
        executable = executable.with_name("python.exe")
        if not executable.is_file():
            raise FileNotFoundError("Companion Python console executable is missing")
        options = {
            "startupinfo": hidden_startup_info(),
            "creationflags": subprocess.CREATE_NEW_CONSOLE,
        }
    else:
        options = {}
    runner = run_managed if os.name == "nt" else subprocess.run
    result = runner(
        [str(executable), *arguments], env=dict(os.environ), check=False, **options
    )
    return result.returncode


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    raise SystemExit(launch(arguments))

"""Start one local ERP ARQ worker with isolated RDS/OSS/ECS-Redis targets."""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from backend.app.services.windows_background_process import background_process_options
from scripts.cutover_runtime_env import build_environment

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime/cutover-workers"
MODULES = {
    "sample": "erp_api.workers.sample_settings.SampleWorkerSettings",
    "main": "erp_api.workers.settings.WorkerSettings",
    "daily": "erp_api.workers.daily_valid_creator_settings.DailyValidCreatorWorkerSettings",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("worker", choices=MODULES)
    args = parser.parse_args()
    env = build_environment()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    pid_path = RUNTIME / f"{args.worker}.pid.json"
    if pid_path.exists():
        previous = json.loads(pid_path.read_text(encoding="utf-8"))
        process = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Get-Process -Id {int(previous['pid'])} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=5, check=False,
            **background_process_options(),
        )
        if process.stdout.strip() == str(previous["pid"]):
            raise SystemExit("STOP_WORKER_ALREADY_RUNNING")
    output_path = RUNTIME / f"{args.worker}.stdout.log"
    error_path = RUNTIME / f"{args.worker}.stderr.log"
    with output_path.open("ab") as stdout, error_path.open("ab") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "arq", MODULES[args.worker]],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    pid_path.write_text(
        json.dumps(
            {"pid": process.pid, "worker": args.worker, "module": MODULES[args.worker],
             "started_at": datetime.now(UTC).isoformat()},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"CUTOVER_WORKER_STARTED TYPE={args.worker} PID={process.pid}")


if __name__ == "__main__":
    main()

from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_local_runtime_entrypoints_use_project_venv_python() -> None:
    api_script = (PROJECT_ROOT / "scripts" / "start-api.ps1").read_text("utf-8")
    worker_script = (PROJECT_ROOT / "scripts" / "start-worker.ps1").read_text("utf-8")

    assert '.venv\\Scripts\\python.exe"' in api_script
    assert "-u -m erp_api" in api_script
    assert '.venv\\Scripts\\python.exe"' in worker_script
    assert "-u -m arq erp_api.workers.settings.WorkerSettings" in worker_script
    assert "arq.exe" not in worker_script


def test_sample_worker_has_an_independent_local_entrypoint() -> None:
    sample_worker_script = (
        PROJECT_ROOT / "scripts" / "start-sample-worker.ps1"
    ).read_text("utf-8")

    assert '.venv-runtime\\Scripts\\python.exe"' in sample_worker_script
    assert (
        "-u -m arq erp_api.workers.sample_settings.SampleWorkerSettings"
        in sample_worker_script
    )


def test_daily_valid_creator_worker_has_an_independent_local_entrypoint() -> None:
    worker_script = (
        PROJECT_ROOT / "scripts" / "start-daily-valid-creator-worker.ps1"
    ).read_text("utf-8")

    assert '.venv-runtime\\Scripts\\python.exe"' in worker_script
    assert (
        "-u -m arq "
        "erp_api.workers.daily_valid_creator_settings."
        "DailyValidCreatorWorkerSettings"
        in worker_script
    )


def test_container_runtime_entrypoints_use_container_venv_python() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text("utf-8")
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text("utf-8")

    assert 'CMD ["/opt/venv/bin/python", "-m", "erp_api"]' in dockerfile
    assert '["/opt/venv/bin/python", "-m", "erp_api"]' in compose
    assert '"/opt/venv/bin/python"' in compose
    assert '"-m"' in compose
    assert '"arq"' in compose
    assert '"erp_api.workers.sample_settings.SampleWorkerSettings"' in compose

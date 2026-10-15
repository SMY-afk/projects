import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import daily_valid_creator_primary_migration as migration


class FakeFeishu:
    def __init__(self, mode):
        self.mode = mode
        self.delete_attempted = False
        self.fields = [
            {"field_id": "fld51re6fs", "field_name": "产品线", "type": 1, "is_primary": True},
            {"field_id": "fldMNQfggl", "field_name": "账号名称", "type": 1, "is_primary": False},
        ] + [{"field_id": key, "field_name": key, "type": value}
             for key, value in migration.FIELD_TYPES.items() if key != "账号名称"]
        self.rows = [{"record_id": "keep", "fields": {"产品线": "童车", "账号名称": " @creator ",
                                                     "BD负责人": "BD"}}]
        self.renames = []

    async def tenant_access_token(self):
        return "test-only"

    async def request_json(self, method, endpoint, **kwargs):
        if method == "GET":
            if self.delete_attempted and self.mode == "unreadable":
                raise TimeoutError("schema unavailable")
            return {"data": {"items": copy.deepcopy(self.fields), "has_more": False}}
        field_id = endpoint.rsplit("/", 1)[-1]
        field = next(item for item in self.fields if item["field_id"] == field_id)
        if method == "PUT":
            old, new = field["field_name"], kwargs["json"]["field_name"]
            self.renames.append((field_id, new))
            field["field_name"] = new
            for row in self.rows:
                if old in row["fields"]:
                    row["fields"][new] = row["fields"].pop(old)
            return {}
        self.delete_attempted = True
        if self.mode == "not_deleted":
            raise TimeoutError("delete rejected before write")
        self.fields.remove(field)
        for row in self.rows:
            row["fields"].pop(field["field_name"], None)
        if self.mode == "changed":
            self.rows[0]["fields"]["账号名称"] = "changed-after-copy"
        raise TimeoutError("delete response lost after write")

    async def batch_records(self, base, table, operation, updates, **kwargs):
        for update in updates:
            row = next(item for item in self.rows if item["record_id"] == update["record_id"])
            row["fields"].update(update["fields"])
        return {"records": copy.deepcopy(updates)}


@pytest.fixture
def setup_migration(monkeypatch):
    async def succeeded(*args):
        return True

    async def verify(*args):
        return None

    async def get(*args, **kwargs):
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(migration.SampleBusinessReadiness, "_daily_sync_succeeded", succeeded)
    monkeypatch.setattr(migration, "verify_target_identity", verify)
    monkeypatch.setattr(migration, "ensure_daily_idle", verify)
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    monkeypatch.setattr(migration, "save_snapshot", lambda *args: None)

    def configure(mode):
        client = FakeFeishu(mode)

        async def rows(*args):
            return copy.deepcopy(client.rows)

        monkeypatch.setattr(migration, "feishu_client", lambda: client)
        monkeypatch.setattr(migration, "target_rows", rows)
        return client

    return configure


@pytest.mark.asyncio
async def test_lost_delete_response_reconciles_verified_final_state(setup_migration, capsys):
    client = setup_migration("deleted")
    await migration.migrate()
    assert '"status": "verified"' in capsys.readouterr().out
    assert client.rows[0]["fields"]["账号名称"] == " @creator "
    assert "产品线" not in client.rows[0]["fields"]
    assert len(client.renames) == 2


@pytest.mark.asyncio
async def test_unknown_delete_schema_never_rolls_back_primary(setup_migration):
    client = setup_migration("unreadable")
    with pytest.raises(RuntimeError, match="audit|unknown"):
        await migration.migrate()
    assert len(client.renames) == 2
    assert "产品线" not in client.rows[0]["fields"]


@pytest.mark.asyncio
async def test_deleted_column_with_changed_values_requires_audit_without_rollback(setup_migration):
    client = setup_migration("changed")
    with pytest.raises(RuntimeError, match="audit"):
        await migration.migrate()
    assert len(client.renames) == 2
    assert client.rows[0]["fields"]["账号名称"] == "changed-after-copy"


@pytest.mark.asyncio
async def test_confirmed_not_deleted_can_restore_old_schema_and_values(setup_migration):
    client = setup_migration("not_deleted")
    with pytest.raises(TimeoutError, match="rejected"):
        await migration.migrate()
    assert client.rows[0]["fields"] == {"产品线": "童车", "账号名称": " @creator ", "BD负责人": "BD"}


def load_runtime(monkeypatch):
    path = Path(__file__).parents[1] / ".runtime/account-shop-cutover/migrate_primary_safely.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("primary_cutover_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failed_service_start_does_not_skip_other_service_or_queue_recovery(monkeypatch):
    runtime = load_runtime(monkeypatch)
    calls = []

    def run(args, **kwargs):
        calls.append(tuple(args))
        if args[:3] == ["docker", "start", runtime.SAMPLE]:
            raise RuntimeError("sample start failed")
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(runtime, "run", run)
    monkeypatch.setattr(runtime, "worker_python", lambda script: calls.append(("restore", script)))
    gate = SimpleNamespace(poll=lambda: 0, wait=lambda timeout: None)
    with pytest.raises(RuntimeError, match="sample start failed"):
        runtime.resume_services("restore-queue", "stop-gate", gate)
    assert ("docker", "start", runtime.DAILY) in calls
    assert ("restore", "restore-queue") in calls


def test_failed_queue_restore_still_starts_daily_and_reports_error(monkeypatch):
    runtime = load_runtime(monkeypatch)
    calls = []
    monkeypatch.setattr(runtime, "run", lambda args, **kwargs: calls.append(tuple(args)))

    def restore(script):
        raise RuntimeError("queue restoration failed")

    monkeypatch.setattr(runtime, "worker_python", restore)
    gate = SimpleNamespace(poll=lambda: 0)
    with pytest.raises(RuntimeError, match="queue restoration failed"):
        runtime.resume_services("restore-queue", "stop-gate", gate)
    assert ("docker", "start", runtime.DAILY) in calls


def test_migration_holds_are_unique_and_generated_scripts_compile(monkeypatch):
    runtime = load_runtime(monkeypatch)
    first = runtime.queue_scripts()
    second = runtime.queue_scripts()
    assert first != second
    for generated in first + second:
        compile(generated, "cutover-queue-script", "exec")
        assert runtime.HOLD_KEY not in generated
    assert "while not await r.exists(stop):" in first[0]
    assert "if not await r.exists(stop): raise RuntimeError" in first[0]


def test_snapshot_is_durable_and_never_overwrites_existing_file(tmp_path):
    path = tmp_path / "snapshot.json"
    migration.save_snapshot(path, [{"field_id": "primary"}], [{"record_id": "keep"}])
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        migration.save_snapshot(path, [], [])
    assert path.read_bytes() == before

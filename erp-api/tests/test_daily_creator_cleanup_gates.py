"""Live health and complete field-pagination gates precede every cleanup read."""

from copy import deepcopy
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from scripts import daily_valid_creator_cleanup_pipeline as cleanup


@pytest.fixture
def health(monkeypatch):
    state = {"status": 200, "api_config": "disabled", "daily_config": "disabled",
             "probes": [], "dependencies": {
                 "database": "ok", "redis": "ok", "sample_schema": "ok",
                 "sample_worker": "ok", "sample_sync_config": "ok"}}

    class HTTP:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            assert url == "http://erp-api:8080/readyz"
            return SimpleNamespace(status_code=state["status"], json=lambda: {
                "status": "ok", "dependencies": {"sample_sync_config": state["api_config"]}})

    async def probe(database, redis_url, *, sample_sync_enabled):
        assert database == "database" and redis_url == "redis"
        assert sample_sync_enabled is True
        state["probes"].append(True)
        return deepcopy(state["dependencies"])

    monkeypatch.setattr(cleanup.httpx, "AsyncClient", HTTP)
    monkeypatch.setattr(cleanup, "probe_dependencies", probe)
    monkeypatch.setattr(cleanup, "get_settings", lambda: SimpleNamespace(redis_url="redis"))
    monkeypatch.setattr(cleanup, "_sample_sync_config_status", lambda _: state["daily_config"])
    return state


@pytest.mark.asyncio
async def test_separate_disabled_daily_role_requires_actual_sample_health(health):
    result = await cleanup.require_cleanup_health({"database": "database"},
                                                  "http://erp-api:8080/api/internal/")
    assert result["daily_sample_config"] == "disabled"
    assert result["api_sample_config"] == "disabled"
    assert result["forced_sample_dependencies"]["sample_worker"] == "ok"
    assert health["probes"] == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("dependency", ["database", "redis", "sample_schema", "sample_worker"])
async def test_actual_sample_dependency_failure_prevents_feishu_read(health, monkeypatch,
                                                                    dependency, tmp_path):
    health["dependencies"][dependency] = "unavailable"

    async def forbidden(*_, **__):
        pytest.fail("Failed sample health cannot call Feishu or backup")

    monkeypatch.setattr(cleanup, "fetch_sources", forbidden)
    with pytest.raises(RuntimeError, match="dependencies are unhealthy"):
        await cleanup.cleanup({"database": "database"}, backup_directory=str(tmp_path),
                              export_url="http://erp-api:8080/api/internal/")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 500, 503])
async def test_http_not_200_prevents_all_source_reads(health, monkeypatch, status, tmp_path):
    health["status"] = status

    async def forbidden(*_, **__):
        pytest.fail("Failed HTTP health cannot call Feishu")

    monkeypatch.setattr(cleanup, "fetch_sources", forbidden)
    with pytest.raises(RuntimeError, match="HTTP 200"):
        await cleanup.cleanup({"database": "database"}, backup_directory=str(tmp_path),
                              export_url="http://erp-api:8080/api/internal/")
    assert health["probes"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("config", ["api_config", "daily_config"])
async def test_unavailable_role_configuration_is_not_masked_as_disabled(health, config):
    health[config] = "unavailable"
    with pytest.raises(RuntimeError, match="configuration is unavailable"):
        await cleanup.require_cleanup_health({"database": "database"},
                                              "http://erp-api:8080/api/internal/")
    assert health["probes"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stale", "reports", "batch", "dates"])
async def test_source_evidence_and_completeness_fail_without_feishu_read(
    monkeypatch, failure, tmp_path,
):
    now = datetime(2026, 10, 14, 6, tzinfo=UTC)
    cutoffs = {"one": {"videos": date(2026, 10, 12)}}

    async def health(*_):
        return {}

    async def snapshot(*_):
        return None if failure == "stale" else (cutoffs, {}, "fingerprint")

    async def runs(*_):
        return []

    async def reports(*_):
        return {"missing": True} if failure == "reports" else {}

    def batch(*_):
        if failure == "batch":
            raise ValueError("incomplete source batch")
        return {}

    async def forbidden(*_, **__):
        pytest.fail("Failed source gate cannot call Feishu")

    monkeypatch.setattr(cleanup, "require_cleanup_health", health)
    monkeypatch.setattr(cleanup, "_now", lambda _: now)
    monkeypatch.setattr(cleanup, "_ready_snapshot", snapshot)
    monkeypatch.setattr(cleanup, "load_batch_runs", runs)
    monkeypatch.setattr(cleanup, "evaluate_batch", batch)
    monkeypatch.setattr(cleanup, "missing_creator_reports", reports)
    monkeypatch.setattr(cleanup, "fetch_sources", forbidden)
    if failure == "dates":
        expected = (cutoffs, {}, "changed", date(2026, 10, 13), {})
        with pytest.raises(RuntimeError, match="scope changed"):
            await cleanup.require_cleanup_sources({"database": "database"}, "", expected=expected)
    else:
        with pytest.raises((RuntimeError, ValueError)):
            await cleanup.cleanup({"database": "database"}, backup_directory=str(tmp_path))
    assert list(tmp_path.iterdir()) == []


class SchemaClient:
    def __init__(self, pages):
        self.pages = list(pages)

    async def tenant_access_token(self):
        return "not-a-real-secret"

    async def request_json(self, method, path, **kwargs):
        assert method == "GET" and path.endswith("/fields")
        return {"data": self.pages.pop(0)}


def schema_fields():
    return [{"field_id": f"field-{index}", "field_name": name, "type": kind,
             "property": {"format": "full-properties"}}
            for index, (name, kind) in enumerate(cleanup.FIELD_TYPES.items())]


@pytest.mark.asyncio
async def test_full_schema_pagination_preserves_all_properties():
    fields = schema_fields()
    pages = [{"items": fields[:6], "total": 11, "has_more": True, "page_token": "next"},
             {"items": fields[6:], "total": 11, "has_more": False}]
    actual = await cleanup.read_target_schema(SchemaClient(pages))
    assert len(actual) == 11
    assert all(field["property"] == {"format": "full-properties"} for field in actual)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["total", "duplicate", "missing", "cursor", "schema"])
async def test_incomplete_or_mutated_field_schema_rejected(failure):
    fields = schema_fields()
    page = {"items": fields, "total": 11, "has_more": False}
    if failure == "total":
        page["total"] = 12
    elif failure == "duplicate":
        fields[-1]["field_id"] = fields[0]["field_id"]
    elif failure == "missing":
        page.pop("total")
    elif failure == "cursor":
        page["has_more"] = True
    else:
        fields[-1]["field_name"] = "Unexpected"
    with pytest.raises(ValueError):
        await cleanup.read_target_schema(SchemaClient([page]))

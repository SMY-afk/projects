from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from scripts.ecs_prepare_daily_valid_env import prepare


def _sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    api = tmp_path / "erp-api.env"
    sample = tmp_path / "erp-sample-worker.env"
    daily = tmp_path / "erp-daily-valid-worker.env"
    base = (
        "APP_ENV=production\n"
        "CORS_ORIGINS=https://example.invalid/configure-resource"
        "AUTH_CAPTCHA_HMAC_SECRET=runtime-secret\n"
        "DATABASE_URL=postgresql+asyncpg://erp:password@"
        "pgm-wz9bb45790nb73dc.pg.rds.aliyuncs.com:5432/wj_erp\n"
        "REDIS_URL=redis://127.0.0.1:6379/0\n"
        "FEISHU_APP_ID=cli-test-app\n"
        "FEISHU_APP_SECRET=test-app-secret\n"
    )
    api.write_text(
        base.replace("cli-test-app", "cli-legacy-app").replace(
            "test-app-secret", "legacy-app-secret"
        ),
        encoding="utf-8",
    )
    sample.write_text(
        base
        + "FEISHU_SAMPLE_BASE_TOKEN=exampleb6b20e30bcdc75e12b5f\n"
        + "FEISHU_DAILY_VALID_CREATOR_TABLE_ID=tblexamplef1d0cfa5\n",
        encoding="utf-8",
    )
    return api, sample, daily


def test_preflight_does_not_change_services_or_create_env(tmp_path: Path) -> None:
    api, sample, daily = _sources(tmp_path)
    original = api.read_bytes()

    result = prepare(api, sample, daily, dry_run=True)

    assert result["status"] == "preflight_ok"
    assert api.read_bytes() == original
    assert not daily.exists()


def test_prepare_stages_isolated_env_and_recoverable_api_backup(tmp_path: Path) -> None:
    api, sample, daily = _sources(tmp_path)
    original = api.read_bytes()

    result = prepare(api, sample, daily)

    assert result["status"] == "prepared_not_started"
    assert len(list(tmp_path.glob("erp-api.env.before-daily-*"))) == 1
    assert next(tmp_path.glob("erp-api.env.before-daily-*")).read_bytes() == original
    assert "AFFILIATE_EXPORT_SERVICE_TOKEN=" in api.read_text(encoding="utf-8")
    assert "FEISHU_NEW_APP_SECRET=test-app-secret" in daily.read_text(
        encoding="utf-8"
    )
    assert "legacy-app-secret" not in daily.read_text(encoding="utf-8")
    assert "AFFILIATE_EXPORT_URL=http://api:8080/api/internal/affiliate-center/" in daily.read_text(
        encoding="utf-8"
    )
    if os.name != "nt":
        assert stat.S_IMODE(daily.stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="already exists"):
        prepare(api, sample, daily)


def test_mismatched_target_fails_without_writes(tmp_path: Path) -> None:
    api, sample, daily = _sources(tmp_path)
    sample.write_text(
        sample.read_text(encoding="utf-8").replace(
            "tblexamplef1d0cfa5", "tblWrongTarget"
        ),
        encoding="utf-8",
    )
    original = api.read_bytes()

    with pytest.raises(ValueError, match="target identity"):
        prepare(api, sample, daily)

    assert api.read_bytes() == original
    assert not daily.exists()


def test_existing_api_captcha_duplicate_is_not_copied(tmp_path: Path) -> None:
    api, sample, daily = _sources(tmp_path)
    api.write_text(
        api.read_text(encoding="utf-8") + "AUTH_CAPTCHA_HMAC_SECRET=other-secret\n",
        encoding="utf-8",
    )

    prepare(api, sample, daily)

    text = daily.read_text(encoding="utf-8")
    assert text.count("AUTH_CAPTCHA_HMAC_SECRET=") == 1
    assert "runtime-secret" not in text
    assert "other-secret" not in text
    assert api.read_text(encoding="utf-8").count("AUTH_CAPTCHA_HMAC_SECRET=") == 2

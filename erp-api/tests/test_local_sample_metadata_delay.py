import pytest

from scripts.run_local_sample_metadata_bridge import result_delay


def test_source_running_without_capture_waits_read_only_sixty_seconds():
    row = {"status": "blocked", "stage": "probe", "reason": "metadata_source_not_complete_success"}
    assert result_delay(row, 20) == 60


@pytest.mark.parametrize("stage", ["captured", "submitting", None])
def test_existing_capture_does_not_get_source_probe_fast_retry(stage):
    row = {"status": "blocked", "stage": stage, "reason": "metadata_source_not_complete_success"}
    assert result_delay(row, 20) == 900


@pytest.mark.parametrize("status", ["completed", "idle", "paused", "audit_required"])
def test_normal_and_security_paths_keep_five_minutes(status):
    assert result_delay({"status": status}, 20) == 300


def test_other_source_failure_retains_backoff():
    assert result_delay({"status": "blocked", "stage": "probe", "reason": "metadata_source_missing"}, 3) == 900


def test_confirmed_unsubmitted_shop_busy_reuses_raw_after_sixty_seconds():
    row = {"status": "deferred", "reason": "sample_shop_busy", "known_unsubmitted": True}
    assert result_delay(row, 20) == 60


@pytest.mark.parametrize("known", [None, False, 1])
def test_unknown_submission_shop_busy_never_gets_fast_retry(known):
    row = {"status": "deferred", "reason": "sample_shop_busy", "known_unsubmitted": known}
    assert result_delay(row, 20) == 900


def test_confirmed_unsubmitted_other_failure_keeps_backoff():
    row = {"status": "deferred", "reason": "metadata_readback_mismatch", "known_unsubmitted": True}
    assert result_delay(row, 20) == 900

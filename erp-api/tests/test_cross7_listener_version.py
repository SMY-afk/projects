import json

from scripts.run_remote_sample_capture_loop import _write_status


def test_cross7_loaded_version_is_distinguishable(tmp_path):
    _write_status(tmp_path, "cross-border-7", "starting")
    row = json.loads((tmp_path / "cross-border-7.status.json").read_text(encoding="utf-8"))
    assert row["collector_version"] == "cross7-reused-review-sort-visible-v6"


def test_other_shop_version_markers_are_unchanged(tmp_path):
    for shop, version in (
        ("cross-border-3", "cross3-first-page-full-window-v2"),
        ("cross-border-4", "cross4-unique-free-tab-v1"),
    ):
        _write_status(tmp_path, shop, "starting")
        row = json.loads((tmp_path / f"{shop}.status.json").read_text(encoding="utf-8"))
        assert row["collector_version"] == version

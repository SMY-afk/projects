"""Package only reviewed changes and preserve unrelated deployed entry points."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / ".runtime/refundable-deploy"
MODULES = {
    "models": ["sample_application", "sample_ingest_batch", "sample_sync_run"],
    "services": [
        "sample_type_policy", "refundable_sample_parser", "refundable_creator_profile",
        "sample_assignment_type_router", "hubstudio_sample_response_parser",
        "remote_sample_capture", "sample_application_mapper", "sample_application_repository",
        "sample_application_upsert", "sample_sync_audit_repository", "hubstudio_sample_ingest_service",
        "feishu_sample_fields", "sample_feishu_source_repository", "sample_feishu_mapper",
        "sample_auto_assignment_repository", "sample_cooperation_repository",
        "sample_assignment_record_service", "sample_notification_card",
        "sample_notification_application_card", "sample_notification_refresh",
        "sample_notification_repository", "sample_notification_products",
        "sample_feishu_duplicate_cleanup", "sample_assignment_record_fields",
        "sample_assignment_summary_service", "sample_assignment_summary_repository",
        "sample_remaining_display", "sample_post_source_work_gate", "sample_creator_profile_realtime",
    ],
    "routers": ["remote_sample_capture"],
    "workers": ["assignment_summary_worker"],
}


def run(api=False):
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for directory, names in MODULES.items():
        target = DESTINATION / "erp_api" / directory
        target.mkdir(parents=True, exist_ok=True)
        for name in names:
            shutil.copy2(ROOT / "src/erp_api" / directory / f"{name}.py", target)
    suffix = "api-remote.py" if api else "remote.py"
    deployed = (ROOT / (".runtime/refundable-contract/main-" + suffix)).read_text(encoding="utf-8")
    local = (ROOT / "src/erp_api/main.py").read_text(encoding="utf-8")
    start = local.index("            refundable_assignment_client = None")
    end = local.index("            roster_client = FeishuSampleBatchClient(", start)
    first = local[start:end]
    marker = "            roster_client = FeishuSampleBatchClient("
    if deployed.count(marker) != 1:
        raise RuntimeError("Deployed roster construction differs from reviewed baseline")
    deployed = deployed.replace(marker, first + marker, 1)
    start = local.index("            if refundable_assignment_client is not None:")
    marker = "        if (\n            feishu_client is not None\n            and settings.feishu_event_verification_token"
    end = local.index(marker, start)
    if deployed.count(marker) != 1:
        raise RuntimeError("Deployed event construction differs from reviewed baseline")
    deployed = deployed.replace(marker, local[start:end] + marker, 1)
    compile(deployed, "main.py", "exec")
    (DESTINATION / "erp_api/main.py").write_text(deployed, encoding="utf-8")
    config = (ROOT / (".runtime/refundable-contract/config-" + suffix)).read_text(encoding="utf-8")
    marker = "    feishu_bd_assignment_record_table_id: str | None = None\n"
    if config.count(marker) != 1:
        raise RuntimeError("Deployed assignment config differs from reviewed baseline")
    config = config.replace(marker, marker +
        "    feishu_refundable_assignment_record_table_id: str | None = None\n"
        "    feishu_refundable_assignment_summary_table_id: str | None = None\n"
        "    feishu_refundable_sample_enabled: bool = False\n", 1)
    (DESTINATION / "erp_api/core").mkdir(exist_ok=True)
    (DESTINATION / "erp_api/core/config.py").write_text(config, encoding="utf-8")
    (DESTINATION / "scripts").mkdir(exist_ok=True)
    for name in ("sample_watch_freshness", "provision_refundable_sample_tables", "provision_refundable_summary"):
        shutil.copy2(ROOT / "scripts" / f"{name}.py", DESTINATION / "scripts")
    shutil.copy2(ROOT / "deploy/refundable-samples/Dockerfile", DESTINATION)
    print(f"REFUNDABLE_BUILD_READY modules={sum(len(names) for names in MODULES.values())}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", action="store_true")
    run(parser.parse_args().api)

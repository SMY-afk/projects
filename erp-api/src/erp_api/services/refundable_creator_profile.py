"""Verify actual @account and all five detail responses before using GMV."""

from datetime import datetime
from decimal import Decimal

from erp_api.services.affiliate_creator_marketplace_profile import (
    parse_marketplace_profile,
)
from erp_api.services.affiliate_creator_summary_parser import merge_profile_snapshots
from erp_api.services.sample_cooperation_parsing import normalize_account_name
from erp_api.services.refundable_identity_guard import quarantined_payload


def apply_refundable_profile(application, responses):
    if quarantined_payload(application):
        return
    if not isinstance(responses, list) or not responses:
        return
    if {tuple(row.get("request", {}).get("profile_types", [])) for row in responses if isinstance(row, dict)} != {(1,), (2,), (3,), (4,), (5,)}:
        return
    snapshots = {}
    source_ids = set()
    observations = []
    account = normalize_account_name(application["creator"]["username"])
    for row in responses:
        if not isinstance(row, dict):
            raise TypeError("Refundable profile evidence is invalid")
        observed = datetime.fromisoformat(row["observed_at"])
        if observed.tzinfo is None:
            raise ValueError("Refundable profile observation lacks timezone")
        summary = parse_marketplace_profile(row["payload"], row["request"], observed_at=observed)
        if summary is None:
            raise ValueError("Refundable profile contract is invalid")
        if summary.creator_username and normalize_account_name(summary.creator_username) != account:
            raise ValueError("Refundable profile @account does not match the application")
        source_ids.add(summary.platform_creator_id)
        snapshots[summary.resource_kind] = summary.profile_snapshot
        observations.append(observed)
    if len(source_ids) != 1 or source_ids != {application["creator"]["creator_open_id"]}:
        raise ValueError("Refundable profile source identity conflicts with the application")
    if set(snapshots) != {"profile", "performance", "followers", "trends", "examples"}:
        return
    snapshot = {}
    for kind in ("profile", "performance", "followers", "trends", "examples"):
        snapshot = merge_profile_snapshots(snapshot, snapshots[kind])
    snapshot["creator_details_complete"] = True
    creator = application["creator"]
    creator["verified_profile_snapshot"] = snapshot
    creator["verified_profile_observed_at"] = min(observations).isoformat()
    creator["follower_count"] = snapshot.get("follower_count")
    gmv = snapshot.get("sales", {}).get("gmv_minor")
    if type(gmv) is int and gmv >= 0:
        creator["gmv"] = {"amount": str(Decimal(gmv) / 100), "currency": "USD"}

"""Fail-closed validation of fresh, direct TikTok availability observations."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.daily_valid_creator_core import SHOP_LINES
from scripts.daily_valid_creator_dates import ShopCutoffs

# A verified TK availability date changes at most once per daily source window.
# Reuse it during the same operating shift; current browser/session health is
# checked independently by the automatic scheduler before an apply is queued.
MAX_EVIDENCE_AGE = timedelta(hours=6)


def validate_online_evidence(
    evidence: dict, cutoffs: ShopCutoffs, now: datetime | None = None
) -> None:
    """Require each shop's live TK dates to match the source windows exactly."""
    if evidence.get("source") != "direct_tk_sources":
        raise ValueError("Direct TK online evidence is required")
    rows = evidence.get("shops")
    if not isinstance(rows, list):
        raise TypeError("Online evidence shops must be a list")
    observed = {row.get("shop"): row for row in rows if isinstance(row, dict)}
    if len(rows) != len(SHOP_LINES) or set(observed) != set(SHOP_LINES):
        raise ValueError("Online evidence has a missing shop or duplicate shop")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    for name in SHOP_LINES:
        row = observed[name]
        try:
            observed_at = datetime.fromisoformat(row["observed_at"])
            if observed_at.tzinfo is None:
                raise ValueError("Naive observation time")
            age = current - observed_at.astimezone(UTC)
            online_dates = tuple(
                row[key] for key in ("creators", "videos", "liveAccounts")
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{name}: invalid direct TK online evidence") from error
        if age < -timedelta(seconds=30) or age > MAX_EVIDENCE_AGE:
            raise ValueError(f"{name}: direct TK online evidence is stale")
        expected = tuple(
            cutoffs[name][key].isoformat()
            for key in ("creators", "videos", "liveAccounts")
        )
        if online_dates != expected:
            raise ValueError(
                f"{name}: TK online cutoff mismatch "
                f"(creators={online_dates[0]}, videos={online_dates[1]}, "
                f"liveAccounts={online_dates[2]})"
            )


def load_online_evidence(path: str, cutoffs: ShopCutoffs) -> dict:
    evidence = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(evidence, dict):
        raise TypeError("Direct TK online evidence must be an object")
    validate_online_evidence(evidence, cutoffs)
    return evidence

from __future__ import annotations

from collections.abc import Mapping

_MONEY_FIELDS = (
    "gmv",
    "direct_gmv",
    "est_commission",
    "est_flat_fee",
    "refund_gmv",
    "main_aov",
    "product_gpm",
    "product_card_gmv",
    "product_card_est_commission",
    "showcase_gmv",
    "showcase_est_commission",
)


def creator_detail_currency(
    payload: Mapping[str, object], fallback: object = None
) -> str | None:
    data = payload.get("data")
    segments = data.get("segments") if isinstance(data, Mapping) else None
    if isinstance(segments, list):
        for segment in segments:
            for stat in _stats(segment):
                for field_name in _MONEY_FIELDS:
                    value = stat.get(field_name)
                    if not isinstance(value, Mapping):
                        continue
                    candidate = value.get("currency_code", value.get("currency"))
                    normalized = _currency(candidate)
                    if normalized:
                        return normalized
    return _currency(fallback)


def _stats(segment: object) -> list[Mapping[str, object]]:
    if not isinstance(segment, Mapping):
        return []
    timed_lists = segment.get("timed_lists")
    if not isinstance(timed_lists, list):
        return []
    return [
        stat
        for timed in timed_lists
        if isinstance(timed, Mapping) and isinstance(timed.get("stats"), list)
        for stat in timed["stats"]
        if isinstance(stat, Mapping)
    ]


def _currency(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    return normalized if len(normalized) == 3 and normalized.isalpha() else None

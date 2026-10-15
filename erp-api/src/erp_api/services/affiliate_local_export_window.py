from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta


@dataclass(frozen=True)
class AffiliateExportWindows:
    creators: tuple[date, date]
    videos: tuple[date, date]
    live_accounts: tuple[date, date]

    def as_dict(self) -> dict[str, dict[str, str]]:
        return {
            "creators": _window_dict(self.creators),
            "videos": _window_dict(self.videos),
            "liveAccounts": _window_dict(self.live_accounts),
        }


def resolve_export_windows(
    window_start: date,
    window_end: date,
    latest_dates: dict[str, date],
) -> AffiliateExportWindows:
    creators = resolve_shop_window(
        window_start,
        window_end,
        latest_dates.get("creators"),
    )
    return AffiliateExportWindows(
        creators=creators,
        videos=resolve_shop_window(
            window_start,
            window_end,
            latest_dates.get("videos"),
        ),
        live_accounts=resolve_shop_window(
            window_start,
            window_end,
            latest_dates.get("liveAccounts"),
        ),
    )


def resolve_shop_window(
    window_start: date,
    window_end: date,
    latest_available_date: date | None,
) -> tuple[date, date]:
    if latest_available_date is None or latest_available_date >= window_end:
        return window_start, window_end
    if window_start == window_end - relativedelta(months=2):
        return latest_available_date - relativedelta(months=2), latest_available_date
    shift = window_end - latest_available_date
    return window_start - shift, latest_available_date


def _window_dict(window: tuple[date, date]) -> dict[str, str]:
    return {"from": window[0].isoformat(), "to": window[1].isoformat()}

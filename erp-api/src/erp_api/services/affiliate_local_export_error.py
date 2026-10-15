from __future__ import annotations

from datetime import date


class AffiliateLocalExportError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "affiliate_export_conflict",
        shop: str | None = None,
        resource: str | None = None,
        window: tuple[date, date] | None = None,
        missing_dates: tuple[date, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.shop = shop
        self.resource = resource
        self.window = window
        self.missing_dates = missing_dates

    @classmethod
    def incomplete_snapshot(
        cls,
        shop: str,
        resource: str,
        window: tuple[date, date],
        missing_dates: tuple[date, ...] = (),
    ) -> AffiliateLocalExportError:
        resource_name = {"creators": "达人", "videos": "视频"}.get(resource, resource)
        date_text = "、".join(item.isoformat() for item in missing_dates)
        suffix = f"，缺失日期：{date_text}" if date_text else ""
        message = (
            f"{shop}的{resource_name}数据不完整：{window[0].isoformat()} 至 "
            f"{window[1].isoformat()} 没有可用的完整快照{suffix}。"
        )
        return cls(
            message,
            code="affiliate_snapshot_incomplete",
            shop=shop,
            resource=resource,
            window=window,
            missing_dates=missing_dates,
        )

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"code": self.code, "message": str(self)}
        if self.shop is not None:
            payload["shop"] = self.shop
        if self.resource is not None:
            payload["resource"] = self.resource
        if self.window is not None:
            payload["window"] = {
                "from": self.window[0].isoformat(),
                "to": self.window[1].isoformat(),
            }
        if self.code == "affiliate_snapshot_incomplete":
            payload["missingDates"] = [item.isoformat() for item in self.missing_dates]
        return payload

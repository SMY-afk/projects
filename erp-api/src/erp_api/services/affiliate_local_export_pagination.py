from collections.abc import Awaitable, Callable, Mapping

from erp_api.services.affiliate_local_export_error import AffiliateLocalExportError

CENTER_PAGE_SIZE = 100_000
LIVE_PAGE_SIZE = 100
MAX_PAGES = 10_000


async def all_pages(
    loader: Callable[[int], Awaitable[Mapping[str, object]]],
    label: str,
    *,
    snapshot_key: str,
    snapshot_error: AffiliateLocalExportError,
) -> tuple[list[Mapping[str, object]], int]:
    rows: list[Mapping[str, object]] = []
    expected_total: int | None = None
    for page in range(1, MAX_PAGES + 1):
        payload = await loader(page)
        if page == 1 and not isinstance(payload.get(snapshot_key), Mapping):
            raise snapshot_error
        items = payload.get("items")
        total = payload.get("total")
        if not isinstance(items, list) or not _valid_total(total):
            raise AffiliateLocalExportError(
                f"{label} returned invalid pagination data."
            )
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise AffiliateLocalExportError(f"{label} changed total during export.")
        rows.extend(item for item in items if isinstance(item, Mapping))
        if len(rows) == expected_total:
            return rows, expected_total
        if not items or len(rows) > expected_total:
            break
    raise AffiliateLocalExportError(
        f"{label} export is incomplete: captured={len(rows)}, total={expected_total}."
    )


async def all_live_pages(
    tenant_id, shop_id, window_start, window_end, repository, label
):
    rows = []
    expected_total = None
    for page in range(1, MAX_PAGES + 1):
        result = await repository.list_page(
            tenant_id,
            shop_id,
            page=page,
            page_size=LIVE_PAGE_SIZE,
            sort_by="startedAt",
            sort_order="desc",
            account_type="AFFILIATE_ACCOUNTS",
            window_start=window_start,
            window_end=window_end,
        )
        if not _valid_total(result.total) or not isinstance(result.items, list):
            raise AffiliateLocalExportError(
                f"{label} returned invalid pagination data."
            )
        if expected_total is None:
            expected_total = result.total
        elif result.total != expected_total:
            raise AffiliateLocalExportError(f"{label} changed total during export.")
        rows.extend(result.items)
        if len(rows) == expected_total:
            return rows, expected_total
        if not result.items or len(rows) > expected_total:
            break
    raise AffiliateLocalExportError(
        f"{label} export is incomplete: captured={len(rows)}, total={expected_total}."
    )


def _valid_total(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0

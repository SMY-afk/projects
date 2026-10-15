from types import SimpleNamespace

from erp_api.services.tiktok_platform_logistics_sync_persistence import (
    update_package_and_waybill,
)
from erp_api.services.tiktok_platform_logistics_sync_records import (
    merge_task_status,
    task_status,
)


class _Cipher:
    def encrypt(self, value):
        return f"encrypted:{value}"

    def fingerprint(self, namespace, value):
        return f"{namespace}:{value}"


def _detail(**overrides):
    values = {
        "package_status": "FULFILLING",
        "tracking_number": "REAL-TRACKING",
        "updated_at": None,
        "weight_grams": None,
        "length_mm": None,
        "width_mm": None,
        "height_mm": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_platform_refresh_does_not_regress_delivered_tracking_state() -> None:
    package = SimpleNamespace(status="shipped")
    waybill = SimpleNamespace(status="delivered", tracking_status="delivered")

    update_package_and_waybill(
        package,
        waybill,
        "carrier-id",
        "IN_TRANSIT",
        _detail(),
        _Cipher(),
    )

    assert waybill.status == "delivered"
    assert merge_task_status("delivered", "IN_TRANSIT") == "delivered"


def test_explicit_platform_cancellation_still_wins() -> None:
    package = SimpleNamespace(status="shipped")
    waybill = SimpleNamespace(status="delivered", tracking_status="delivered")

    update_package_and_waybill(
        package,
        waybill,
        "carrier-id",
        "IN_TRANSIT",
        _detail(package_status="CANCELLED"),
        _Cipher(),
    )

    assert package.status == "cancelled"
    assert waybill.status == "cancelled"


def test_awaiting_shipment_maps_to_pending_dispatch() -> None:
    assert task_status("AWAITING_SHIPMENT") == "pending_dispatch"
    assert merge_task_status("pending_review", "AWAITING_SHIPMENT") == (
        "pending_dispatch"
    )

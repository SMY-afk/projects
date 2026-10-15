import pytest

from erp_api.services.tiktok_order_schemas import parse_order


def raw_order(packages, lines, provider=None):
    return {"id": "order-1", "status": "IN_TRANSIT", "create_time": 1_700_000_000,
            "update_time": 1_700_000_100, "packages": packages,
            "line_items": lines, "shipping_provider": provider}


def test_carriers_are_matched_by_package_id_from_official_order_lines():
    order = parse_order(raw_order([{"id": "p1"}, {"id": "p2"}], [
        {"id": "l2", "package_id": "p2", "shipping_provider_name": "FedEx"},
        {"id": "l1", "package_id": "p1", "shipping_provider_name": "USPS"},
    ], "Unrelated order provider"))
    assert [(p.platform_package_id, p.carrier) for p in order.fulfillments] == [
        ("p1", "USPS"), ("p2", "FedEx")]


@pytest.mark.parametrize("provider", [None, "Order Carrier"])
def test_conflicting_package_line_carriers_remain_unknown(provider):
    order = parse_order(raw_order([{"id": "p1"}], [
        {"id": "l1", "package_id": "p1", "shipping_provider_name": "USPS"},
        {"id": "l2", "package_id": "p1", "shipping_provider_name": "FedEx"},
    ], provider))
    assert order.fulfillments[0].carrier is None


def test_multi_package_order_does_not_copy_another_packages_carrier():
    order = parse_order(raw_order([{"id": "p1"}, {"id": "p2"}], [
        {"id": "l1", "package_id": "p1", "shipping_provider_name": "USPS"},
    ], "USPS"))
    assert [p.carrier for p in order.fulfillments] == ["USPS", None]


def test_single_package_uses_official_order_provider_when_no_line_carrier_exists():
    order = parse_order(raw_order([{"id": "p1"}], [], " FedEx "))
    assert order.fulfillments[0].carrier == "FedEx"


def test_explicit_package_name_is_preserved_over_line_fallback():
    order = parse_order(raw_order([{"id": "p1", "shipping_provider_name": " UPS "}], [
        {"id": "l1", "package_id": "p1", "shipping_provider_name": "USPS"},
    ]))
    assert order.fulfillments[0].carrier == "UPS"

import inspect

from erp_api.services.logistics_dispatch_repository import (
    LogisticsDispatchRepository,
)


def test_dispatch_transaction_has_required_aggregate_and_audit_updates() -> None:
    source = inspect.getsource(LogisticsDispatchRepository.dispatch)

    for value in (
        'package.status = "shipped"',
        'waybill.status = "shipped"',
        "task.status = (",
        'operation_type="package_dispatched"',
        "_create_platform_callback(",
        "await session.commit()",
    ):
        assert value in source
    assert source.count("await session.commit()") == 1


def test_dispatch_repository_does_not_touch_erp_inventory_or_product_stock() -> None:
    source = inspect.getsource(LogisticsDispatchRepository)

    assert not any(
        value in source
        for value in (
            "Product",
            "ProductSku",
            "products.stock",
            "product_skus.stock",
            "Inventory",
            "Warehouse",
        )
    )

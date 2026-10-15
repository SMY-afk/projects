from erp_api.main import create_app


def test_dashboard_snapshot_route_is_registered() -> None:
    paths = {route.path for route in create_app().routes}

    assert "/api/dashboard/snapshot" in paths
    assert "/api/dashboard/affiliate-rankings" in paths

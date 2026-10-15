from erp_api.services.tiktok_scope_status import evaluate_scope_status


def test_scope_status_returns_required_minus_granted_scopes() -> None:
    status = evaluate_scope_status(
        granted_scopes=["seller.shop.info", "data.shop_analytics.public.read"],
        required_scopes=[
            "data.bestselling.public.read",
            "seller.shop.info",
        ],
    )

    assert status.required_scopes == (
        "data.bestselling.public.read",
        "seller.shop.info",
    )
    assert status.granted_scopes == (
        "data.shop_analytics.public.read",
        "seller.shop.info",
    )
    assert status.missing_scopes == ("data.bestselling.public.read",)
    assert status.reauthorization_required is True


def test_scope_status_is_ready_when_all_required_scopes_are_granted() -> None:
    status = evaluate_scope_status(
        granted_scopes=["data.bestselling.public.read"],
        required_scopes=["data.bestselling.public.read"],
    )

    assert status.missing_scopes == ()
    assert status.reauthorization_required is False

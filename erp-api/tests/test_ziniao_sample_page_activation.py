import pytest

import backend.app.services.ziniao_sample_list_selenium as sample_list_module


def _target(target_id: str, *, shop_id: str = "shop-one") -> dict[str, str]:
    return {
        "id": target_id,
        "type": "page",
        "url": (
            "https://affiliate-us.tiktok.com/affiliate/sample/"
            f"sample-request?shop_id={shop_id}"
        ),
        "webSocketDebuggerUrl": f"ws://127.0.0.1/devtools/page/{target_id}",
    }


def test_activation_skips_unresponsive_duplicate_and_selects_ready_page(
    monkeypatch,
) -> None:
    targets = [_target("stuck"), _target("ready"), _target("other", shop_id="other")]
    activated = []
    closed = []
    monkeypatch.setattr(sample_list_module, "_cdp_page_targets", lambda _port: targets)
    monkeypatch.setattr(
        sample_list_module,
        "_page_ready",
        lambda target: target["id"] == "ready",
    )
    monkeypatch.setattr(
        sample_list_module,
        "_activate_target",
        lambda port, target_id: activated.append((port, target_id)),
    )
    monkeypatch.setattr(
        sample_list_module,
        "_close_target",
        lambda port, target_id: closed.append((port, target_id)),
    )

    selected = sample_list_module.activate_responsive_sample_page(59802, "shop-one")

    assert selected == "ready"
    assert activated == [(59802, "ready")]
    assert closed == [(59802, "stuck")]


def test_activation_fails_closed_when_no_sample_page_responds(monkeypatch) -> None:
    closed = []
    monkeypatch.setattr(
        sample_list_module, "_cdp_page_targets", lambda _port: [_target("stuck")]
    )
    monkeypatch.setattr(sample_list_module, "_page_ready", lambda _target: False)
    monkeypatch.setattr(
        sample_list_module,
        "_close_target",
        lambda port, target_id: closed.append((port, target_id)),
    )

    with pytest.raises(RuntimeError, match="responsive"):
        sample_list_module.activate_responsive_sample_page(59802, "shop-one")

    assert closed == []

from types import SimpleNamespace

from erp_api import __main__


def test_main_disables_access_log_to_protect_oauth_query_credentials(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    settings = SimpleNamespace(api_host="127.0.0.1", api_port=8080, api_reload=False)

    monkeypatch.setattr(__main__, "get_settings", lambda: settings)
    monkeypatch.setattr(
        __main__.uvicorn,
        "run",
        lambda app, **kwargs: captured.update(app=app, **kwargs),
    )

    __main__.main()

    assert captured == {
        "app": "erp_api.main:app",
        "host": "127.0.0.1",
        "port": 8080,
        "reload": False,
        "access_log": False,
    }

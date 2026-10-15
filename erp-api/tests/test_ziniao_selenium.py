from pathlib import Path

import pytest

from erp_api.services.ziniao_selenium import (
    ZiniaoSeleniumError,
    attach_selenium,
    detach_selenium,
)
from erp_api.services.ziniao_webdriver_client import ZiniaoBrowserSession


def _session(tmp_path: Path) -> ZiniaoBrowserSession:
    return ZiniaoBrowserSession(
        debugging_port=45678,
        core_version="192.0.2.1",
        core_type="Chromium",
        download_path=tmp_path,
    )


def test_attaches_to_exact_debugger_address(monkeypatch, tmp_path) -> None:
    driver_path = tmp_path / "chromedriver.exe"
    driver_path.touch()
    captured = {}

    class Driver:
        def __init__(self):
            self.capabilities = {"browserVersion": "119.0.6045.160"}

    def chrome(*, service, options):
        captured["service"] = service
        captured["options"] = options
        return Driver()

    monkeypatch.setattr("erp_api.services.ziniao_selenium.webdriver.Chrome", chrome)
    driver = attach_selenium(_session(tmp_path), driver_path)

    assert isinstance(driver, Driver)
    assert captured["options"].experimental_options["debuggerAddress"] == (
        "127.0.0.1:45678"
    )
    assert captured["options"].page_load_strategy == "none"
    assert Path(captured["service"].path) == driver_path.resolve()


def test_rejects_mismatched_chromedriver_version(monkeypatch, tmp_path) -> None:
    driver_path = tmp_path / "chromedriver.exe"
    driver_path.touch()

    class Driver:
        def __init__(self):
            self.capabilities = {"browserVersion": "192.0.2.1"}
            self.quit_called = False

        def quit(self):
            self.quit_called = True

    driver = Driver()
    monkeypatch.setattr(
        "erp_api.services.ziniao_selenium.webdriver.Chrome", lambda **_kwargs: driver
    )

    with pytest.raises(ZiniaoSeleniumError, match="version"):
        attach_selenium(_session(tmp_path), driver_path)
    assert driver.quit_called is True


def test_requires_explicit_chromedriver_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="ChromeDriver"):
        attach_selenium(_session(tmp_path), tmp_path / "missing.exe")


def test_performance_logging_is_opt_in(monkeypatch, tmp_path) -> None:
    driver_path = tmp_path / "chromedriver.exe"
    driver_path.touch()
    captured = {}

    class Driver:
        def __init__(self):
            self.capabilities = {"browserVersion": "192.0.2.1"}

    def chrome(*, service, options):
        captured["options"] = options
        return Driver()

    monkeypatch.setattr("erp_api.services.ziniao_selenium.webdriver.Chrome", chrome)
    attach_selenium(_session(tmp_path), driver_path, performance_logs=True)

    assert captured["options"].capabilities["goog:loggingPrefs"] == {
        "performance": "ALL"
    }


def test_detach_does_not_quit_browser() -> None:
    calls = []

    class Closeable:
        def close(self):
            calls.append("executor-close")

    class Stoppable:
        def stop(self):
            calls.append("service-stop")

    class Driver:
        command_executor = Closeable()
        service = Stoppable()

        def quit(self):
            calls.append("quit")

    detach_selenium(Driver())

    assert calls == ["executor-close", "service-stop"]

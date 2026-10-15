from __future__ import annotations

from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.service import Service

from erp_api.services.ziniao_webdriver_client import ZiniaoBrowserSession


class ZiniaoSeleniumError(RuntimeError):
    pass


def attach_selenium(
    session: ZiniaoBrowserSession,
    chromedriver_path: str | Path,
    *,
    performance_logs: bool = False,
) -> Any:
    if session.core_type.casefold() not in {"chrome", "chromium"}:
        raise ValueError("Ziniao Selenium requires a Chromium browser core.")
    driver_path = Path(chromedriver_path).expanduser().resolve()
    if not driver_path.is_file():
        raise ValueError("A matching ChromeDriver file is required.")

    options = webdriver.ChromeOptions()
    options.page_load_strategy = "none"
    options.add_experimental_option("debuggerAddress", session.debugger_address)
    if performance_logs:
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    try:
        driver = webdriver.Chrome(
            service=Service(executable_path=str(driver_path)),
            options=options,
        )
    except WebDriverException as error:
        raise ZiniaoSeleniumError("Could not attach Selenium to Ziniao.") from error

    actual_version = str(driver.capabilities.get("browserVersion") or "")
    actual_major = actual_version.partition(".")[0]
    if actual_major != str(session.core_major_version):
        driver.quit()
        raise ZiniaoSeleniumError(
            "Ziniao browser and ChromeDriver version did not match."
        )
    return driver


def detach_selenium(driver: Any) -> None:
    """Detach ChromeDriver without closing the externally owned browser."""
    try:
        driver.command_executor.close()
    except Exception:  # noqa: BLE001,S110 -- browser must remain open
        pass
    try:
        driver.service.stop()
    except Exception:  # noqa: BLE001,S110 -- browser must remain open
        pass

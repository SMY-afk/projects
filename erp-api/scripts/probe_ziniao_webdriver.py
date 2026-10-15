from __future__ import annotations

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.ziniao_webdriver_client import (
    ZiniaoCredentials,
    ZiniaoWebDriverClient,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely list or start a Ziniao WebDriver browser."
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the exact browser configured by ZINIAO_AKELEO_BROWSER_NAME.",
    )
    return parser.parse_args()


def _credentials(settings) -> ZiniaoCredentials:
    if not (
        settings.ziniao_company
        and settings.ziniao_username
        and settings.ziniao_password
    ):
        raise ValueError("Ziniao WebDriver credentials are not configured.")
    return ZiniaoCredentials(
        settings.ziniao_company,
        settings.ziniao_username,
        settings.ziniao_password.get_secret_value(),
    )


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    credentials = _credentials(settings)
    async with ZiniaoWebDriverClient(settings.ziniao_webdriver_url) as client:
        browsers = await client.list_browsers(credentials)
        if not arguments.start:
            return {
                "status": "listed",
                "items": [
                    {
                        "name": browser.name,
                        "siteId": browser.site_id,
                        "platformName": browser.platform_name,
                    }
                    for browser in browsers
                ],
            }
        target_name = (settings.ziniao_akeleo_browser_name or "").strip()
        matches = [browser for browser in browsers if browser.name == target_name]
        if len(matches) != 1:
            raise ValueError("Configured Ziniao browser name must match exactly once.")
        session = await client.start_browser(
            credentials,
            browser_oauth=matches[0].oauth,
        )
        return {
            "status": "started",
            "browserName": matches[0].name,
            "debuggingPort": session.debugging_port,
            "coreType": session.core_type,
            "coreVersion": session.core_version,
        }


def main() -> None:
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

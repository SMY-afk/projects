import asyncio

from backend.app.services import local_browser_security as security


def test_login_target_is_expired_even_before_renderer_navigation():
    assert (
        asyncio.run(
            security._page_state(
                {
                    "url": "https://seller.tiktokshopglobalselling.com/account/login",
                }
            )
        )
        == "session_expired"
    )


def test_missing_renderer_is_not_online():
    assert (
        asyncio.run(
            security._page_state(
                {
                    "url": "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request",
                }
            )
        )
        == "connecting"
    )


def test_captcha_target_never_attaches_or_navigates():
    assert (
        asyncio.run(
            security._page_state(
                {
                    "url": "https://affiliate.tiktokshopglobalselling.com/captcha",
                }
            )
        )
        == "captcha"
    )

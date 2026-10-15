"""Prepare original owned exports or one explicitly approved existing video tab."""

from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    page_security_failure,
)
from backend.app.services.tiktok_affiliate_intent_page import (
    PreparedIntentPage,
    _prepare_trigger,
    _resource_page_url,
)
from backend.app.services.tiktok_affiliate_scheduled_creator_page import (
    close_owned_page,
)

HOSTS = {"affiliate-us.tiktok.com", "affiliate.tiktokshopglobalselling.com"}
VIDEO_PATHS = {"/affiliate/assets/video-analysis", "/insights/video-analysis"}


def _same_video_shop(url, platform_shop_id):
    split = urlsplit(url)
    return (split.hostname in HOSTS and split.path in VIDEO_PATHS
            and parse_qs(split.query).get("shop_id") == [platform_shop_id])


async def _no_op():
    pass


async def _prepare_video_export_trigger(page, platform_shop_id):
    if not _same_video_shop(page.url, platform_shop_id):
        raise RuntimeError("Affiliate export page changed shop or resource identity")
    security = await page_security_failure(page)
    if security is not None:
        raise RuntimeError("Affiliate export page blocked: " + security[1])
    if not _same_video_shop(page.url, platform_shop_id):
        raise RuntimeError("Affiliate export page changed shop or resource identity")
    # download_video_export selects and validates the original export task window.
    return _no_op


async def _existing_video_page(context, platform_shop_id, approved_target_id):
    matches = []
    for page in context.pages:
        if not _same_video_shop(page.url, platform_shop_id):
            continue
        session = await context.new_cdp_session(page)
        try:
            target = (await session.send("Target.getTargetInfo")).get("targetInfo", {})
            if (target.get("targetId") == approved_target_id
                    and _same_video_shop(target.get("url", ""), platform_shop_id)):
                matches.append(page)
        finally:
            await session.detach()
    if len(matches) != 1:
        raise RuntimeError("Exact approved analytics video target is missing or ambiguous")
    return matches[0]


async def _prepare_reused_page(context, query, platform_shop_id, approved_target_id):
    if query.resource.value != "videos":
        raise RuntimeError("Approved analytics target reuse is limited to video exports")
    page = await _existing_video_page(context, platform_shop_id, approved_target_id)
    trigger = await _prepare_video_export_trigger(page, platform_shop_id)
    return PreparedIntentPage(page, query, trigger, _no_op)


async def prepare_export_page(context, query, platform_shop_id, *,
                              approved_page_target_id=None):
    if approved_page_target_id is not None:
        return await _prepare_reused_page(context, query, platform_shop_id,
                                         approved_page_target_id)
    page = await context.new_page()
    try:
        url = _resource_page_url([context], query.resource.value, platform_shop_id)
        split = urlsplit(url)
        if split.hostname not in HOSTS:
            raise RuntimeError("Affiliate export host is not approved")
        params = parse_qs(split.query)
        params["shop_id"] = [platform_shop_id]
        url = urlunsplit(
            (split.scheme, split.netloc, split.path, urlencode(params, doseq=True), "")
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if parse_qs(urlsplit(page.url).query).get("shop_id") != [platform_shop_id]:
            raise RuntimeError("Affiliate export page changed shop identity")
        trigger = (
            await _prepare_video_export_trigger(page, platform_shop_id)
            if query.resource.value == "videos" else await _prepare_trigger(page, query)
        )

        async def cleanup():
            try:
                if hasattr(trigger, "cleanup"):
                    await trigger.cleanup()
            finally:
                await close_owned_page(page)

        return PreparedIntentPage(page, query, trigger, cleanup)
    except Exception:
        await close_owned_page(page)
        raise

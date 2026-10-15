"""Recover only exact-shop known creator avatars within sample-priority browser guards."""
import argparse
import asyncio
import json
import platform
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

platform._wmi = None
from playwright.async_api import async_playwright
from backend.app.services.hubstudio_attached_browser import connect_attached_hubstudio_browser
from backend.app.services.hubstudio_cdp import discover_hubstudio_cdp_url, read_cdp_platform_shop_ids, normalize_loopback_cdp_url
from backend.app.services.tiktok_affiliate_creator_identity_sample import (
    _batch_request_body, _fetch_identity_batch, prepare_creator_identity_source)
from backend.app.services.tiktok_affiliate_creator_identity_collector import pagination
from backend.app.services.tiktok_affiliate_creator_payload import extract_creator_payload_dimensions
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery, AffiliateCenterResource
from erp_api.services.affiliate_creator_metric_parser import parse_creator_page_payload
from scripts.affiliate_avatar_images import download_avatars
from scripts.local_capture_guard import CaptureGuardError, browser_work, ensure_browser_ready
from scripts.run_remote_sample_capture_loop import SHOPS
from scripts.sample_capture_priority import refresh_official_free, run_secondary, secondary_budget
from scripts.send_local_affiliate_export import _prepare_owned_page
from scripts.ziniao_affiliate_export_source import resolve_ziniao_export_source


def save(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)


def windows(shop):
    end, start = date.fromisoformat(shop["latest"]), date.fromisoformat(shop["earliest"])
    result = []
    while end >= start:
        lower = max(start, end - timedelta(days=29))
        result.append((lower, end))
        end = lower - timedelta(days=1)
    return result


async def collect(args, shop):
    label = args.shop_label
    if label == "local":
        endpoint, environment = await resolve_ziniao_export_source(shop["platformShopId"])
    else:
        shop_id, environment, platform_id = SHOPS[label]
        assert shop_id == shop["shopId"] and platform_id == shop["platformShopId"], "avatar_shop_config_mismatch"
        endpoints = args.output / "verified-endpoints.json"
        observed = json.loads(endpoints.read_text()).get(label) if endpoints.exists() else None
        cached = normalize_loopback_cdp_url(args.cdp_url or observed)
        endpoint = cached if cached and await read_cdp_platform_shop_ids(cached) == frozenset({platform_id}) else await discover_hubstudio_cdp_url(current_url=None, expected_platform_shop_id=platform_id)
    if not endpoint:
        raise CaptureGuardError("verified_shop_browser_unavailable")
    assert await read_cdp_platform_shop_ids(endpoint) == frozenset({shop["platformShopId"]}), "avatar_shop_cdp_mismatch"
    await ensure_browser_ready(label, endpoint)
    root = args.output / label
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"window": 0, "page": 0, "sources": {}, "images": {}, "missing": [], "failures": []}
    external = args.output / "downloads" / (label + ".json")
    if external.exists():
        state["images"].update(json.loads(external.read_text()))
    known = {r["usernameNormalized"]: r for r in shop["targets"]}
    known_ids = {}
    for target in shop["targets"]:
        if target.get("platformCreatorId"):
            known_ids.setdefault(target["platformCreatorId"], []).append(target["usernameNormalized"])
    planned = windows(shop)
    pending = [r for name, r in state["sources"].items() if name not in state["images"] and name not in state["missing"]]
    if state["window"] >= len(planned) and not pending and not args.retry_missing:
        print(f"AVATAR_SCAN_COMPLETE shop={label} cached={len(state['images'])}", flush=True)
        return
    index = min(state["window"], len(planned) - 1)
    start, end = planned[index]
    query = AffiliateCenterQuery(resource=AffiliateCenterResource.CREATORS,
        shop_id=UUID(shop["shopId"]), window_start=start, window_end=end,
        shop_timezone=shop["timezone"], currency=shop["currency"], filters={})
    async with async_playwright() as playwright:
        browser = await connect_attached_hubstudio_browser(playwright, endpoint)
        contexts = [c for c in browser.contexts if any(parse_qs(urlsplit(p.url).query).get("shop_id") == [shop["platformShopId"]] for p in c.pages)]
        assert len(contexts) == 1, "creator_context_ambiguous"
        context = contexts[0]
        prepared = None
        try:
            pending = [r for name, r in state["sources"].items() if name not in state["images"] and name not in state["missing"]]
            captured_source = False
            if state["window"] < len(planned):
                template_path = root / f"request-{start}-{end}.json"
                template = json.loads(template_path.read_text()) if template_path.exists() and time.time() - template_path.stat().st_mtime < 1800 else None
                existing = next((p for p in context.pages if urlsplit(p.url).hostname in {"affiliate-us.tiktok.com", "affiliate.tiktokshopglobalselling.com"}), None)
                if template and existing:
                    from types import SimpleNamespace
                    source = SimpleNamespace(request_url=template["url"], request_body=template["body"], first_payload=None)
                    source_page = existing
                else:
                    prepared = await _prepare_owned_page(context, query, shop["platformShopId"])
                    source_page = prepared.page
                for attempt in range(3) if not template or not existing else []:
                    source = await prepare_creator_identity_source(source_page, prepared.trigger)
                    dimension = extract_creator_payload_dimensions(source.first_payload, [])
                    if dimension.platform_shop_id == shop["platformShopId"] and dimension.window_start == start and dimension.query_window_end(query) == end:
                        break
                    print(f"AVATAR_STALE_WINDOW shop={label} expected={start}/{end} actual={dimension.window_start}/{dimension.window_end}", flush=True)
                    await asyncio.sleep(0.5)
                else:
                    if not template or not existing:
                        raise RuntimeError("creator_bound_window_unavailable")
                save(template_path, {"url": source.request_url, "body": source.request_body})
                capture_started = time.monotonic()
                for _ in range(max(args.source_pages, 50)):
                    number = state["page"]
                    payload = source.first_payload if number == 0 and source.first_payload is not None else await _fetch_identity_batch(source_page, source.request_url, _batch_request_body(source.request_body, number))
                    dimension = extract_creator_payload_dimensions(payload, [])
                    assert dimension.platform_shop_id == shop["platformShopId"], "creator_response_shop_mismatch"
                    assert dimension.window_start == start and dimension.query_window_end(query) == end, "creator_response_window_mismatch"
                    for record in parse_creator_page_payload(payload, query=query):
                        identifier = record.source_identifiers.get("tiktok_page_creator_id")
                        names = set(known_ids.get(identifier, []))
                        if record.username_normalized in known and known[record.username_normalized].get("platformCreatorId") in {None, identifier}:
                            names.add(record.username_normalized)
                        for name in names:
                            if known[name]["cached"] or name in state["images"]:
                                continue
                            if record.avatar_url:
                                state["sources"][name] = {"name": name, "url": record.avatar_url,
                                    "sourceIdentity": record.source_identifiers, "observedAt": datetime.now(UTC).isoformat()}
                    more, total = pagination(payload)
                    state["page"] = number + 1
                    save(state_path, state)
                    if not more:
                        state["window"] += 1
                        state["page"] = 0
                        break
                    if time.monotonic() - capture_started > 55:
                        break
                    await asyncio.sleep(0.35)
                print(f"AVATAR_SOURCE shop={label} window={index+1}/{len(planned)} page={number+1} total={total} matched={len(state['sources'])}", flush=True)
                pending = [r for name, r in state["sources"].items() if name not in state["images"] and name not in state["missing"]]
                captured_source = True
            if captured_source:
                save(state_path, state)
                print(f"AVATAR_SOURCE_READY shop={label} pending={len(pending)}", flush=True)
                return
            if label == "local":
                save(state_path, state)
                print(f"AVATAR_SOURCE_ONLY shop={label} pending={len(pending)}", flush=True)
                return
            completed = 0
            def on_image(name, image):
                nonlocal completed
                state["images"][name] = dict(image, username=name, sourceIdentity=state["sources"][name]["sourceIdentity"])
                completed += 1
                if completed % 12 == 0:
                    save(state_path, state)
            failures = await download_avatars(context, pending[:args.batch_size], args.output / "images", on_image)
            state["failures"] = failures
            if failures:
                print(f"AVATAR_IMAGE_FAILURES shop={label} count={len(failures)} reason={failures[0]['error']}", flush=True)
                state["missing"].extend(r["name"] for r in failures if r["error"].startswith("http_"))
            save(state_path, state)
            print(f"AVATAR_CACHED shop={label} count={len(state['images'])} pending={max(0,len(pending)-args.batch_size)}", flush=True)
        finally:
            if prepared:
                await prepared.cleanup()


async def main(args):
    audit = json.loads(args.audit.read_text())
    shop_id = str(args.shop_id)
    shop = next(s for s in audit["shops"] if s["shopId"] == shop_id)
    deadline = time.monotonic() + args.wait_seconds
    while True:
        try:
            if args.shop_label == "local":
                await asyncio.to_thread(refresh_official_free)
            if not secondary_budget(args.shop_label):
                raise CaptureGuardError("free_priority_wait")
            with browser_work(args.shop_label):
                await run_secondary(args.shop_label, lambda: collect(args, shop))
            return
        except CaptureGuardError as error:
            print(f"AVATAR_DEFER shop={args.shop_label} reason={error.code}", flush=True)
            if error.code in {"captcha", "session_expired"} or time.monotonic() >= deadline:
                raise
            await asyncio.sleep(15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shop-label", required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--source-pages", type=int, default=4)
    parser.add_argument("--wait-seconds", type=int, default=300)
    parser.add_argument("--retry-missing", action="store_true")
    parser.add_argument("--cdp-url")
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as error:
        import re
        message = str(error)
        code = getattr(error, "code", None) or (message if re.fullmatch(r"[a-z][a-z0-9_]{1,100}", message) else "unclassified")
        print(f"AVATAR_ERROR type={type(error).__name__} code={code}", flush=True)
        raise SystemExit(1) from None

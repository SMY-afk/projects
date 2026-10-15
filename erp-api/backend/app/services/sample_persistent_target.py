"""Durable ownership for the approved shop's reusable collection pages."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PERSISTENT_PLATFORM_SHOPS = frozenset({
    "9121478993551097445", "9768147009521852682",
    "9622543325839925006", "9472478445887813622",
})
PAID_PLATFORM_SHOPS = PERSISTENT_PLATFORM_SHOPS | frozenset({
    "9136806951995371293", "9622543325839925006",
    "9768147009521852682", "9472478445887813622",
})
ROOT = Path(__file__).resolve().parents[3] / ".runtime/sample-owned-pages"
HOST = "affiliate.tiktokshopglobalselling.com"


def persistent_sample_key(platform_shop_id, purpose="free"):
    if purpose not in {"free", "refundable"}:
        raise ValueError("Unknown persistent sample page purpose")
    if platform_shop_id in PERSISTENT_PLATFORM_SHOPS:
        return platform_shop_id, "free"
    if purpose == "refundable" and platform_shop_id in PAID_PLATFORM_SHOPS:
        return platform_shop_id, purpose
    return None


class PersistentSampleTarget:
    def __init__(self, key, browser_endpoint, *, root=None):
        self.shop, self.purpose = key
        self.browser = hashlib.sha256(browser_endpoint.encode()).hexdigest()
        name = hashlib.sha256(f"{self.shop}:{self.purpose}".encode()).hexdigest()
        self.path = (root or ROOT) / f"{name}.json"

    def resolve(self, targets):
        try:
            row = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            raise RuntimeError("owned_page_registry_invalid") from error
        if (
            not isinstance(row, dict)
            or row.get("shop") != self.shop
            or row.get("purpose") != self.purpose
            or not isinstance(row.get("browser"), str)
            or len(row["browser"]) != 64
            or any(character not in "0123456789abcdef" for character in row["browser"])
        ):
            raise RuntimeError("owned_page_registry_invalid")
        if row.get("browser") != self.browser or row.get("target_id") is None:
            if row.get("ownership") == "operator_approved_external":
                raise RuntimeError("approved_sample_browser_changed")
            return None
        if not isinstance(row["target_id"], str) or not row["target_id"]:
            raise RuntimeError("owned_page_registry_invalid")
        target = next(
            (item for item in targets if item.get("id") == row["target_id"]), None
        )
        if target is None:
            if row.get("ownership") == "operator_approved_external":
                raise RuntimeError("approved_sample_page_missing")
            return None
        if target.get("type") != "page":
            raise RuntimeError("owned_page_target_changed")
        split = urlsplit(target.get("url", ""))
        if target.get("url") != "about:blank":
            expected_host = (
                "affiliate-us.tiktok.com" if self.shop == "9136806951995371293"
                else HOST
            )
            local_paid_redirect = (
                self.shop == "9136806951995371293"
                and self.purpose == "refundable"
                and row.get("ownership") == "collector_created"
                and split.scheme == "https"
                and split.hostname == "seller-us.tiktok.com"
                and split.path == "/affiliate/landing"
                and parse_qs(split.query).get("oec_seller_id", [self.shop]) == [self.shop]
            )
            if split.hostname != expected_host and not local_paid_redirect:
                raise RuntimeError("owned_page_target_changed")
            shops = parse_qs(split.query).get("shop_id", [])
            if shops and shops != [self.shop]:
                raise RuntimeError("owned_page_shop_changed")
        return row["target_id"]

    def is_externally_owned(self):
        row = json.loads(self.path.read_text(encoding="utf-8"))
        return row.get("ownership") == "operator_approved_external"

    def save(self, target_id, *, externally_owned=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "shop": self.shop,
                    "purpose": self.purpose,
                    "browser": self.browser,
                    "target_id": target_id,
                    "ownership": (
                        "operator_approved_external" if externally_owned else "collector_created"
                    ),
                }
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)


def is_owned_error_page(targets, target_id):
    target = next((item for item in targets if item.get("id") == target_id), {})
    split = urlsplit(target.get("url", ""))
    return split.hostname == HOST and split.path == "/errorpage"

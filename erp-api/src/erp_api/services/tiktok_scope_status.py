from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

BESTSELLER_REQUIRED_SCOPES = ("data.bestselling.public.read",)
TIKTOK_301_REQUIRED_SCOPES = (
    "seller.affiliate_collaboration.read",
    "seller.affiliate_collaboration.write",
    "seller.creator_marketplace.read",
)


@dataclass(frozen=True)
class TikTokScopeStatus:
    required_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...]
    missing_scopes: tuple[str, ...]

    @property
    def reauthorization_required(self) -> bool:
        return bool(self.missing_scopes)


def evaluate_scope_status(
    *,
    granted_scopes: Iterable[str],
    required_scopes: Iterable[str],
) -> TikTokScopeStatus:
    granted = frozenset(scope for scope in granted_scopes if scope)
    required = frozenset(scope for scope in required_scopes if scope)
    return TikTokScopeStatus(
        required_scopes=tuple(sorted(required)),
        granted_scopes=tuple(sorted(granted)),
        missing_scopes=tuple(sorted(required - granted)),
    )

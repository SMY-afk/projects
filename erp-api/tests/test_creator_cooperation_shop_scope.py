from datetime import date

from scripts.daily_valid_creator_accounts import select_accounts
from scripts.daily_valid_creator_core import SHOP_ORDER
from scripts.daily_valid_creator_shop_rows import desired_shop_rows


def test_declared_cooperation_shop_wins_over_older_blank_record_and_other_shop_gmv():
    rows = [{"accountName": "mamakailashops", "bdOwner": "帝维",
             "sampleApprovedDate": "2026-08-20", "cooperationShop": ""},
            {"accountName": " mamakailashops ", "bdOwner": "帝维",
             "sampleApprovedDate": "2026-08-21", "cooperationShop": "跨境12店"}]
    window = (date(2026, 8, 16), date(2026, 10, 14))
    base, _ = select_accounts(rows, window)
    assert set(base) == {("mamakailashops", "跨境12")}
    high = {shop: {"creators": [], "liveAccounts": []} for shop in SHOP_ORDER}
    low = {shop: {"videos": []} for shop in SHOP_ORDER}
    windows = {shop: {resource: (date(2026, 8, 12), date(2026, 10, 12))
               for resource in ("creators", "videos", "liveAccounts")} for shop in SHOP_ORDER}
    high["跨境3"]["creators"] = [{"username": "mamakailashops", "affiliateGmvMinor": 10000}]
    desired = desired_shop_rows(base, high, low, windows, window)
    assert set(desired) == {("mamakailashops", "跨境12")}
    assert desired[("mamakailashops", "跨境12")]["BD负责人"] == "帝维"
    assert desired[("mamakailashops", "跨境12")]["业绩"] == 0


def test_same_account_does_not_mix_owners_from_two_declared_shops():
    rows = [{"accountName": "abc", "bdOwner": owner, "sampleApprovedDate": "2026-10-13",
             "cooperationShop": shop} for shop, owner in (("跨境3店", "A"), ("跨境4店", "B"))]
    base, _ = select_accounts(rows, (date(2026, 8, 16), date(2026, 10, 14)))
    assert base[("abc", "跨境3")]["bd"] == "A"
    assert base[("abc", "跨境4")]["bd"] == "B"

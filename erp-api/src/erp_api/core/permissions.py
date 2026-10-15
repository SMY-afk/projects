from typing import Final, Literal, get_args

SHOP_VIEW: Final = "shops:view"
SHOP_MANAGE: Final = "shops:manage"
PRODUCTS_VIEW: Final = "products:view"
ORDERS_VIEW: Final = "orders:view"
ORDERS_BUYER_PII_VIEW: Final = "orders:buyer-pii:view"
SYNC_TRIGGER: Final = "sync:trigger"
DASHBOARD_VIEW: Final = "dashboard:view"
SALES_VIEW: Final = "sales:view"
ADS_VIEW: Final = "ads:view"
PLATFORM_WAREHOUSE_VIEW: Final = "platform-warehouse:view"
WAREHOUSE_VIEW: Final = "warehouse:view"
LOGISTICS_VIEW: Final = "logistics:view"
LOGISTICS_OPERATE: Final = "logistics:operate"
LOGISTICS_DISPATCH: Final = "logistics:dispatch"
LOGISTICS_MANAGE: Final = "logistics:manage"
LOGISTICS_COST_VIEW: Final = "logistics:cost:view"
LOGISTICS_COST_RECONCILE: Final = "logistics:cost:reconcile"
RETURNS_VIEW: Final = "returns:view"
RETURNS_MANAGE: Final = "returns:manage"
RETURNS_INSPECT: Final = "returns:inspect"
DATA_VIEW: Final = "data:view"
BESTSELLERS_VIEW: Final = "bestsellers:view"
AFFILIATE_CENTER_VIEW: Final = "affiliate-center:view"
FINANCE_VIEW: Final = "finance:view"
TOOLS_VIEW: Final = "tools:view"
SETTINGS_VIEW: Final = "settings:view"

PermissionCode = Literal[
    "shops:view",
    "shops:manage",
    "products:view",
    "orders:view",
    "orders:buyer-pii:view",
    "sync:trigger",
    "dashboard:view",
    "sales:view",
    "ads:view",
    "platform-warehouse:view",
    "warehouse:view",
    "logistics:view",
    "logistics:operate",
    "logistics:dispatch",
    "logistics:manage",
    "logistics:cost:view",
    "logistics:cost:reconcile",
    "returns:view",
    "returns:manage",
    "returns:inspect",
    "data:view",
    "bestsellers:view",
    "affiliate-center:view",
    "finance:view",
    "tools:view",
    "settings:view",
]

MODULE_PERMISSION_CODES: Final[frozenset[str]] = frozenset(get_args(PermissionCode))

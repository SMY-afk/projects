"""The Excel column contract plus the fields owned by logistics synchronization."""

EXCEL_FIELDS = (
    "店铺", "订单号", "实时订单状态", "实时物流状态", "订单创建时间（当地时间）",
    "当地时间的发货时间", "当地时间的真实发货时间", "实际送达时间（当地时间）",
    "创建至发货（小时）", "发货至真实发货（小时）", "真实多久送达（天）", "首次地点轨迹依据", "最新轨迹",
    "发货轨迹依据", "送达轨迹依据", "官方查询时间（北京时间）", "订单数据同步时间（北京时间）",
    "包裹号", "包裹状态", "承运商", "运单号（脱敏）", "核对说明", "导出时间（北京时间）", "物流方式",
)
EXTRA_FIELDS = (
    "ERP订单键", "预警状态", "预警节点", "快超时节点", "已超时节点", "节点预警详情",
    "首次接入飞书时间", "解除预警时间", "最近飞书同步时间",
)
OWNED_FIELDS = EXCEL_FIELDS + EXTRA_FIELDS
KEY_FIELD = "ERP订单键"
STATE_FIELD = "预警状态"
YELLOW = "🟡快超时"
RED = "🔴已超时"
RESOLVED = "已解除预警"
NODE_NAMES = {"unshipped_48h": "未发货", "uncollected_48h": "未真实发货", "undelivered_77h": "未送达"}


def field_definition(name):
    definition = {"field_name": name, "type": 1}
    if name in {"创建至发货（小时）", "发货至真实发货（小时）", "真实多久送达（天）"}:
        definition.update(type=2, property={"formatter": "0.0000"})
    elif name == STATE_FIELD:
        definition.update(type=3, property={"options": [{"name": value} for value in [YELLOW, RED, RESOLVED]]})
    elif name == "预警节点":
        definition.update(type=4, property={"options": [{"name": value} for value in NODE_NAMES.values()]})
    return definition

"""Chinese display templates matching the ERP Excel export, preserving place names."""
import re

DESCRIPTIONS = {
    "order placed": "已下单。",
    "package details received by the carrier": "承运商已收到包裹详细信息。",
    "order packed and ready for pickup": "订单已打包，正在等待承运商揽收。",
    "order packed and ready for dropoff at carrier's facility": "订单已打包，正在等待在承运商的仓储场所卸货。",
    "package is being prepared at warehouse": "包裹正在仓库备货。",
    "package is ready and will be handed over to the carrier soon": "包裹已准备好，即将交给承运商。",
    "arrived at the sorting center": "已到达分拣中心。",
    "in transit": "运输中。", "in transit to the next facility": "正在运往下一个仓储场所。",
    "out for delivery": "正在派送。", "package has been delivered": "包裹已送达。", "delivered": "已送达。",
}
DELIVERY_LOCATIONS = {
    "front door/porch": "前门/门廊", "front desk/reception/mail room": "前台/接待处/收发室",
    "in/at mailbox": "信箱内/信箱处", "parcel locker": "包裹柜", "left with individual": "已交给收件人",
    "garage or other location at address": "地址处的车库或其他位置",
    "individual picked up at postal facility": "收件人已在邮政网点领取",
}


def translate(description):
    if not description:
        return ""
    source = description.strip()
    key = source.lower().replace("’", "'").rstrip(".!")
    if key in DESCRIPTIONS:
        return DESCRIPTIONS[key]
    facility = re.fullmatch(
        r"(Arrived at|Departed(?: from)?) (?:the )?(.+?) (carrier['’]s|destination|shipping partner['’]s) facility[.!]?",
        source, re.IGNORECASE,
    )
    if facility:
        action, place, owner = facility.groups()
        verb = "已到达" if action.lower().startswith("arrived") else "已离开"
        kind = owner.lower().replace("’", "'")
        if kind == "destination":
            return f"{verb}{place}目的地仓储场所。"
        owner_name = "承运商" if kind == "carrier's" else "物流合作伙伴"
        return f"{verb}{owner_name}的{place}仓储场所。"
    pickup = re.fullmatch(r"Package picked up and currently at (.+?)[.!]?", source, re.IGNORECASE)
    if pickup:
        return f"包裹已被揽收，目前位于{pickup[1]}。"
    delivery = re.fullmatch(r"delivered,\s*(.+)", key)
    if delivery and delivery[1] in DELIVERY_LOCATIONS:
        return f"已送达，{DELIVERY_LOCATIONS[delivery[1]]}。"
    return description

AFFILIATE_CONTENT_FORM_BY_PROMOTION_TYPE: dict[int, str] = {
    1: "product_showcase",
    2: "video",
    3: "live",
    5: "affiliate_product_page",
    6: "external_traffic_plan",
}

AFFILIATE_CONTENT_FORM_LABELS: dict[str, str] = {
    "product_showcase": "商品橱窗",
    "video": "视频",
    "live": "直播",
    "affiliate_product_page": "联盟商品页",
    "external_traffic_plan": "外部流量计划",
}


def affiliate_content_form(promotion_type: int | None) -> str | None:
    if promotion_type is None:
        return None
    return AFFILIATE_CONTENT_FORM_BY_PROMOTION_TYPE.get(promotion_type)


def affiliate_content_form_label(content_form: str | None) -> str | None:
    if content_form is None:
        return None
    return AFFILIATE_CONTENT_FORM_LABELS.get(content_form)

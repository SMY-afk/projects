from __future__ import annotations

from erp_api.services.sample_notification_card_components import escape_text, markdown
from erp_api.services.sample_shop_display import sample_shop_display_name


def build_application_elements(
    task,
    bd_name: str,
    product_img_keys: tuple[str, ...],
    *,
    formatted_deadline: str,
) -> list[dict[str, object]]:
    shop_name = sample_shop_display_name(task.shop_name)
    product_name = escape_text(task.product_name, limit=120)
    deadline_label = "审核截止"
    if getattr(task, "sample_type", "free") == "refundable":
        deadline_label = "样品类型"
        formatted_deadline = "买返样品（不适用免费审核倒计时）"
    content = (
        f"🏬 **店铺**　{escape_text(shop_name, limit=100)}\n"
        f"📦 **申请商品**　{product_name}\n"
        f"⏳ **{deadline_label}**　{formatted_deadline}\n"
        f"🙋 **分配 BD**　{escape_text(bd_name, limit=80)}"
    )
    if not product_img_keys:
        return [markdown(content)]
    image_columns: list[dict[str, object]] = [
        {
            "tag": "column",
            "width": "80px",
            "elements": [
                {
                    "tag": "img",
                    "img_key": image_key,
                    "alt": {
                        "tag": "plain_text",
                        "content": f"Product image {index}",
                    },
                    "corner_radius": "4px",
                    "preview": True,
                }
            ],
        }
        for index, image_key in enumerate(product_img_keys, start=1)
    ]
    return [
        markdown(f"🏬 **店铺**　{escape_text(shop_name, limit=100)}\n📦 **申请商品**"),
        {
            "tag": "column_set",
            "flex_mode": "none",
            "horizontal_spacing": "8px",
            "columns": image_columns,
        },
        markdown(
            f"⏳ **{deadline_label}**　{formatted_deadline}\n"
            f"🙋 **分配 BD**　{escape_text(bd_name, limit=80)}"
        ),
    ]

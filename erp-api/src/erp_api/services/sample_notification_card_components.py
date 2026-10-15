from __future__ import annotations

import re
from collections.abc import Sequence


def markdown(content: str, *, size: str | None = None) -> dict[str, object]:
    text: dict[str, object] = {"tag": "lark_md", "content": content}
    if size:
        text["text_size"] = size
    return {"tag": "div", "text": text}


def metric_grid(metrics: Sequence[tuple[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for start in range(0, len(metrics), 2):
        pair = metrics[start : start + 2]
        rows.append(
            {
                "tag": "column_set",
                "flex_mode": "bisect" if len(pair) == 2 else "stretch",
                "horizontal_spacing": "8px",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [
                            markdown(
                                f"<font color='grey'>{escape_text(label)}</font>\n"
                                f"**{escape_text(value)}**"
                            )
                        ],
                    }
                    for label, value in pair
                ],
            }
        )
    return rows


def collapsible_panel(
    title: str,
    elements: Sequence[dict[str, object]],
    *,
    element_id: str,
    expanded: bool = False,
) -> dict[str, object]:
    return {
        "tag": "collapsible_panel",
        "element_id": element_id,
        "expanded": expanded,
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "icon": {
                "tag": "standard_icon",
                "token": "down-small-ccm_outlined",
            },
            "icon_position": "right",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "8px"},
        "elements": list(elements),
    }


def open_url_button(label: str, url: str, *, primary: bool) -> dict[str, object]:
    return {
        "tag": "button",
        "type": "primary" if primary else "default",
        "width": "fill",
        "text": {"tag": "plain_text", "content": label},
        "behaviors": [{"type": "open_url", "default_url": url}],
    }


def button_row(buttons: Sequence[dict[str, object]]) -> dict[str, object]:
    return {
        "tag": "column_set",
        "flex_mode": "bisect" if len(buttons) == 2 else "stretch",
        "horizontal_spacing": "8px",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [button],
            }
            for button in buttons
        ],
    }


def escape_text(value: object, *, limit: int = 240) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "—"))
    text = re.sub(r"\s+", " ", text).strip() or "—"
    text = text[:limit]
    return (
        text.replace("\\", "\\\\")
        .replace("<", "＜")
        .replace(">", "＞")
        .replace("*", "\\*")
        .replace("`", "\\`")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )

# TikTok Shop 订单状态映射

| TikTok 状态                               | ERP 状态              |
| ----------------------------------------- | --------------------- |
| `UNPAID`                                  | `unpaid`              |
| `ON_HOLD`                                 | `on_hold`             |
| `AWAITING_SHIPMENT`                       | `awaiting_shipment`   |
| `AWAITING_COLLECTION`                     | `awaiting_collection` |
| `PARTIALLY_SHIPPING`, `PARTIALLY_SHIPPED` | `partially_shipped`   |
| `SHIPPED`, `IN_TRANSIT`                   | `in_transit`          |
| `DELIVERED`                               | `delivered`           |
| `COMPLETED`                               | `completed`           |
| `CANCELLED`, `CANCELED`                   | `cancelled`           |
| 其他新状态                                | `unknown`             |

所有记录保留 `externalStatus`。未知状态不得中断同步；只有平台 `update_time` 不早于已存记录时才能更新订单，防止延迟事件造成状态倒退。

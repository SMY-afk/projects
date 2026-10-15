# 物流轨迹 Webhook 合同

## 接口

`POST /api/v1/webhooks/logistics/{tenant_id}/{carrier_code}`

请求头：

- `X-Carrier-Timestamp`：当前 Unix 秒时间戳，允许前后偏差 300 秒。
- `X-Carrier-Signature`：`sha256=<hex>`。
- 签名原文：`timestamp + "." + raw_body`。
- 签名算法：HMAC-SHA256。

签名密钥通过 `LOGISTICS_WEBHOOK_SIGNING_SECRETS` 注入。优先使用
`TENANT_UUID:CARRIER_CODE`，也支持以物流商代码或 Adapter Key 作为键。

## 通用请求体

单条事件可以直接作为请求体；批量事件使用 `events` 数组。

```json
{
  "events": [
    {
      "eventId": "carrier-event-1001",
      "externalWaybillId": "carrier-waybill-2001",
      "trackingNumber": "TRACKING-3001",
      "status": "OUT_FOR_DELIVERY",
      "occurredAt": "2026-08-24T08:30:00Z",
      "sequence": 5,
      "location": "Shanghai",
      "description": "Courier is delivering the parcel"
    }
  ]
}
```

`externalWaybillId` 与 `trackingNumber` 至少提供一个。优先使用物流商外部运单号；
追踪号通过加密指纹匹配，不在轨迹表保存明文。

## 统一状态

- `info_received`
- `picked_up`
- `in_transit`
- `out_for_delivery`
- `delivered`
- `exception`
- `returned`
- `cancelled`

系统内置常见英文状态别名。物流商特有状态通过物流服务的
`trackingStatusMap` 配置，例如：

```json
{
  "trackingStatusMap": {
    "CUSTOM_TRANSIT_20": "in_transit",
    "CUSTOM_SIGNED_90": "delivered"
  }
}
```

## 去重和顺序保护

- 优先使用物流商 `eventId` 生成幂等键；缺失时使用状态、时间、序号、地点和描述生成摘要。
- 同一租户、运单和幂等键仅保存一次。
- 序号不大于当前序号的事件记录为 `out_of_order_sequence`。
- 发生时间早于当前轨迹时间的事件记录为 `out_of_order_time`。
- 已签收、已退回或已取消后的状态回退记录为 `status_regression`。
- 未识别状态记录为 `unknown_status`，不会覆盖运单状态。

所有被忽略的事件仍保留在轨迹时间线中，`accepted=false`，便于审计。

## 轮询补偿

ARQ 每 10 分钟扫描一次到期运单。在线 Carrier Adapter 根据自身 API 返回
`CarrierTrackingUpdate`，并复用与 Webhook 相同的映射、去重和顺序保护逻辑。
人工物流商不会进入轮询队列。

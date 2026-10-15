# TikTok Shop 订单 API 契约

## 范围

订单模块首期只读取 TikTok Shop 订单、订单项、金额和履约状态，不向平台提交发货、取消或退款操作。首次回填固定为最近 30 天，之后由 Webhook 和每 10 分钟一次的增量任务更新。

部署前必须在 TikTok Shop 开发者后台确认当前应用已获批订单读取、物流读取及订单 Webhook 权限，并使用新权限重新授权目标店铺。具体 scope 名称、endpoint 版本和事件名称以开发者后台实际批准结果为准，禁止用 Mock 字段代替平台确认。

## 查询接口

```text
GET  /api/orders?page=&pageSize=&shopId=&keyword=&status=&updatedFrom=&updatedTo=&trafficSource=&operatorSubject=&entryPoint=&specialOrderType=&classificationStatus=&chainCode=
GET  /api/orders/{orderId}
GET  /api/orders/{orderId}/recipient
POST /api/orders/sync?shopId=&mode=backfill|incremental&updatedFrom=&updatedTo=
```

- 列表和详情要求 `orders:view`；本期没有人工归因修正写接口，也不启用 `orders:attribution:manage`。后续若增加人工修正，需单独评审并新增该权限。
- 手动同步要求 `sync:trigger`。
- 完整收件信息要求 `orders:buyer-pii:view`，每次允许或拒绝访问都记录审计。
- 分页返回 `{ items, total, page, pageSize }`；时间为 UTC ISO 8601，筛选范围采用 `[updatedFrom, updatedTo)`。
- 金额使用最小货币单位整数和 ISO 4217 币种，不使用浮点数或格式化金额字符串。
- 订单列表额外返回 `settlementAmountMinor: int | null`：按同租户、订单和币种汇总最终 Finance 流水；预计流水不计入。没有最终结算记录时返回 `null`，实际净结算为零时返回 `0`。

订单列表和详情响应均返回 `attribution`。列表返回简要对象：`trafficSource`、`operatorSubject`、`entryPoint`、`specialOrderType`、`chainCode`、`classificationStatus`；详情在此基础上增加 `classificationMethod`、`sourceUpdatedAt` 和脱敏 `evidenceSummary`。详情证据项同时返回 `reason` 与 `reasonLabel`；缺少订单详情来源字段时使用 `reasonLabel=未识别：订单详情未返回来源字段`，不得显示或推导为自然流；当外部联盟或 Ads/GMV Max 响应没有可精确关联当前订单的订单 ID/订单项 ID 时，`reason=platform_no_order_level_evidence`、`reasonLabel=平台无订单级证据`，且归类必须保持 `classificationStatus=unknown`、`chainCode=unknown`。证据中的外部转化 ID 只返回不可逆指纹，不返回原始 ID、payload、Token、买家 PII。枚举未知时使用 `unknown`，不使用空字符串替代。

订单列表支持按截图所示订单类型树进行服务端精确筛选：一级为 `trafficSource`（自然流订单/广告流订单），二级为 `operatorSubject`（达人订单/自营订单/商城订单），三级为 `entryPoint`（视频订单/直播订单/站外订单/橱窗订单/联盟商品页/搜索或推荐）；样品订单和买样返款订单使用 `specialOrderType`，另可按 `classificationStatus` 筛选。筛选条件在 SQL 查询中与订单事实条件合并，并在筛选后执行 `total` 计数、排序、分页；前端不得拉取全量订单后再过滤。筛选当前唯一有效归因记录；无归因记录的订单在筛选 `unknown` 时也纳入。未知枚举或非法 `chainCode` 返回 `422 VALIDATION_ERROR`。既有分页仍为 1-based `{ items, total, page, pageSize }`，时间范围仍为 `[updatedFrom, updatedTo)`。

## 隐私与保留

列表和普通详情只返回脱敏买家、电话和地址。完整收件信息通过独立接口按需获取，前端不得预取、持久化或放入 React Query 缓存。姓名、电话、地址、完整运单号及含 PII 的 Webhook 载荷使用独立 `ORDER_PII_ENCRYPTION_KEY` 加密；终态订单 90 天后清除可还原字段。

## Webhook

`POST /api/v1/webhooks/tiktok` 校验签名、五分钟时间窗口和 1 MiB 请求体上限，事件持久化成功后才返回 `202`。事件表是可靠 inbox；Redis 即时投递失败不会丢失已接收事件，后续调度任务重新同步店铺数据。

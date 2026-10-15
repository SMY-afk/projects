# ERP 内部 API v1 契约

本文档是 `erp-web` 与未来 `erp-api` FastAPI 服务之间的内部契约。TikTok Shop 的原始响应不得直接暴露给浏览器；后端必须转换为本文档定义的内部结构。

## 1. 版本与请求约定

- 浏览器请求前缀：`/api`
- 当前契约版本：`v1`
- 请求头：`X-API-Contract-Version: v1`
- 认证：`Authorization: Bearer <ERP access token>`
- 内容类型：`application/json; charset=utf-8`
- 所有资源 ID 使用字符串传输；前端不得依赖数据库自增整数类型。
- 服务器响应应包含 `X-Request-Id`；错误响应体中的 `requestId` 与该值一致。

示例：

```text
GET /api/products?page=1&pageSize=20&shopId=shop_123
X-API-Contract-Version: v1
Authorization: Bearer <token>
```

## 2. 统一响应结构

### 成功

```json
{
  "code": 0,
  "message": "OK",
  "data": {},
  "requestId": "req_01J..."
}
```

- `code: 0` 表示业务成功；HTTP 状态码仍使用标准 `2xx`。
- `message` 用于日志和非本地化提示；前端不应依赖它判断成功。
- `data` 可以是对象、数组、分页对象或 `null`。
- `requestId` 用于客服、日志和同步任务排查。

### 错误

```json
{
  "code": "AUTH_UNAUTHORIZED",
  "message": "登录已过期，请重新登录",
  "data": null,
  "requestId": "req_01J...",
  "details": null
}
```

- 错误必须同时使用正确的 HTTP 状态码和稳定的业务 `code`。
- `details` 只返回安全、可展示的字段错误；不得包含 token、App Secret、SQL、堆栈或买家 PII。
- 前端当前 `src/services/http-client.ts` 已兼容 `code` 为数字或字符串，并以 `0/200/'0'/'200'/'SUCCESS'` 判断成功；新后端统一使用 `0`。

## 3. 错误码

| HTTP | 业务 code             | 使用场景                      |
| ---: | --------------------- | ----------------------------- |
|  400 | `BAD_REQUEST`         | 参数组合无效、请求格式错误    |
|  401 | `AUTH_UNAUTHORIZED`   | 未登录、token 过期或无效      |
|  403 | `AUTH_FORBIDDEN`      | 已登录但无对应权限            |
|  404 | `RESOURCE_NOT_FOUND`  | 资源不存在或不属于当前租户    |
|  409 | `RESOURCE_CONFLICT`   | 重复连接、状态冲突、幂等冲突  |
|  422 | `VALIDATION_ERROR`    | 字段校验失败                  |
|  429 | `RATE_LIMITED`        | ERP 或 TikTok 平台限流        |
|  502 | `PLATFORM_ERROR`      | TikTok 上游错误或响应无法转换 |
|  503 | `SERVICE_UNAVAILABLE` | 数据库、队列或依赖暂不可用    |
|  500 | `INTERNAL_ERROR`      | 未预期服务端错误              |

错误细节示例：

```json
{
  "code": "VALIDATION_ERROR",
  "message": "请求参数校验失败",
  "data": null,
  "requestId": "req_123",
  "details": {
    "fields": [{ "field": "pageSize", "reason": "must be between 1 and 100" }]
  }
}
```

## 4. 分页与筛选

所有列表接口统一使用服务端分页：

### 请求参数

```text
page=1                # 必填或默认 1，1-based
pageSize=20           # 默认 20，最大 100
keyword=              # 可选，后端按接口定义搜索字段
sortBy=updatedAt      # 可选，必须使用白名单字段
sortOrder=desc        # 可选：asc 或 desc
```

资源专属过滤字段使用明确名称，例如 `shopId`、`status`、`updatedFrom`、`updatedTo`；日期范围为左闭右开 `[from, to)`。

### 响应结构

```json
{
  "code": 0,
  "message": "OK",
  "data": {
    "items": [],
    "total": 0,
    "page": 1,
    "pageSize": 20
  },
  "requestId": "req_123"
}
```

规则：

- `total` 是当前筛选条件下的总条数，不是当前页条数。
- 空结果返回 `items: []`，不返回 `null`。
- 超过最后一页时返回空列表并保留请求页码，或由具体接口明确返回 `400 BAD_REQUEST`；本项目统一采用空列表。
- 删除最后一页数据后的页码回退由前端根据 `total` 处理，后端不返回 HTML 或特殊结构。

## 5. 金额格式

- 禁止用浮点数传输金额。
- 使用最小货币单位整数：`amountMinor`。
- 必须同时返回 ISO 4217 大写货币码：`currency`，例如 `USD`。
- `amountMinor` 可为负数表示退款/折扣，但业务字段必须明确含义。

```json
{
  "totalAmountMinor": 29900,
  "settlementAmountMinor": 25700,
  "currency": "USD"
}
```

前端展示时再按 `currency` 格式化；数据库和接口不要保存带 `$`、逗号或本地化符号的字符串。

订单列表的 `settlementAmountMinor` 是同币种最终 Finance 流水净额合计；尚无最终结算时为 `null`，不得按零结算展示。

## 6. 时间格式

- API 和数据库统一使用 UTC。
- 使用 ISO 8601，带 `Z` 或明确 UTC 偏移；推荐 `2026-08-11T10:20:00Z`。
- 不返回无时区的 `2026-08-11 10:20:00`。
- `updatedFrom`/`updatedTo` 接受带时区的 ISO 8601，并按 UTC 比较。
- 前端根据用户/店铺时区展示，但不得修改原始 UTC 值。

## 7. 首期核心接口

```text
GET  /api/health
GET  /api/auth/captcha
POST /api/auth/login
GET  /api/auth/current-user
POST /api/auth/logout

POST /api/shops/tiktok/authorize
GET  /shops/tiktok/callback
GET  /api/shops
GET  /api/shops/{shopId}
POST /api/shops/{shopId}/disconnect

GET  /api/products?page=1&pageSize=20&shopId=&keyword=&status=
GET  /api/products/{productId}
GET  /api/orders?page=1&pageSize=20&shopId=&status=&updatedFrom=&updatedTo=&trafficSource=&operatorSubject=&entryPoint=&specialOrderType=&classificationStatus=&chainCode=
GET  /api/orders/{orderId}
GET  /api/orders/{orderId}/recipient
POST /api/sync-jobs/products
POST /api/sync-jobs/orders
GET  /api/sync-jobs/{jobId}
POST /api/tiktok/webhooks

# 设计中：数据板块只读接口，详见 docs/tiktok-shop/data-api-contract.md
GET  /api/data/overview?shopId=&from=&to=&granularity=
GET  /api/data/trends?shopId=&from=&to=&granularity=
GET  /api/data/videos?shopId=&from=&to=&granularity=&pageToken=&pageSize=
GET  /api/data/lives?shopId=&from=&to=&granularity=&pageToken=&pageSize=

GET  /api/bestsellers/authorization-status?shopId=
GET  /api/bestsellers/{products|creators|videos|lives}?shopId=&date=&timeSlot=&currency=&authorType=
POST /api/bestsellers/sync
```

订单列表和详情均返回 `attribution`，读取沿用 `orders:view`。本期不提供人工归因修正写接口，也不启用 `orders:attribution:manage`；后续如增加人工修正，需单独评审权限。列表返回简要归因字段；详情增加判定方法、更新时间和脱敏证据摘要。归因对象字段为：

```text
trafficSource: organic | paid_ads | unknown
operatorSubject: creator | self_operated | mall | unknown
entryPoint: video | live | offsite | showcase | affiliate_product_page | search_recommendation | unknown
specialOrderType: normal | sample | purchase_sample_rebate | unknown
chainCode: (organic|paid_ads).(creator|self_operated|mall).(video|live|offsite|showcase|affiliate_product_page|search_recommendation) | sample | purchase_sample_rebate | unknown
classificationStatus: confirmed | derived | unknown
classificationMethod: shop_order_detail | affiliate_order | ads_order_link | rule
sourceUpdatedAt: UTC ISO 8601 或 null
evidenceSummary: 详情返回的脱敏摘要；列表省略
```

列表筛选参数为 `trafficSource`、`operatorSubject`、`entryPoint`、`specialOrderType`、`classificationStatus` 和 `chainCode`，均为单值精确匹配，并筛选当前唯一有效归因记录；可显式传 `unknown`。非法枚举或 `chainCode` 返回 `422 VALIDATION_ERROR`，不能静默转为 `unknown`。筛选条件必须参与服务端查询和前端 Query Key。

订单的真实实现使用 `POST /api/orders/sync` 触发指定店铺的 `backfill` 或 `incremental` 同步；`/api/sync-jobs/orders` 保留为后续统一任务中心契约，不作为当前前端依赖。订单隐私和字段规范见 `docs/order-api-contract.md`。

## 8. 兼容和变更规则

- v1 只做向后兼容的新增字段；已有字段不改类型、不改变语义。
- 破坏性变更创建 v2，并至少保留一个发布周期的 v1。
- 新的枚举值必须允许前端显示“未知状态”，不能导致整个响应解析失败。
- 所有契约变更先更新本文档和 `docs/backend-contract-confirmation.md`，再修改 FastAPI schema 和 React 类型。

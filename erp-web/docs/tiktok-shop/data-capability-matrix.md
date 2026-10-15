# TikTok Shop 数据能力矩阵

> 核验日期：2026-08-14  
> 核验范围：TikTok Shop Open API / Analytics，优先覆盖店铺、视频、直播数据。  
> 当前状态：完成官方文档核验和本地授权 scope 核验，尚未向 Analytics endpoint 发起真实数据探针请求。

## 1. 当前店铺授权基线

最小权限差集和重新授权设计见：[数据板块最小 OAuth 权限与重新授权方案](./data-minimum-oauth-scopes.md)。

当前 ERP 数据库中的授权连接：

| 项目            | 当前值                            | 结论                            |
| --------------- | --------------------------------- | ------------------------------- |
| 店铺            | `Akeleo Fun Toys`                 | 作为首个只读联调店铺            |
| 区域            | `US`                              | 属于 Analytics 全球开放范围     |
| 授权状态        | `authorized`                      | 店铺连接有效                    |
| Analytics scope | `data.shop_analytics.public.read` | 已存在，可进入只读 API 探针阶段 |

注意：这里只证明当前这一个店铺连接保存了该 scope。后续每个店铺接入时仍需检查 `shop_connections.scopes`，缺少 scope 时必须重新授权。

## 2. 官方共同规则

| 项目         | 官方规则                                                                                                     | ERP 实施约束                                                                                      |
| ------------ | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| API 产品     | TikTok Shop Open API / Analytics                                                                             | 浏览器只调用 ERP `/api`，平台 API 由后端调用                                                      |
| Base URL     | `https://open-api.tiktokglobalshop.com`                                                                      | 复用后端 `TikTokTransport`                                                                        |
| 认证         | Seller access token，`user_type = 0`                                                                         | Token 仅加密存储在后端                                                                            |
| 必需 scope   | `data.shop_analytics.public.read`                                                                            | 查询前做 scope preflight；缺失时返回明确的重新授权状态                                            |
| 必需公共参数 | `app_key`、`sign`、`timestamp`、`shop_cipher`                                                                | 继续由后端统一签名；跨境店必须传正确 `shop_cipher`                                                |
| 区域         | 2025-09-27 起 Analytics API 面向所有市场、本地店和跨境店开放；受具体应用类目审批约束                         | 首期 US 店可用，但仍需在 Partner Center 确认应用类目已批准                                        |
| 时间语义     | 日期使用店铺注册时区；`start_date_ge` 包含开始日，`end_date_lt` 不包含结束日                                 | 数据库保存 UTC，同时保存店铺时区和原始统计日期                                                    |
| 币种         | `USD` 或 `LOCAL`，默认 `LOCAL`                                                                               | 内部使用 `amountMinor + currency`，禁止使用浮点金额                                               |
| 限流         | 配额动态计算，最小隔离单位通常为 `App ID × Authorized Shop`，没有统一固定 QPS                                | Analytics 初始按每店每 endpoint `0.2–1 req/s` 调度，稳定后逐步提升                                |
| 限流信号     | HTTP `429` 或业务码 `36009002`                                                                               | 遵守 `Retry-After`，否则指数退避 + jitter；记录二者但不记录 token                                 |
| 数据时效     | 多数 endpoint 未公布固定 SLA；部分响应提供 `latest_available_date`，部分 overview 支持 `today=true` 实时口径 | 保存 `sourceLatestAvailableDate`、`fetchedAt`、`syncedAt`，不要把“请求成功时间”当成“数据更新时间” |

官方限流文档将复杂 Analytics 的 `0.2–1 req/s` 定义为保守的客户端起始值，不是平台承诺配额。

## 3. 首期能力矩阵

### 3.1 店铺级数据

| 数据项       | API 产品 / endpoint                                                                    | 方法与 scope                               | 区域限制              | 时间范围与粒度                                                   | 分页 | 限流                     | 更新延迟 / 粒度                                 | 当前结论                                              |
| ------------ | -------------------------------------------------------------------------------------- | ------------------------------------------ | --------------------- | ---------------------------------------------------------------- | ---- | ------------------------ | ----------------------------------------------- | ----------------------------------------------------- |
| 店铺经营总览 | Analytics `202509`<br>`/analytics/202509/shop/performance`                             | `GET`<br>`data.shop_analytics.public.read` | 全市场；本地店/跨境店 | 必填 `start_date_ge/end_date_lt`；店铺时区；`granularity=ALL/1D` | 无   | 动态；先按 `0.2–1 req/s` | 店铺级汇总或日粒度；未公布固定 SLA              | 官方契约已确认；当前店铺 scope 已具备；待真实响应验证 |
| 店铺小时趋势 | Analytics `202510`<br>`/analytics/202510/shop/performance/{date}/performance_per_hour` | `GET`<br>`data.shop_analytics.public.read` | 全市场；本地店/跨境店 | 单个 `date`；仅最近 30 天，包含今天；店铺时区；小时粒度          | 无   | 动态；先按 `0.2–1 req/s` | 店铺 × 小时；今天可查询，但未公布分钟级刷新 SLA | 可作为数据首页“今日小时趋势”；待真实响应验证          |

### 3.2 视频数据

| 数据项           | API 产品 / endpoint                                                                   | 方法与 scope                               | 区域限制                         | 时间范围与粒度                                                                 | 分页                                        | 限流                     | 更新延迟 / 返回粒度                                                                  | 当前结论                          |
| ---------------- | ------------------------------------------------------------------------------------- | ------------------------------------------ | -------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------- | ------------------------ | ------------------------------------------------------------------------------------ | --------------------------------- |
| 视频整体概览     | Analytics `202509`<br>`/analytics/202509/shop_videos/overview_performance`            | `GET`<br>`data.shop_analytics.public.read` | 全市场；本地店/跨境店            | `start_date_ge/end_date_lt`；`granularity=ALL/1D`；`today=true` 时覆盖日期参数 | 无                                          | 动态；先按 `0.2–1 req/s` | 店铺下全部视频汇总；`today=true` 返回店铺本地时间的当日实时指标；历史固定 SLA 未公布 | 首期核心卡片和趋势接口            |
| 视频表现列表     | Analytics `202509`<br>`/analytics/202509/shop_videos/performance`                     | `GET`<br>`data.shop_analytics.public.read` | 全市场；本地店/跨境店            | 必填日期范围；店铺时区；支持 `account_type`                                    | `page_token`；`page_size` 默认 10、最大 100 | 动态；先按 `0.2–1 req/s` | 视频级；按查询窗口聚合；固定更新延迟未公布                                           | 首期视频排行/列表接口             |
| 单视频表现详情   | Analytics `202509`<br>`/analytics/202509/shop_videos/{video_id}/performance`          | `GET`<br>`data.shop_analytics.public.read` | 全市场；只能读取授权店铺关联视频 | 必填日期范围；`granularity=ALL/1D`                                             | 无                                          | 动态；先按 `0.2–1 req/s` | 单视频 × 汇总/日；固定更新延迟未公布                                                 | 第二阶段详情抽屉/详情页           |
| 视频带货商品表现 | Analytics `202509`<br>`/analytics/202509/shop_videos/{video_id}/products/performance` | `GET`<br>`data.shop_analytics.public.read` | 全市场；只能读取授权店铺关联视频 | 必填日期范围；店铺时区                                                         | `page_token`；`page_size` 默认 10、最大 100 | 动态；先按 `0.2–1 req/s` | 单视频 × 商品；固定更新延迟未公布                                                    | 第二阶段，用于解释某视频 GMV 来源 |

视频列表支持的 `account_type`：

- `ALL`
- `OFFICIAL_ACCOUNTS`
- `MARKETING_ACCOUNTS`
- `AFFILIATE_ACCOUNTS`

首期页面建议默认 `ALL`，同时保留账号类型筛选，避免把达人分销视频误算成店铺官方视频。

### 3.3 直播数据

| 数据项       | API 产品 / endpoint                                                                    | 方法与 scope                               | 区域限制                                                 | 时间范围与粒度                                                                   | 分页                                                            | 限流                     | 更新延迟 / 返回粒度                     | 当前结论                                                                |
| ------------ | -------------------------------------------------------------------------------------- | ------------------------------------------ | -------------------------------------------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------- | ------------------------ | --------------------------------------- | ----------------------------------------------------------------------- |
| 直播整体概览 | Analytics `202509`<br>`/analytics/202509/shop_lives/overview_performance`              | `GET`<br>`data.shop_analytics.public.read` | 官方公告确认全市场、本地店/跨境店                        | `start_date_ge/end_date_lt`；`granularity=ALL/1D`；`today=true` 支持当日实时口径 | 无                                                              | 动态；先按 `0.2–1 req/s` | 店铺下全部直播汇总；历史固定 SLA 未公布 | 首期直播核心卡片和趋势接口                                              |
| 直播场次列表 | Analytics `202509`<br>`/analytics/202509/shop_lives/performance`                       | `GET`<br>`data.shop_analytics.public.read` | 全市场；Seller 只能查询自己官方创作者账号的 room ID 数据 | 必填日期范围；店铺时区；支持 `account_type`                                      | `page_token`；`page_size` 默认 10、最大 100                     | 动态；先按 `0.2–1 req/s` | 直播场次级；固定更新延迟未公布          | 首期直播场次列表；需实测营销/达人账号返回边界                           |
| 直播分钟趋势 | Analytics `202510`<br>`/analytics/202510/shop_lives/{live_id}/performance_per_minutes` | `GET`<br>`data.shop_analytics.public.read` | 仅店铺官方账号或营销账号主持的直播                       | 无日期参数；按 `live_id`；仅直播结束后返回                                       | `page_token`；官方 request 未提供 `page_size`，批大小由平台控制 | 动态；先按 `0.2–1 req/s` | 单直播 × 分钟；不是直播中的实时接口     | 第二阶段直播详情趋势；不能用于在播实时监控                              |
| 直播商品表现 | Analytics `202512`<br>`/analytics/202512/shop/{live_id}/products_performance`          | `GET`<br>`data.shop_analytics.public.read` | 店铺关联直播；仅官方账号或营销账号                       | 无日期参数；按 `live_id`                                                         | 当前 request 文档未提供 `page_token/page_size`                  | 动态；先按 `0.2–1 req/s` | 单直播 × 商品；固定数据就绪时间未公布   | 第二阶段，用于商品曝光、点击、订单和直接 GMV 分析；需验证大场次返回上限 |

## 4. 时间范围与数据时效结论

### 官方已明确

1. 所有日期参数都按店铺注册时区解释。
2. 店铺小时趋势只能查询最近 30 天，包含今天。
3. 视频/直播 overview 的 `today=true` 返回当日实时指标，并覆盖 `start_date_ge/end_date_lt`。
4. 直播分钟趋势只在直播结束后提供，不是实时直播监控接口。
5. 视频列表和直播列表的单页最大数量为 100。

### 官方未明确，需要探针验证

1. 大部分日期范围 endpoint 的单次最大查询窗口和最早可回溯日期。
2. 历史指标的固定更新延迟，例如 T+5 分钟、T+1 小时或 T+1 日。
3. 直播商品表现未提供分页参数时的大场次商品返回上限。
4. `AFFILIATE_ACCOUNTS` 视频和直播数据在当前 US 店铺授权下的实际完整度。
5. `latest_available_date` 是否在所有 `202509+` Analytics 响应中一致返回。

ERP 首期应主动限制日期窗口：默认最近 7 天，单次最多 30 天；更长时间由后端分段同步，不允许前端发起无限窗口查询。

## 5. 能力状态定义

| 状态            | 含义                                           |
| --------------- | ---------------------------------------------- |
| `documented`    | 官方 endpoint、方法、scope 和参数已核实        |
| `scope_ready`   | 当前店铺连接已保存所需 scope                   |
| `probe_pending` | 尚未用当前店铺发起最小只读请求                 |
| `verified`      | 已完成真实响应、字段、分页、时间范围和时效验证 |
| `unsupported`   | 官方或当前应用授权明确不支持                   |

当前本矩阵中所有首期接口状态为：`documented + scope_ready + probe_pending`。

## 6. 下一步只读探针清单

按以下顺序执行，每次只查询最近 1 天，`page_size=1` 或最小结果量：

1. `GET /analytics/202509/shop/performance`
2. `GET /analytics/202509/shop_videos/overview_performance`
3. `GET /analytics/202509/shop_videos/performance`
4. `GET /analytics/202509/shop_lives/overview_performance`
5. `GET /analytics/202509/shop_lives/performance`
6. 如果存在已结束直播，再调用分钟趋势和直播商品表现接口。

探针只记录：HTTP 状态、TikTok 业务码、`request_id`、响应字段名、分页信息、`latest_available_date`、耗时和脱敏错误分类。禁止记录 access token、签名、完整原始响应中的敏感字段。

## 7. 官方资料

- [TikTok Shop Analytics API Reference](https://partner.tiktokshop.com/docv2/page/get-shop-video-performance-list-202509)
- [Get Shop Performance](https://partner.tiktokshop.com/docv2/page/get-shop-performance-202509)
- [Get Shop Performance Per Hour](https://partner.tiktokshop.com/docv2/page/get-shop-performance-per-hour-202510)
- [Get Shop Video Performance Overview](https://partner.tiktokshop.com/docv2/page/get-shop-video-performance-overview-202509)
- [Get Shop Video Performance Details](https://partner.tiktokshop.com/docv2/page/get-shop-video-performance-details-202509)
- [Get Shop Video Product Performance List](https://partner.tiktokshop.com/docv2/page/get-shop-video-product-performance-list-202509)
- [Get Shop LIVE Performance List](https://partner.tiktokshop.com/docv2/page/get-shop-live-performance-list-202509)
- [Get Shop LIVE Performance Overview](https://partner.tiktokshop.com/docv2/page/get-shop-live-performance-overview-202509)
- [Get Shop LIVE Minute Performance](https://partner.tiktokshop.com/docv2/page/get-shop-live-minute-performance-202510)
- [Get Shop LIVE Products Performance List](https://partner.tiktokshop.com/docv2/page/get-shop-live-products-performance-list-202512)
- [Analytics APIs now available globally](https://partner.tiktokshop.com/docv2/page/j5k1cmia)
- [New APIs for TikTok LIVE](https://partner.tiktokshop.com/docv2/page/sv0xa2r6)
- [TikTok Shop API Rate Limits](https://partner.tiktokshop.com/docv2/page/rate-limits)

## 8. 指标口径与 UI 状态

数据页指标的自然日、店铺时区、观看人数/播放次数、归因、退款和币种口径，以[数据指标字典](./data-metric-dictionary.md)为准。未完成真实响应探针的指标必须标记为 `pending` 并在 UI 显示不可用；不得使用 Mock、0 值或推测值冒充真实数据。

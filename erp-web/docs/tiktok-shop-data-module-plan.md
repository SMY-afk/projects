# TikTok Shop 数据板块开发计划

> 状态：首期实现完成，当前处于测试店铺稳定性监控和分阶段灰度（更新于 2026-08-19）。未达到门槛的小时级、更多字段和跨连接器能力仍不得视为完成；以 `docs/tiktok-shop/data-development-status.md` 为准。

## 1. 目标与边界

目标是在 ERP 中新增“数据”板块，优先读取当前已授权店铺能够访问的官方数据，第一批关注：

- 视频数据：视频发布量、播放量、点赞、评论、分享、带货点击/成交（以官方实际返回字段为准）。
- 直播数据：直播场次、直播时长、观看人数、峰值在线、互动、商品点击/成交（以官方实际返回字段为准）。
- 店铺/商品/订单概览：作为视频和直播指标的上下文，不在本计划中重复建设已有商品、订单模块。

边界约束：

1. 浏览器只调用 ERP 内部 `/api`，不直接调用 TikTok，也不接触 `appSecret`、access token、refresh token 或签名。
2. 所有查询必须带 `tenant_id + shop_id` 服务端隔离；前端传入的 `shopId` 只能作为筛选条件，不能作为越权依据。
3. 视频/直播接口是否属于 TikTok Shop Open API，还是属于 TikTok for Business/创作者/营销数据产品，必须先核验应用权限、区域、历史时间范围和数据粒度；未确认的能力不得写死 endpoint。
4. 首期只读，不做投流、改价、改库存、直播控制或平台反向写入。
5. 真实 API 失败必须显示为真实错误，不静默回退 Mock；Mock 仅用于显式离线开发。

## 2. 推荐实施顺序

```text
官方能力核验
  -> 内部指标字典和 API 契约
  -> 后端 TikTok 数据客户端
  -> 数据库快照/明细与同步任务
  -> 租户安全的内部查询 API
  -> 前端 /data 页面和图表
  -> 真实店铺只读联调
  -> 监控、对账和灰度发布
```

## 3. 分步执行计划

### 第 0 步：确认官方接口能力与业务口径

**要做什么**

1. 针对每个数据项建立能力矩阵：API 产品名称、endpoint、HTTP 方法、必需 scope、区域限制、时间范围、分页方式、限流、更新时间延迟、是否按店铺/视频/直播间粒度返回。
2. 用当前测试店铺生成最小权限清单，确认现有 OAuth 授权是否需要增加 scope；若需增加，设计重新授权而不是绕过权限。
3. 明确指标口径：自然日/店铺时区、观看人数是去重人数还是播放次数、成交归因窗口、退款是否冲减、币种和金额字段。
4. 记录“支持/不支持/待确认”状态。待确认项先在 UI 显示不可用，不用假数据冒充真实数据。

**涉及文件**

- 新增 `erp-web/docs/tiktok-shop/data-capability-matrix.md`
- 新增 `erp-web/docs/tiktok-shop/data-metric-dictionary.md`
- 复核 `erp-api/src/erp_api/services/tiktok_authorization.py`
- 复核 `erp-api/src/erp_api/services/tiktok_client.py`
- 复核 `erp-api/src/erp_api/core/permissions.py`
- 复核双方环境变量示例文件（不写入任何密钥）

**依赖与数据结构**

```ts
type CapabilityStatus = 'supported' | 'unsupported' | 'pending'
interface DataCapability {
  entity: 'video' | 'live' | 'shop' | 'product' | 'order'
  provider: 'tiktok_shop' | 'tiktok_business' | 'other'
  endpoint: string
  scopes: string[]
  granularity: 'daily' | 'session' | 'content' | 'realtime'
  status: CapabilityStatus
}
```

**验收标准**

- 每个首期指标都有官方来源、权限和口径记录。
- 无法从当前店铺 API 读取的指标被明确标记，产品负责人确认是否延期或更换数据源。
- 不保存 token、授权码、state、App Secret 到文档、日志或前端。

### 第 1 步：冻结内部指标字典和 v1 API 契约

**要做什么**

1. 统一所有时间为 UTC ISO 8601，展示时按店铺时区转换。
2. 统一金额为最小货币单位整数 `amountMinor + currency`，比例/率使用明确的小数精度。
3. 设计概览、趋势、视频列表、直播列表四类只读接口；所有接口支持 `shopId`、时间范围和粒度。
4. 约定数据新鲜度、部分失败、无权限、无数据、平台限流等错误码。

**涉及文件**

- 修改/新增 `erp-web/docs/api-v1-contract.md`（仅追加兼容契约）
- 新增 `erp-web/docs/tiktok-shop/data-api-contract.md`
- 后端新增 `erp-api/src/erp_api/services/data_schemas.py`
- 前端新增 `erp-web/src/features/data/types/data.types.ts`

**建议数据结构**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "shopId": "uuid",
    "timezone": "America/Los_Angeles",
    "range": { "from": "2026-08-01T00:00:00Z", "to": "2026-08-14T00:00:00Z" },
    "granularity": "day",
    "items": [
      {
        "periodStart": "2026-08-13T00:00:00Z",
        "periodEnd": "2026-08-14T00:00:00Z",
        "views": 1200,
        "likes": 80,
        "comments": 12,
        "shares": 9,
        "orders": 4,
        "gmv": { "amountMinor": 19900, "currency": "USD" },
        "sourceUpdatedAt": "2026-08-14T01:05:00Z"
      }
    ],
    "freshness": { "syncedAt": "2026-08-14T01:10:00Z", "isStale": false }
  },
  "requestId": "internal-request-id"
}
```

视频明细和直播场次采用独立结构，平台原始字段只保存在后端 `raw_payload`，不直接返回 React。

### 第 2 步：扩展后端 TikTok 数据客户端和标准化层

**要做什么**

1. 在现有 `TikTokTransport` 上复用签名、超时、Retry-After、重试和安全日志。
2. 为视频、直播分别增加 client protocol 和 HTTP 实现；endpoint、版本和字段映射通过配置注入。
3. 将平台响应转换为内部 DTO，保留 `platform_request_id`、`source_updated_at` 和安全的错误分类。
4. 对分页、时间窗口、游标重复、字段缺失、未知状态做显式处理；禁止在列表接口内做同步 N+1 详情请求。

**涉及文件**

- `erp-api/src/erp_api/services/tiktok_client.py`
- 新增 `erp-api/src/erp_api/services/tiktok_data_client.py`
- 新增 `erp-api/src/erp_api/services/tiktok_data_schemas.py`
- `erp-api/src/erp_api/services/tiktok_transport.py`
- `erp-api/src/erp_api/core/config.py`
- 新增测试 `erp-api/tests/test_tiktok_data_client.py`

**依赖**

- 已有 `httpx`、Pydantic、TikTokTransport、token cipher、shop connection。
- 若官方接口需要不同产品签名/认证，新增独立 transport adapter，不修改现有 Shop 订单签名行为。

**验收标准**

- Mock HTTP server 能验证签名、分页、429/Retry-After、5xx 重试和确定性 4xx 失败。
- 原始 token、签名、PII 不出现在日志和 DTO。

### 第 3 步：建立数据持久化模型和迁移

**要做什么**

1. 保存可重复查询的日/小时聚合快照，避免每次打开页面都打平台 API。
2. 保存视频内容和直播场次的去重明细，使用平台外部 ID 做幂等 upsert。
3. 保存同步运行记录、游标、失败摘要和数据新鲜度；游标只在整批成功后提交。
4. 设计原始数据保留策略：仅后端保存、按租户/店铺隔离、可配置 TTL，不把原始 JSON 返回前端。

**涉及文件**

- 新增模型：`erp-api/src/erp_api/models/data_snapshot.py`
- 新增模型：`erp-api/src/erp_api/models/video_metric.py`
- 新增模型：`erp-api/src/erp_api/models/live_session_metric.py`
- 新增模型：`erp-api/src/erp_api/models/data_sync_run.py`
- 更新 `erp-api/src/erp_api/models/__init__.py` 和 metadata 注册
- 新增 Alembic migration：`erp-api/migrations/versions/<revision>_create_data_tables.py`
- 新增测试：`erp-api/tests/test_data_models.py`、`test_data_tenant_scope.py`

**建议表结构**

| 表                            | 关键字段                                                                                                                                                                         | 约束/用途                                                  |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `data_metric_snapshots`       | `id, tenant_id, shop_id, metric_date, granularity, metric_json, currency, source_updated_at, synced_at, raw_payload`                                                             | `(shop_id, metric_date, granularity)` 唯一；趋势与概览     |
| `video_metric_records`        | `id, tenant_id, shop_id, external_video_id, title, published_at, views, likes, comments, shares, clicks, orders, gmv_amount_minor, currency, platform_updated_at, raw_payload`   | `(shop_id, external_video_id, metric_date)` 唯一；视频列表 |
| `live_session_metric_records` | `id, tenant_id, shop_id, external_live_id, started_at, ended_at, duration_seconds, viewers, peak_viewers, interactions, clicks, orders, gmv_amount_minor, currency, raw_payload` | `(shop_id, external_live_id)` 唯一；直播场次               |
| `data_sync_runs`              | `id, tenant_id, shop_id, entity_type, mode, cursor, status, received_count, upserted_count, failed_count, error_summary, started_at, finished_at`                                | 任务审计、恢复和监控                                       |

说明：最终列类型以官方字段和现有 SQLAlchemy/Alembic 规范为准；新增 schema 属于高影响变更，实施前需单独确认。

### 第 4 步：实现同步、缓存与数据质量任务

**要做什么**

1. 首次同步使用明确时间窗口（例如最近 30 天），禁止默认无限回溯；成功后再启用增量游标。
2. 由 ARQ + Redis 执行视频/直播同步，按店铺和实体类型限并发，避免平台限流。
3. 采用 `queued/running/retry_wait/succeeded/failed/dead_letter/cancelled` 状态机和幂等 job id。
4. 对缺失日期、重复外部 ID、金额币种不一致、平台时间倒退生成质量告警，不覆盖人工可追踪记录。
5. 增加按小时/每日调度策略；页面刷新只读本地快照，必要时提供管理员“重新同步”入口。

**涉及文件**

- 新增 `erp-api/src/erp_api/services/data_sync_service.py`
- 新增 `erp-api/src/erp_api/services/data_repository.py`
- 新增/更新 `erp-api/src/erp_api/workers/data_jobs.py`
- `erp-api/src/erp_api/workers/settings.py`（或现有 ARQ 配置文件）
- 新增测试 `erp-api/tests/test_data_sync_service.py`、`test_data_sync_routes.py`

**依赖与验收**

- 依赖 PostgreSQL、Redis、ARQ 和现有 token refresh 流程。
- 重复 webhook/重复任务不会产生重复统计；失败任务可从最后成功页/游标恢复。
- 指标包含处理耗时、成功/失败数、429 次数和最后成功时间，标签不包含 token、游标、外部 ID 或 PII。

### 第 5 步：提供租户安全的后端查询 API

**要做什么**

1. 新增概览、趋势、视频、直播和同步状态路由，统一返回 v1 envelope。
2. 每个路由依赖 session 和 `data:view`；手动同步额外需要 `sync:trigger`。
3. `shopId` 不属于当前租户时统一返回 404；不把平台原始错误直接透传给前端。
4. 查询优先数据库快照；数据缺失时返回 `freshness.isStale` 和可操作错误，不在 HTTP 请求中临时执行长同步。

**涉及文件**

- 新增 `erp-api/src/erp_api/routers/data.py`
- 新增 `erp-api/src/erp_api/services/data_query_service.py`
- 更新 `erp-api/src/erp_api/main.py` 路由注册
- 更新 `erp-api/src/erp_api/core/permissions.py`（新增 `DATA_VIEW`，如当前未定义）
- 更新前端 `src/auth/permission-codes.ts`
- 新增 API/权限/跨租户测试

**建议接口**

```text
GET  /api/data/overview?shopId=&from=&to=
GET  /api/data/trends?shopId=&entity=video|live&from=&to=&granularity=day
GET  /api/data/videos?shopId=&from=&to=&page=&pageSize=&keyword=
GET  /api/data/live-sessions?shopId=&from=&to=&page=&pageSize=
GET  /api/data/sync-status?shopId=&entity=
POST /api/data/sync-jobs       # 需要 sync:trigger，首期仅管理员
```

### 第 6 步：实现前端 `/data` 页面

**要做什么**

1. 将当前 `/data` 占位页替换为真实页面，保留统一布局、权限守卫和店铺选择器。
2. 页面区域：时间/店铺筛选、核心指标卡、趋势图、视频排行、直播场次表、同步状态/数据更新时间。
3. 使用 loading、empty、stale、forbidden、platform-error 五种明确状态；部分接口失败不影响其他卡片展示。
4. 图表只使用内部 DTO；金额按 currency 展示，时间按店铺时区展示。
5. 增加显式 Mock 开关 `VITE_DATA_USE_MOCK`，真实模式错误不回退 Mock。

**涉及文件**

- 新增 `erp-web/src/features/data/types/data.types.ts`
- 新增 `erp-web/src/features/data/api/data.api.ts`
- 新增 `erp-web/src/features/data/queries/data.queries.ts`
- 新增 `erp-web/src/features/data/components/data-overview.tsx`
- 新增 `erp-web/src/features/data/components/data-trend-chart.tsx`
- 新增 `erp-web/src/features/data/components/video-metric-table.tsx`
- 新增 `erp-web/src/features/data/components/live-session-table.tsx`
- 新增 `erp-web/src/features/data/pages/data-page.tsx`
- 更新 `erp-web/src/router/route-metadata.tsx`
- 更新 `erp-web/src/services/api-mode.ts`
- 新增 Vitest 与 Playwright 测试

**依赖**

- 已有 React Query、Axios、Ant Design、ECharts、dayjs。
- 不新增图表库；如现有 ECharts 封装不足，再补最小公共组件。

### 第 7 步：真实店铺只读联调与验收

**要做什么**

1. 启动 PostgreSQL、Redis、后端和前端，先验证 `/healthz`、`/readyz`，再验证认证和店铺连接状态。
2. 使用专用测试店铺和新鲜授权，执行一次有限时间窗全量同步，再执行增量同步。
3. 逐项比对 TikTok 后台/官方接口与 ERP：总播放、总观看、场次数、订单/GMV、时区边界、分页总数。
4. 注入 401、403、429、超时、字段缺失、平台空数据，确认用户看到可理解的状态。
5. 记录接口延迟、限流、同步耗时和数据新鲜度，确定默认刷新周期。

**涉及文件**

- `erp-api/tests/integration/`（新增只读集成测试目录）
- `erp-web/tests/e2e/data.spec.ts`
- `erp-web/tests/e2e/global-setup.ts`（仅使用测试凭据，不提交秘密）
- `erp-api/README.md`、`erp-web/docs/environment-release.md`

**验收标准**

- 两个不同租户无法读取彼此店铺和指标。
- 页面与数据库快照一致，刷新不会重复请求平台或重复入库。
- 平台错误、权限不足、数据延迟和无数据状态可区分。
- `VITE_DATA_USE_MOCK=false` 时任何真实错误都可见。

### 第 8 步：监控、灰度与后续扩展

**要做什么**

1. 为每个店铺/实体监控最后成功同步时间、延迟、失败率、429 次数、死信数量和数据缺口。
2. 按“测试店铺 → 单个生产店铺 → 全部店铺”灰度，保留旧占位页回滚开关。
3. 在数据稳定后再评估小时级实时数据、更多视频字段、直播商品明细、广告归因和导出功能。
4. 若官方接口不提供视频/直播数据，另立“TikTok Business/创作者数据连接器”子项目，不把两套授权和数据模型强行混合。

## 4. 首期 MVP 建议

首期只交付：

1. 第 0、1 步的能力矩阵和指标字典。
2. 一个已确认可用的数据源（优先店铺级日趋势），完成后端 DTO、快照表、同步任务和查询 API。
3. `/data` 页面中的店铺筛选、核心指标卡、趋势图、同步时间和错误状态。
4. 视频列表、直播场次列表作为第二个垂直切片，确认接口字段后再分别上线。

这样可以先验证授权、数据时区、快照和租户隔离，再扩展到高频视频/直播明细，降低一次性接入多个不确定 API 的风险。

## 5. 开发前需要产品确认的事项

1. 首期目标区域和店铺数量，以及是否只读。
2. 视频/直播数据的官方产品来源和已批准 scope。
3. 默认查询时间范围、店铺时区、刷新频率和数据保留期。
4. GMV/订单归因口径：下单、支付、发货还是扣除退款后成交。
5. 是否允许管理员手动触发同步，及其权限与频率限制。

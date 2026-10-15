# ERP 畅销榜模块实施计划

> 编制日期：2026-08-20  
> 适用项目：`erp-api`、`erp-web`  
> 目标：在 ERP 顶部导航新增“畅销榜”，按店铺授权市场读取创作者、直播、商品、视频 Top 100，服务于选品、达人筛选和内容趋势分析。

## 1. 结论与范围边界

### 1.1 是否需要重新授权

已完成重新授权；当前不需要再次授权。

当前本地 `Akeleo Fun Toys` 店铺连接状态为 `authorized`，数据库记录的已授予 Scope 包含：

- `data.bestselling.public.read`
- `data.shop_analytics.public.read`
- `seller.authorization.info`
- `seller.finance.info`
- `seller.logistics`
- `seller.order.info`
- `seller.product.basic`
- `seller.shop.info`

四个畅销榜 API 共同要求的 Scope 已经落库：

```text
data.bestselling.public.read
```

本次店铺重新授权后的 `granted_scopes` 已包含 `data.bestselling.public.read`。服务端仍需保留 Scope 差集预检：只有未来 `required_scopes - granted_scopes` 非空时才生成目标店铺绑定的重新授权 URL；当前店铺应返回“无需重新授权”。普通 refresh 不能替代未来的 Scope 升级授权。

重新授权成功的判定条件：

```text
目标 shop 匹配
AND auth_status == authorized
AND data.bestselling.public.read in granted_scopes
AND 四个 Bestsellers API 最小只读探针成功
```

### 1.2 平台能力边界

四个官方接口分别为：

- `GET /analytics/202511/products/bestselling`
- `GET /analytics/202511/creators/bestselling`
- `GET /analytics/202511/videos/bestselling`
- `GET /analytics/202511/lives/bestselling`

共同边界：

- 每类最多返回 Top 100。
- 排名按 GMV，但 GMV 只返回脱敏区间，不能展示或推导精确 GMV。
- 数据范围是已授权卖家所在市场的畅销榜，不等同于“本店自己的商品/内容业绩榜”。
- 查询不是任意起止日期，而是 `date + time_slot`；首期只提供结束日期和 `1D / 7D / 30D`。
- 币种为 `USD | LOCAL`。
- 创作者额外支持 `author_type = ALL | OFFICIAL | CHANNEL | AFFILIATE`。
- 不能把多个 1D 结果的 GMV 区间相加来模拟任意日期范围。

## 2. 推荐产品方案

### 2.1 导航与权限

- 顶部导航新增“畅销榜”，路径 `/bestsellers`，建议放在“数据”之后、“财务”之前。
- 新增 ERP 权限 `bestsellers:view`，控制导航、路由和读取 API。
- 手动刷新继续复用 `sync:trigger`，避免再增加同义写权限。
- 重新授权继续要求 `shops:manage`。
- 普通用户缺少平台 Scope 时只显示联系管理员提示；管理员才显示“重新授权”按钮。

### 2.2 页面结构

页面分为四层：

1. 标题区：模块名称、数据市场、店铺时区、数据更新时间、Scope 状态。
2. 筛选区：店铺、结束日期、周期 `1D / 7D / 30D`、币种；创作者页额外显示作者类型。
3. 榜单 Tab：商品、创作者、视频、直播；每个 Tab 显示 Top 100 表格。
4. 状态区：缓存新鲜度、最近同步结果、失败原因、重新同步入口。

默认行为：

- 默认 Tab：商品。
- 默认周期：`7D`。
- 默认结束日期：店铺时区下最近一个可用自然日，预计通常为 T-1，以真实探针结果为准。
- 默认币种：`USD`；允许切换 `LOCAL`，两种币种不混算。
- 切换店铺或筛选条件时使用独立 React Query key，不保留其他范围的旧表格冒充当前数据。

### 2.3 四类榜单字段

通用列：排名、名称/标题、GMV 区间、统计周期、数据更新时间。

商品榜建议列：

- 商品图片、商品名称、平台商品 ID
- 排名、GMV 区间
- 类目、价格/评分/销量等字段仅在真实响应确认存在后启用

创作者榜建议列：

- 昵称、用户名、Open ID
- 作者类型、粉丝数、获赞数
- 排名、GMV 区间

视频榜建议列：

- 封面、视频标题/ID、创作者
- 发布时间、时长、播放、点赞、评论、分享
- 关联商品、排名、GMV 区间

直播榜建议列：

- 直播封面/标题/ID、主播
- 开播时间、时长、观看/互动指标
- 关联商品、排名、GMV 区间

直播和商品的最终字段必须以重新授权后的脱敏真实响应为准；未验证字段显示“暂不支持”，不能用 Mock、0 或本店 Analytics 数据代替。

### 2.4 页面状态

- `ready`：展示本地快照并显示抓取时间。
- `stale`：保留旧快照，显示“数据可能过期”，后台刷新。
- `syncing`：目标组合尚无快照时显示准备中，不展示其他组合的数据。
- `reauthorization_required`：明确列出缺少的 Scope；管理员可重新授权。
- `empty`：平台成功返回空数组，显示该市场/周期暂无榜单。
- `error`：展示安全错误摘要和 request ID，不回退 Mock。

## 3. 内部 API 契约草案

### 3.1 Scope 预检

```http
GET /api/bestsellers/authorization-status?shopId={uuid}
```

响应：

```json
{
  "apiVersion": "v1",
  "source": "local_connection",
  "data": {
    "shopId": "uuid",
    "status": "ready",
    "requiredScopes": ["data.bestselling.public.read"],
    "grantedScopes": ["data.bestselling.public.read"],
    "missingScopes": [],
    "canRead": true
  },
  "freshness": { "isStale": false, "asOf": "2026-08-20T04:00:00Z" },
  "errors": []
}
```

### 3.2 榜单读取

```http
GET /api/bestsellers/{entityType}
  ?shopId={uuid}
  &date=2026-08-19
  &timeSlot=7D
  &currency=USD
  &authorType=ALL
```

其中 `entityType = products | creators | videos | lives`，`authorType` 仅创作者使用。

响应：

```json
{
  "apiVersion": "v1",
  "source": "local_snapshot",
  "data": {
    "query": {
      "shopId": "uuid",
      "market": "US",
      "date": "2026-08-19",
      "timeSlot": "7D",
      "currency": "USD",
      "authorType": "ALL"
    },
    "items": []
  },
  "freshness": {
    "isStale": false,
    "asOf": "2026-08-20T04:00:00Z"
  },
  "errors": []
}
```

### 3.3 手动同步

```http
POST /api/bestsellers/sync
```

```json
{
  "shopId": "uuid",
  "entityTypes": ["products", "creators", "videos", "lives"],
  "date": "2026-08-19",
  "timeSlot": "7D",
  "currency": "USD",
  "authorType": "ALL"
}
```

返回统一 envelope，`data` 中包含 `jobIds` 和 `alreadyQueued`。相同店铺、实体、日期、周期、币种、作者类型使用确定性 job ID 去重。

### 3.4 重新授权

建议新增目标店铺绑定的入口：

```http
POST /api/v1/shops/tiktok/{shopId}/reauthorization-url
```

一次性 state 必须绑定 `tenantId + userId + shopId + platformShopId + intent + requiredScopes`，回调校验通过后才原子替换旧 token；失败时保留旧连接。此项属于新增公共 API，实施前需确认契约。

## 4. 数据结构设计

### 4.1 `bestseller_snapshots`

一次平台请求及其查询上下文对应一个快照。

| 字段                  | 类型                   | 说明                            |
| --------------------- | ---------------------- | ------------------------------- |
| `id`                  | UUID                   | 主键                            |
| `tenant_id`           | UUID                   | 租户边界                        |
| `shop_id`             | UUID                   | 发起授权读取的店铺              |
| `entity_type`         | varchar(16)            | `product/creator/video/live`    |
| `reference_date`      | date                   | `date`，店铺时区自然日          |
| `time_slot`           | varchar(4)             | `1D/7D/30D`                     |
| `currency`            | varchar(8)             | `USD/LOCAL`                     |
| `author_type`         | varchar(16), non-null  | 创作者枚举；其他实体固定 `NONE` |
| `entry_count`         | integer                | 0–100                           |
| `platform_request_id` | varchar(128), non-null | 平台排障 ID                     |
| `is_stale`            | boolean, non-null      | 最近一次刷新失败时为 `true`     |
| `last_error_category` | varchar(32), nullable  | 安全的归一化失败分类            |
| `last_error_at`       | timestamptz, nullable  | 最近一次刷新失败时间            |
| `refreshed_at`        | timestamptz            | 本查询组合最近完整替换时间      |

唯一键：

```text
(tenant_id, shop_id, entity_type, reference_date, time_slot, currency, author_type)
```

### 4.2 `bestseller_entries`

| 字段                     | 类型                   | 说明                          |
| ------------------------ | ---------------------- | ----------------------------- |
| `id`                     | UUID                   | 主键                          |
| `tenant_id`              | UUID                   | 租户边界                      |
| `snapshot_id`            | UUID                   | 归属快照，级联删除            |
| `rank`                   | integer                | 1–100                         |
| `external_id`            | varchar(128), non-null | 商品/创作者/视频/直播稳定标识 |
| `display_name`           | text, nullable         | 通用展示名                    |
| `gmv_range_raw`          | text, non-null         | 原样保存平台脱敏区间          |
| `gmv_currency_context`   | varchar(8), non-null   | `USD/LOCAL`，不参与金额计算   |
| `extensions`             | JSONB                  | 各实体未映射的扩展字段        |
| `raw_payload`            | JSONB, nullable        | 后端排障用原始记录副本        |
| `raw_payload_expires_at` | timestamptz, nullable  | 原始副本 TTL 截止时间         |

约束与索引：

- snapshot 使用 `(shop_id, tenant_id)` 复合外键，entry 使用 `(snapshot_id, tenant_id)` 复合外键。
- 唯一键 `(snapshot_id, rank)` 与 `(snapshot_id, external_id)`。
- snapshot 查询索引 `(tenant_id, shop_id, entity_type, reference_date)`。
- entry 排名索引 `(tenant_id, snapshot_id, rank)`。
- TTL 索引 `(raw_payload_expires_at)`。
- `gmv_range` 只能作为展示文本，禁止解析为精确金额参与求和、平均或 ROI。

Repository 只保存成功返回的完整榜单；失败时仅按完整查询组合更新已有 snapshot 的 stale 状态，不删除或改写最后一次成功 entries，也不创建半成品 snapshot。同一查询组合成功返回后通过 snapshot 唯一键 upsert，随后在同一事务中删除旧 entries 并批量插入本次 0–100 条记录，同时清除 stale 状态，保证不会混合两次排名。

`raw_payload` 复用 Analytics 原始响应 TTL（默认 30 天）。每天 03:00 的清理任务只将到期 entry 的 `raw_payload` 与 `raw_payload_expires_at` 置空；snapshot、entry 以及所有规范化字段长期保留。

## 5. 分步执行计划

### 第 0 步：冻结平台契约与真实探针清单

要做什么：

- 保存四个 API 的版本、路径、Scope、请求参数和返回字段表。
- 明确 `date + time_slot`，不承诺任意起止日期。
- 定义允许展示与待验证字段，确认 GMV 区间不可计算。

详细契约见 [`tiktok-shop/bestsellers-api-contract.md`](./tiktok-shop/bestsellers-api-contract.md)。

产出/验收：契约文档评审通过；真实响应前不将待确认字段标成 supported。

### 第 1 步：实现 Scope 预检与安全重新授权

要做什么：

- 服务端比较 `required_scopes - shop_connections.scopes`。
- 新增目标店铺绑定的重新授权 URL 和一次性 state。
- 回调换取新 token 后验证目标店铺和 `granted_scopes`，再原子替换连接。
- 对四个 API 做最小只读探针，只记录字段名、状态码和 request ID。

产出/验收：数据库 Scope 包含 `data.bestselling.public.read`；四个探针成功；无 token/code/state/cipher 泄漏。

### 第 2 步：先写后端契约测试，再实现 TikTok Client

要做什么：

- 为四类请求参数、签名上下文、响应解析、错误码、超时和 429 编写失败测试。
- 在现有 `TikTokTransport` 上增加 Bestsellers client，不复制签名/重试逻辑。
- 将四种异构响应规范化为统一 entry，并保留实体扩展字段。

产出/验收：四类样例、空数据、字段缺失、105005、429、5xx 均有测试；错误中无敏感信息。

### 第 3 步：新增持久化模型与迁移

要做什么：

- 建立 snapshot/entry 模型、复合外键、唯一键和索引。
- Repository 实现幂等 upsert：同一查询组合替换整份 Top 100，避免新旧排名混合。
- 对 `raw_payload` 执行 TTL 清理，规范化字段长期保留。

产出/验收：Alembic upgrade/downgrade 可执行；重复同步不产生重复行；tenant/shop 越权查询不可见。

### 第 4 步：同步编排与缓存策略

要做什么：

- 增加 ARQ 手动任务和每日定时任务。
- 默认每天刷新最近 `1D/7D/30D`；历史结束日期按需同步，不无限回填。
- job ID 按完整查询维度去重；失败保留最后一次成功快照并标 stale。
- 105005 映射为 `reauthorization_required`，429 映射为可重试限流，不混淆。

产出/验收：任务可去重、重试、观测；真实模式失败可见且不回退 Mock。

当前实现：`sync_bestseller_job` 每次只处理一个明确查询组合；job ID 包含 `tenant_id + shop_id + entity_type + reference_date + time_slot + currency + author_type`，按完整查询维度去重。`enqueue_scheduled_bestseller_syncs` 默认每日 `05:00 UTC` 为每个已授权且有时区的店铺生成四类实体 × `1D/7D/30D` 共 12 个任务。参考日固定为店铺时区最近一个已完成自然日；手动传入历史 `date` 时不展开日期序列、不创建回填游标。

刷新失败时，Repository 只将相同查询组合的已有 snapshot 标记为 `is_stale=true` 并记录安全错误分类和时间，最后一次成功 Top 100 保持原样；下一次成功整榜替换会清除 stale。平台错误先匹配 `TikTokRateLimitError`，映射为可重试的 `rate_limited` 并尊重 `Retry-After`；再匹配平台码 `105005`，映射为不可重试的 `reauthorization_required`，两者不会因继承关系而混淆。

### 第 5 步：实现 ERP 内部 API 与权限

要做什么：

- 增加 authorization-status、四类读取和 sync 路由。
- 增加 `bestsellers:view`，sync 复用 `sync:trigger`。
- 所有读取必须同时按 `tenant_id + shop_id` 过滤。
- 返回统一 envelope、freshness 和安全错误结构。

产出/验收：401/403/404、缺 Scope、空榜、陈旧缓存、排队中和成功响应均有路由测试。

当前实现：已注册 `GET /api/bestsellers/authorization-status`、`GET /api/bestsellers/{products|creators|videos|lives}` 和 `POST /api/bestsellers/sync`。授权状态和榜单读取要求 `bestsellers:view`；手动同步同时要求 `bestsellers:view + sync:trigger`。连接、snapshot 和 entry 读取 SQL 都显式同时过滤 `tenant_id + shop_id`；只查询本地规范化字段，不读取或返回 `raw_payload`。三个接口统一返回 `apiVersion + source + data + freshness + errors`，缺少快照、成功空榜、stale、缺 Scope 使用互不混淆的安全状态。`errors[].code` 使用固定白名单，未知内部错误统一降级为 `sync_failed`，不透传平台原文。sync 在入队前检查连接状态、Bestsellers Scope、店铺时区和已完成自然日。

### 第 6 步：前端页面与导航

要做什么：

- 增加 `/bestsellers` 懒加载路由和顶部导航。
- 实现筛选器、四个 Tab、四类表格、Scope 状态条和同步状态。
- 表格固定排名与主体列；其余列横向滚动；移动窄屏压缩筛选区。
- 用 URL query 保存 Tab 和筛选条件，便于分享与刷新恢复。
- 实数模式失败不展示 Mock；无数据、加载、同步、缺授权分开呈现。

产出/验收：导航权限正确；切换组合不串数据；Top 100 可读；键盘操作和基本无障碍标签可用。

### 第 7 步：端到端验收与灰度

要做什么：

- 后端运行全量 pytest、Alembic 和 secret scan。
- 前端运行 format check、lint、Vitest、build 和 Playwright。
- 用授权店铺验证四类榜单、周期、币种、创作者类型、刷新和重新授权。
- 先单店灰度，再开放其他店铺；保留独立 `VITE_BESTSELLERS_USE_MOCK`，生产必须为 false。

产出/验收：真实数据与平台 Top 100 抽样一致；失败状态可定位；日志无敏感信息；回滚只隐藏导航，不删除快照。

## 6. 涉及文件

### 6.1 `erp-api` 新增文件

- `src/erp_api/models/bestseller_snapshot.py`
- `src/erp_api/services/tiktok_bestseller_schemas.py`
- `src/erp_api/services/tiktok_bestseller_client.py`
- `src/erp_api/services/bestseller_repository.py`
- `src/erp_api/services/bestseller_read_repository.py`
- `src/erp_api/services/bestseller_sync_service.py`
- `src/erp_api/routers/bestseller_schemas.py`
- `src/erp_api/routers/bestsellers.py`
- `src/erp_api/workers/bestseller_jobs.py`
- `migrations/versions/0a1b2c3d4e5f_create_bestseller_snapshots.py`
- `migrations/versions/1b2c3d4e5f6a_add_bestseller_raw_payload_ttl.py`
- `migrations/versions/2c3d4e5f6a7b_add_bestseller_stale_status.py`
- `migrations/versions/3d4e5f6a7b8c_add_bestsellers_view_permission.py`
- 对应 `tests/test_bestseller_*.py`

### 6.2 `erp-api` 修改文件

- `src/erp_api/core/config.py`：四个 endpoint、TTL、定时配置。
- `src/erp_api/core/permissions.py`：`bestsellers:view`。
- `src/erp_api/models/__init__.py`：模型注册。
- `src/erp_api/main.py`：service 构建与 router 注册。
- `src/erp_api/workers/settings.py`：job/cron 注册。
- `src/erp_api/services/tiktok_authorization.py`：目标店铺和意图绑定 state。
- `src/erp_api/services/shop_repository.py`：Scope preflight、校验后原子替换。
- `src/erp_api/routers/tiktok.py`：重新授权入口与回调分支。
- `.env.*.example`：仅加入非敏感 endpoint/config 示例。

### 6.3 `erp-web` 新增文件

- `src/features/bestsellers/api/bestsellers.api.ts`
- `src/features/bestsellers/types/bestsellers.types.ts`
- `src/features/bestsellers/queries/bestsellers.queries.ts`
- `src/features/bestsellers/pages/bestsellers-page.tsx`
- `src/features/bestsellers/pages/bestsellers-page.css`
- `src/features/bestsellers/components/bestseller-filters.tsx`
- `src/features/bestsellers/components/bestseller-table.tsx`
- `src/features/bestsellers/components/product-ranking-columns.tsx`
- `src/features/bestsellers/components/creator-ranking-columns.tsx`
- `src/features/bestsellers/components/video-ranking-columns.tsx`
- `src/features/bestsellers/components/live-ranking-columns.tsx`
- `src/features/bestsellers/components/authorization-status.tsx`
- 对应 `*.test.ts(x)` 与 `tests/e2e/bestsellers.spec.ts`

### 6.4 `erp-web` 修改文件

- `src/router/route-pages.tsx`：懒加载页面。
- `src/router/route-metadata.tsx`：导航、路由和权限。
- `src/auth/permission-codes.ts`：权限常量。
- `src/services/api-mode.ts`：独立 Mock 开关。
- 环境示例和发布文档：新增 `VITE_BESTSELLERS_USE_MOCK=false`。

各 Python/TypeScript 文件按项目规范拆分，单文件不超过 300 行。

## 7. 依赖评估

预计不新增运行时依赖，复用现有技术栈：

- 后端：FastAPI、Pydantic、SQLAlchemy async、Alembic、httpx、ARQ、Redis、PostgreSQL、现有 `TikTokTransport`。
- 前端：React、TypeScript、React Router、TanStack Query、Ant Design、dayjs。
- 测试：pytest、Vitest、Testing Library、Playwright。

首期不需要 ECharts；只有在后续增加“历史排名变化”图时再复用项目现有 ECharts。

## 8. 工期与里程碑

| 阶段                         | 预计工作量 |
| ---------------------------- | ---------: |
| 契约冻结、重新授权、真实探针 |   1–2 人日 |
| Client、解析、持久化、迁移   |   2–3 人日 |
| 同步任务、内部 API、权限     |     2 人日 |
| 前端页面、状态、测试         |   2–3 人日 |
| E2E、灰度与修正              |   1–2 人日 |
| 合计                         |  8–12 人日 |

外部等待时间不计入：Scope 审批/生效、卖家重新授权、平台接口异常。

## 9. 开工前决策点

1. 确认接受官方 `1D / 7D / 30D + 结束日期`，不做任意日期拼接。
2. 确认新内部权限名使用 `bestsellers:view`，同步继续复用 `sync:trigger`。
3. 确认新增公共重新授权路由和两张数据库表。
4. 确认首期只做 Top 100 展示与快照，不做精确 GMV、跨币种汇总、自动选品评分。
5. 四接口 `7D` 最小只读探针已完成；商品/直播字段名已冻结，字段类型、单位和空值规则需在解析器开发前专项验证。

## 10. 参考资料

- [TikTok Bestsellers Analytics Open API Launch](https://partner.tiktokshop.com/docv2/page/3dk9557y)
- [Get Bestselling Products](https://partner.tiktokshop.com/docv2/page/get-bestselling-products-202511)
- [Get Bestselling Creators](https://partner.tiktokshop.com/docv2/page/get-bestselling-creators-202511)
- [Get Bestselling Videos](https://partner.tiktokshop.com/docv2/page/get-bestselling-videos-202511)
- [Get Bestselling LIVEs](https://partner.tiktokshop.com/docv2/page/get-bestselling-lives-202511)
- [TikTok authorization page updates](https://partner.tiktokshop.com/docv2/page/authorization-page-updates)
- [TikTok common errors](https://partner.tiktokshop.com/docv2/page/common-errors)

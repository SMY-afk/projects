# React + FastAPI ERP 开发计划书

> 状态：历史立项方案，已完成同级 `erp-api` 后端建设（更新于 2026-08-19）。本文的“当前缺口”和目标目录不再代表现状；实际边界以 `erp-web/README.md`、`erp-api/README.md` 和后端残片审计为准。

## 一、架构审查结论

当前前端采用 React 19 + TypeScript + Vite，按 `features` 组织业务模块，使用 React Router、TanStack Query、Axios、权限守卫、Mock/真实 API 切换和统一错误观测。这些方向合理，适合继续扩展。

当前主要缺口：

1. 项目只有 `erp-web` 前端，没有 FastAPI 后端、数据库、迁移和任务处理目录。
2. TikTok Shop 连接计划已经记录，但 OAuth、token 加密、签名、Webhook、同步任务尚未落地。
3. 商品已有分页契约；订单、库存仍主要是 Mock 或旧的无分页接口，需要统一内部 API。
4. 前端不能保存 TikTok App Secret、店铺 token 或直接调用 TikTok Open API；这些必须由后端完成。

结论：保留当前 React 前端结构，新增同级 `erp-api` FastAPI 服务；前端只访问 ERP 内部 `/api`，后端负责 TikTok Shop 集成和数据持久化。

## 二、目标目录

```text
erp-web/                         # 现有 React 前端
  src/features/shops/            # 店铺连接与授权页面
  src/features/products/         # 商品/SKU
  src/features/orders/           # 订单/履约
  src/services/                  # HTTP、认证、观测
  tests/                         # 单元与 E2E

erp-api/                         # 新增 FastAPI 后端
  app/main.py                    # FastAPI 入口、CORS、路由
  app/core/config.py             # 环境变量与配置
  app/core/security.py           # 用户认证、加密、权限
  app/db/session.py              # SQLAlchemy 数据库会话
  app/api/v1/router.py           # 内部 API 路由
  app/modules/auth/              # ERP 登录、验证码、当前用户
  app/modules/shops/             # 店铺、OAuth、连接状态
  app/modules/tiktok_shop/       # 客户端、签名、Webhook、限流重试
  app/modules/products/          # 商品与 SKU 同步/查询
  app/modules/orders/            # 订单、订单项、履约
  app/modules/sync_jobs/         # 同步任务与状态
  app/models/                    # ORM 模型
  migrations/                   # Alembic 迁移
  tests/                         # API、集成、Webhook 测试
  pyproject.toml
  .env.example
```

## 三、按优先级执行的步骤

### P0：确定边界与 API 契约

**要做什么**

- 确认首期只接 TikTok Shop 美国跨境店铺、只读商品和订单。
- 确认分页、金额、时间、错误码、权限和回调 URL 规则。
- 固定内部接口版本 `v1`，不让前端猜测 TikTok 原始字段。

**涉及文件**

- `docs/tiktok-shop/connection-scope.md`
- `docs/tiktok-shop/field-mapping.md`
- `docs/tiktok-shop/order-status-mapping.md`
- `docs/tiktok-shop/data-dictionary.md`
- `docs/backend-contract-confirmation.md`
- 新增 `erp-api/openapi/openapi.yaml`

**依赖/数据结构**

- FastAPI/Pydantic schema
- 统一响应：`{ code, message, data }`
- 列表响应：`{ items, total, page, pageSize }`
- 金额：`amountMinor: integer + currency: string`
- 时间：UTC ISO 8601

**验收**

- 前后端能根据同一份契约实现接口，不需要读取 TikTok 原始响应。

### P1：搭建 FastAPI 基础设施与 ERP 登录

**要做什么**

- 创建 `erp-api`，提供 `/api/health`。
- 配置 CORS、日志、统一异常、请求 ID、环境变量和数据库连接。
- 实现登录、服务端验证码、当前用户、权限校验，与当前前端认证契约对齐。

**涉及文件**

- `erp-api/pyproject.toml`
- `erp-api/app/main.py`
- `erp-api/app/core/config.py`
- `erp-api/app/core/security.py`
- `erp-api/app/db/session.py`
- `erp-api/app/modules/auth/{router,schemas,service,models}.py`
- `erp-web/src/services/auth/*`
- `erp-web/.env.development.local`（不提交密钥）

**依赖**

- `fastapi`
- `uvicorn[standard]`
- `pydantic-settings`
- `sqlalchemy[asyncio]`
- `asyncpg`
- `alembic`
- 密码哈希库（例如 `pwdlib`）

**验收**

- `GET /api/health` 返回成功。
- `VITE_USE_MOCK=false` 时登录、验证码、当前用户和 401 跳转可用。

### P1：数据库与租户/店铺基础模型

**要做什么**

- 建立租户、用户、角色、店铺及连接关系。
- 为店铺平台 ID 加唯一约束，区分 ERP 内部 ID 与 TikTok external ID。
- 生成第一版 Alembic migration。

**涉及文件**

- `erp-api/app/models/{tenant,user,shop,shop_connection}.py`
- `erp-api/migrations/versions/001_initial.py`
- `erp-api/app/modules/shops/{router,schemas,service}.py`

**数据结构**

- `shops(id, tenant_id, platform, platform_shop_id, region, name, status)`
- `shop_connections(shop_id, auth_status, access_token_ciphertext, refresh_token_ciphertext, expires_at, scopes)`

**验收**

- 同一租户不能重复保存同一平台店铺。
- token 数据库中只保存密文，日志不出现 token。

### P2：TikTok Shop OAuth 连接闭环

**要做什么**

- 后端生成授权链接和一次性 `state`。
- 实现 OAuth 回调、state 校验、code 换 token、刷新 token 和连接状态。
- 为临时测试支持 Cloudflare Tunnel/ngrok 的 HTTPS 回调。

**涉及文件**

- `erp-api/app/modules/tiktok_shop/oauth.py`
- `erp-api/app/modules/tiktok_shop/client.py`
- `erp-api/app/modules/shops/router.py`
- `erp-api/app/modules/shops/schemas.py`
- `erp-web/src/features/shops/{api,queries,pages,components,types}/`
- `src/router/route-metadata.tsx`
- `docs/tiktok-shop/connection-scope.md`

**依赖**

- `httpx`
- `cryptography`
- 可选 Redis：保存短期 OAuth state、限流和任务状态

**接口**

```text
POST /api/shops/tiktok/authorize
GET  /shops/tiktok/callback
GET  /api/shops
POST /api/shops/{shopId}/disconnect
```

**验收**

- TikTok 后台 Redirect URL 与运行时 URL 完全一致。
- 授权后能创建店铺连接；刷新浏览器后不暴露 App Secret 或平台 token。

### P2：TikTok 客户端安全层

**要做什么**

- 集中实现请求签名、区域 endpoint、超时、限流、重试和错误转换。
- 记录 shop、request ID、耗时和错误摘要，不记录 token 或买家 PII。

**涉及文件**

- `erp-api/app/modules/tiktok_shop/client.py`
- `erp-api/app/modules/tiktok_shop/signing.py`
- `erp-api/app/modules/tiktok_shop/errors.py`
- `erp-api/app/core/logging.py`

**验收**

- 单元测试覆盖签名、超时、429、5xx、不可重试错误。

### P3：商品与 SKU 同步（首个业务闭环）

**要做什么**

- 首轮支持指定时间范围或全量同步；商品默认全量初始化，也允许按平台更新时间指定范围回补。
- 首轮成功后才启用游标增量同步。每页幂等落库后记录恢复游标，整批成功后才提交下一轮游标，失败不得推进已提交游标。
- 保存平台原始记录和标准化内部实体。
- 前端商品列表和详情从 Mock 切换到内部 API；离线 Mock 仅在显式设置 `VITE_USE_MOCK=true` 时使用，真实模式请求失败不得自动回退 Mock。

**涉及文件**

- 后端：`app/modules/products/{models,schemas,router,service,sync}.py`
- 前端：`src/features/products/api/product.api.ts`、`types/product.types.ts`、`queries/product.queries.ts`、列表/详情页面及测试

**数据结构**

- `products(id, tenant_id, title, status, category_id, primary_image_url, updated_at)`
- `product_variants(id, product_id, internal_sku, title, attributes_json, status)`
- `channel_products(id, shop_id, product_id, external_product_id, platform_status, external_updated_at)`
- `channel_skus(id, channel_product_id, variant_id, external_sku_id, seller_sku, mapping_status)`

**验收**

- 商品按店铺、状态、关键词分页查询。
- 商品详情按 `productId` 查询并展示 SKU 明细；不存在时显示标准 `404` 状态。
- `VITE_USE_MOCK=false` 时商品列表、筛选、分页和详情只请求 ERP `/api/products`，并覆盖 loading、empty/404、403、error 和 retry。
- 重复同步使用幂等 upsert，不产生重复商品或 SKU。
- 首轮未成功时不能启动游标增量；失败重试可从恢复游标继续且不漏数。

### P4：订单、履约和 Webhook

**要做什么**

- 订单首轮默认按明确时间窗口回填，确需全量时由管理员显式触发；首轮成功后再做游标增量同步。
- 订单游标按店铺独立保存，整批成功后提交，失败任务不得推进已提交游标。
- Webhook 只验签、持久化、入队并快速响应；异步任务负责业务处理。
- 保存订单项、金额、履约、必要的脱敏地址信息。

**涉及文件**

- 后端：`app/modules/orders/*`、`app/modules/tiktok_shop/webhook.py`、`app/modules/sync_jobs/*`
- 前端：`src/features/orders/api/order.api.ts`、`types/order.types.ts`、`queries/order.queries.ts`、列表/详情页面及 E2E 测试

**数据结构**

- `orders(id, shop_id, external_order_id, order_number, status, external_status, currency, total_amount_minor, placed_at, platform_updated_at)`
- `order_lines(id, order_id, channel_sku_id, external_line_id, quantity, unit_price_minor, discount_minor, line_total_minor)`
- `fulfillments(id, order_id, external_fulfillment_id, status, carrier, tracking_number, shipped_at, delivered_at)`
- `webhook_events(id, platform_event_id, shop_id, event_type, occurred_at, payload_json, status)`
- `sync_jobs(id, shop_id, entity_type, mode, cursor, status, error_summary)`

**验收**

- 重复 Webhook 不重复创建订单。
- 订单列表支持店铺、状态、时间范围、分页和详情。
- 指定时间范围/全量回填成功后可无缝进入游标增量，失败重试不漏单。

### P5：前端真实 API 切换与可观测性

**要做什么**

- 商品、订单和 Webhook 共用后端任务状态机：`queued/running/retry_wait/succeeded/failed/dead_letter/cancelled`；Worker 通过租约和心跳回收中断任务。
- 商品/订单重试从任务级恢复游标继续，Webhook 重试从已持久化原始事件继续；人工重试创建关联原任务的新执行记录，保留审计历史。
- TikTok HTTP 请求最多 3 次尝试；商品/订单任务最多 5 次，Webhook 最多 8 次。任务按 full jitter 指数退避，本地退避上限 30 分钟；有效 `Retry-After` 至少等待平台指定时长，超过 24 小时则暂停并告警。
- 默认每租户最多并发 2 个商品/订单同步任务和 4 个 Webhook 任务；同一店铺同一实体类型最多运行 1 个。人工重试要求 `sync:trigger` 权限并记录原因。
- 任务记录有效处理耗时、排队到终态总历时、接收/成功/失败数量、最近整批成功时间及每次平台 `429`；成功数量只在页面事务提交后增加，失败重试不得重复计数。
- 新增店铺连接页面、连接状态、最后同步时间和失败提示。
- 商品、订单按模块逐个关闭 Mock，不一次性切换全部模块。
- 将 `shopId`、`syncJobId` 接入受控业务统计、日志和 trace 关联字段；通用时序指标只使用有限枚举标签，避免高基数和 PII。

**涉及文件**

- `src/features/shops/**`
- `src/features/products/**`
- `src/features/orders/**`
- `src/services/http-client.ts`
- `src/services/observability/**`
- `.env.example`
- `tests/e2e/**`

**验收**

- `VITE_USE_MOCK=false` 时核心页面只调用 ERP `/api`。
- loading、error、empty、403、401、分页和重试均有测试。

### P6：临时联调与上线前加固

**要做什么**

- 本机启动 FastAPI `localhost:8080`。
- 用 Cloudflare Tunnel 或 ngrok 暴露 HTTPS 临时域名。
- 将临时域名加上 `/shops/tiktok/callback` 填入 TikTok Partner Center。
- 增加密钥轮换、审计日志、备份、Webhook 重放和失败告警。

**涉及文件/配置**

- `erp-api/.env.example`
- `erp-api/docker-compose.yml`（可选）
- `docs/environment-release.md`
- `docs/tiktok-shop/connection-scope.md`

**验收**

- 完成授权、token 保存、商品同步、订单查询和重复 Webhook 测试。
- 后端单元测试覆盖签名、token 加密、一次性且租户绑定的 OAuth state、模块权限、商品/订单 normalizer 和幂等 upsert；包含篡改、过期、跨租户、乱序事件、事务回滚及敏感信息不泄露场景。
- API 测试覆盖登录、店铺、商品、订单、Webhook、统一错误码和租户隔离；跨租户列表不可见、详情统一 `404`，重复 Webhook 返回 `2xx` 但只持久化和入队一次。
- 集成测试分为 CI 必跑的独立受控 TikTok mock server 和发布前 TikTok 测试店铺只读冒烟。两层复用授权、商品初始化/增量、订单时间窗口/增量、Webhook 及错误恢复断言；进程内 HTTP mock 不算集成测试。
- 临时 Tunnel 地址失效时能明确显示连接状态并重新授权。

## 四、下一步开发排序

立即做：P0 → P1 后端骨架/登录 → P1 数据库店铺模型 → P2 OAuth。

暂缓：仓库、广告、财务、多平台聚合和平台反向写操作。这些依赖商品、订单、权限和同步链路稳定后再做。

首个可交付 MVP：一个 TikTok Shop 美国跨境店铺完成授权，商品/SKU 和订单只读同步，前端真实 API 可分页查询，并能显示同步状态和失败原因。

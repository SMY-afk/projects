# ERP FastAPI 后端开发计划书

> 状态：历史架构方案，核心目标已由唯一后端 `erp-api` 实施（更新于 2026-08-19）。文中的 `erp-api/app/...` 是早期目标结构，当前可安装包位于 `erp-api/src/erp_api/`；不得据此新建第二套后端。

## 0. 目标与边界

目标是在现有 `erp-web` React/Vite 前端旁边新增 `erp-api` FastAPI 服务，首期打通：

```text
ERP 登录/权限
    -> TikTok Shop 店铺 OAuth 授权
    -> 店铺 token 安全保存
    -> 商品/SKU 只读同步
    -> 订单/履约只读同步
    -> React 通过 ERP 内部 /api 查询
```

首期范围限定为 TikTok Shop 美国跨境店铺；暂不开发仓库、广告、财务、多平台聚合和平台反向写操作。TikTok 的具体 endpoint、签名规则和 scope 必须以当前 Partner Center/API 文档为准，不在后端计划中猜测。

### 已确认的首期接入参数

- 目标市场：United States（美国站）
- 卖家类型：Cross-border sellers（跨境卖家）
- 跨境主体国家：中国（China）
- 测试店铺数量：1 家
- 数据范围：只读店铺信息、商品、SKU、订单、订单明细和履约/物流状态
- 事件范围：接收订单变更 Webhook，但首期不向 TikTok 写入业务数据

## 1. 目标后端目录

```text
erp-api/
  app/
    main.py                         # FastAPI 应用入口
    api/v1/router.py                # 版本化路由汇总
    core/
      config.py                    # pydantic-settings 配置
      errors.py                    # 统一异常与错误码
      logging.py                   # 请求 ID、脱敏日志
      security.py                  # JWT/密码哈希/加密工具
    db/
      session.py                    # Async SQLAlchemy engine/session
      base.py                       # ORM metadata
    models/                         # ORM 数据模型
    modules/
      auth/                         # 登录、验证码、用户、角色、权限
      tenants/                      # 租户隔离
      shops/                        # 店铺和连接状态
      tiktok_shop/                  # OAuth、签名、客户端、Webhook
      products/                     # 商品/SKU 查询与同步
      orders/                       # 订单/订单项/履约查询与同步
      sync_jobs/                    # 同步任务、重试、进度
    workers/                        # 异步任务入口
  migrations/                      # Alembic migration
  tests/
    unit/
    api/
    integration/
  openapi/                          # 内部 API 契约（可选导出）
  pyproject.toml
  .env.example
  README.md
```

## 2. 分阶段执行步骤

### P0：冻结契约和外部前置条件

**要做什么**

- 确认首期市场、卖家类型、店铺数量和只读范围。
- 在 TikTok Partner Center 确认 App Key、App Secret、Redirect URL、批准的 scopes、Webhook 事件和 API 版本。
- 固定内部 API v1：统一响应、错误码、分页、金额和时间格式。
- 确定开发数据库、Redis 是否需要，以及临时 HTTPS 回调方案。

本阶段已固定的内部规则见 `docs/api-v1-contract.md`：统一响应 `{ code, message, data, requestId }`、稳定错误码、1-based 分页、`amountMinor + currency` 金额和 UTC ISO 8601 时间。

**涉及文件**

- `docs/tiktok-shop/connection-scope.md`
- `docs/tiktok-shop/field-mapping.md`
- `docs/tiktok-shop/order-status-mapping.md`
- `docs/tiktok-shop/data-dictionary.md`
- `docs/backend-contract-confirmation.md`
- 新增 `erp-api/openapi/openapi.yaml`

**预计依赖/结构**

- FastAPI/Pydantic schema
- 成功响应：`{ code, message, data }`
- 分页响应：`{ items, total, page, pageSize }`，页码从 1 开始
- 金额：`amountMinor: integer` + `currency: string`
- 时间：UTC ISO 8601，例如 `2026-08-11T10:20:00Z`

**验收**

- 前端和后端可以根据同一份契约实现，不直接依赖 TikTok 原始 JSON。

### P1：创建 FastAPI 服务骨架

**要做什么**

- 创建 `erp-api` Python 项目和虚拟环境。
- 实现 `/api/health`、启动配置、CORS、请求 ID、统一异常处理和结构化日志。
- 配置开发/测试/生产环境分离，禁止把密钥提交到 Git。
- 让现有 Vite `/api` 代理可以访问 `http://localhost:8080`。

**涉及文件**

- `erp-api/pyproject.toml`
- `erp-api/app/main.py`
- `erp-api/app/api/v1/router.py`
- `erp-api/app/core/config.py`
- `erp-api/app/core/errors.py`
- `erp-api/app/core/logging.py`
- `erp-api/.env.example`
- `erp-web/.env.development.local`（本地文件，不提交）
- `erp-api/tests/api/test_health.py`

**预计依赖**

- `fastapi`
- `uvicorn[standard]`
- `pydantic-settings`
- `python-multipart`
- `httpx`（测试与外部 API 客户端）
- `pytest`、`pytest-asyncio`、`ruff`

**验收**

- `uvicorn app.main:app --reload --port 8080` 可启动。
- `GET /api/health` 返回版本和环境信息但不泄露密钥。
- `npm run dev` 下前端 `/api` 请求能代理到后端。

### P1：数据库、迁移和租户隔离

**要做什么**

- 建立 SQLAlchemy async engine、session 和 Alembic。
- 建立租户、用户、角色、权限、店铺和连接模型。
- 所有业务查询强制带 `tenant_id`，避免跨租户读取。
- 为平台与外部 ID 建唯一索引。

**涉及文件**

- `erp-api/app/db/session.py`
- `erp-api/app/db/base.py`
- `erp-api/app/models/tenant.py`
- `erp-api/app/models/user.py`
- `erp-api/app/models/role.py`
- `erp-api/app/models/shop.py`
- `erp-api/app/models/shop_connection.py`
- `erp-api/alembic.ini`
- `erp-api/migrations/env.py`
- `erp-api/migrations/versions/001_initial.py`

**预计依赖**

- `sqlalchemy[asyncio]`
- `asyncpg`（PostgreSQL）
- `alembic`
- `redis`（可选，state、限流、短期缓存）

**核心数据结构**

```text
tenants(id, name, status, created_at)
users(id, tenant_id, username, password_hash, status, created_at)
roles(id, tenant_id, code, name)
user_roles(user_id, role_id)
permissions(id, code, name)
role_permissions(role_id, permission_id)
shops(id, tenant_id, platform, platform_shop_id, region, name, status, created_at)
shop_connections(
  id, shop_id, auth_status, access_token_ciphertext,
  refresh_token_ciphertext, expires_at, scopes, last_error, updated_at
)
```

**验收**

- migration 可重复执行和回滚。
- `shops(tenant_id, platform, platform_shop_id)` 唯一。
- token 字段只保存密文，日志和 API 响应不返回 token。

### P1：ERP 登录、验证码和权限

**要做什么**

- 实现登录、当前用户、登出和服务端一次性验证码。
- 使用短期 access token；前端继续通过 `Authorization: Bearer` 调用内部 API。
- 实现模块级权限依赖，至少支持 `shops:view`、`shops:manage`、`products:view`、`orders:view`、`sync:trigger`。
- 401/403 与当前 `erp-web` 的 route guards 和统一错误处理对齐。

**涉及文件**

- `erp-api/app/modules/auth/router.py`
- `erp-api/app/modules/auth/schemas.py`
- `erp-api/app/modules/auth/service.py`
- `erp-api/app/modules/auth/models.py`
- `erp-api/app/core/security.py`
- `erp-web/src/services/auth/auth-api.ts`
- `erp-web/src/services/auth/auth-client.ts`
- `erp-web/src/router/route-guards.tsx`
- `erp-api/tests/api/test_auth.py`

**预计依赖**

- `pwdlib[argon2]` 或等价密码哈希库
- `pyjwt` 或 `python-jose`
- `itsdangerous`/Redis（验证码和短期 state）
- `slowapi` 或网关限流

**接口**

```text
GET  /api/auth/captcha
POST /api/auth/login
GET  /api/auth/current-user
POST /api/auth/logout
```

**验收**

- 验证码短期、一次性、服务端校验，失败也立即失效。
- `VITE_USE_MOCK=false` 时前端登录和权限菜单正常工作。

### P2：TikTok Shop OAuth 连接闭环

**要做什么**

- 后端生成授权 URL 和一次性 `state`，state 绑定当前用户/租户并设置过期时间。
- 接收回调，校验 state，使用 code 换取 token，解析店铺身份并 upsert `shops`/`shop_connections`。
- 实现 token 刷新、断开连接、连接状态查询。
- App Secret、token 加密密钥只放后端环境变量或 Secret Manager。

**涉及文件**

- `erp-api/app/modules/shops/router.py`
- `erp-api/app/modules/shops/schemas.py`
- `erp-api/app/modules/shops/service.py`
- `erp-api/app/modules/tiktok_shop/oauth.py`
- `erp-api/app/modules/tiktok_shop/client.py`
- `erp-api/app/core/security.py`
- `erp-web/src/features/shops/api/shop.api.ts`
- `erp-web/src/features/shops/queries/shop.queries.ts`
- `erp-web/src/features/shops/pages/shop-list-page.tsx`
- `erp-web/src/features/shops/types/shop.types.ts`
- `erp-web/src/router/route-metadata.tsx`

**预计依赖**

- `httpx`
- `cryptography`（token 对称加密）
- Redis（推荐，用于 state 一次性消费和限流）

**接口**

```text
POST /api/shops/tiktok/authorize
GET  /shops/tiktok/callback
GET  /api/shops
GET  /api/shops/{shop_id}
POST /api/shops/{shop_id}/disconnect
```

**验收**

- Partner Center 的 Redirect URL 与运行时 URL 完全一致。
- 授权成功后只返回连接状态和店铺摘要，不返回 access/refresh token。
- 重复回调、错误 state、过期 token 都有明确错误和审计记录。

### P2：TikTok API 客户端安全层

**要做什么**

- 集中实现 TikTok 请求签名、endpoint、headers、超时、重试、429 限流和错误映射。
- 每个请求记录 tenant/shop、平台 request ID、耗时、结果和脱敏错误。
- 将 TikTok 原始响应转换为内部 schema，不让平台字段泄漏到 React。

**涉及文件**

- `erp-api/app/modules/tiktok_shop/client.py`
- `erp-api/app/modules/tiktok_shop/signing.py`
- `erp-api/app/modules/tiktok_shop/errors.py`
- `erp-api/app/modules/tiktok_shop/normalizers.py`
- `erp-api/tests/unit/test_signing.py`
- `erp-api/tests/integration/test_tiktok_client.py`

**预计依赖**

- `httpx`
- `tenacity`（指数退避重试）
- `limits`/Redis（按店铺限流，可与网关配合）

**验收**

- 单元测试覆盖签名输入、429、5xx、超时、不可重试 4xx。
- 任意日志搜索不到完整 token、App Secret 和买家地址/电话。

### P3：商品和 SKU 同步

**要做什么**

- 同步分两阶段：首轮支持指定时间范围或全量同步；首轮成功后，后续任务才使用平台返回的游标做增量同步。
- 商品默认全量初始化，也允许按平台更新时间指定范围回补；订单默认指定时间范围回填，避免无限回溯。
- 游标按店铺和实体类型隔离保存。每页数据完成幂等 upsert 后记录任务恢复游标，整批成功后才提交下一轮增量游标；失败任务不得推进已提交游标。
- 使用事务和幂等 upsert，保存必要原始记录用于排错。
- 提供服务端分页查询和商品详情接口；`VITE_USE_MOCK=false` 时前端商品列表、筛选和详情只调用 ERP API，不得在请求失败时自动回退商品 Mock。

**涉及文件**

- `erp-api/app/models/product.py`
- `erp-api/app/models/product_variant.py`
- `erp-api/app/models/channel_product.py`
- `erp-api/app/models/channel_sku.py`
- `erp-api/app/modules/products/{router,schemas,service,sync}.py`
- `erp-api/migrations/versions/002_products.py`
- `erp-web/src/features/products/api/product.api.ts`
- `erp-web/src/features/products/types/product.types.ts`
- `erp-web/src/features/products/queries/product.queries.ts`
- `erp-web/tests/e2e/products.spec.ts`

**核心数据结构**

```text
products(id, tenant_id, title, status, category_id, primary_image_url, updated_at)
product_variants(id, product_id, internal_sku, title, attributes_json, status)
channel_products(id, shop_id, product_id, external_product_id, platform_status, external_updated_at)
channel_skus(id, channel_product_id, variant_id, external_sku_id, seller_sku, mapping_status)
raw_platform_records(id, shop_id, entity_type, external_id, payload_json, payload_hash, fetched_at)
```

**接口**

```text
GET  /api/products?page=1&pageSize=20&shopId=&keyword=&status=
GET  /api/products/{product_id}
POST /api/sync-jobs/products
```

**验收**

- 返回 `{ items, total, page, pageSize }`。
- `GET /api/products` 按 `shopId/page/pageSize/keyword/status` 服务端筛选和分页；`GET /api/products/{product_id}` 返回指定商品及 SKU 明细，不存在时返回标准 `404`。
- 商品详情页处理 loading、empty/404、403、error 和 retry；列表进入详情后返回时保留原筛选与分页状态。
- `VITE_USE_MOCK=false` 时网络面板中商品模块只出现 ERP `/api/products` 请求，接口失败显示真实错误且不展示 Mock 数据。
- 相同 external ID 重复同步不会产生重复记录。
- 未映射 SKU 显示 `unmapped`，不按名称自动猜测。
- 未完成指定时间范围/全量同步时不能启动游标增量；首轮成功后可从已提交游标继续，失败重试不漏数、不重复建档。

### P4：订单、履约和 Webhook

**要做什么**

- 订单首轮默认按明确时间窗口回填；确需全量时由管理员显式触发。首轮成功后再进入游标增量同步。
- 增量任务复用商品同步的游标提交规则：分页结果先幂等落库，整批成功后再提交下一轮游标，失败从最近恢复点重试。
- Webhook 入口完成验签、去重、原始事件持久化后快速返回；业务处理进入任务队列。
- 订单金额使用最小货币单位；地址和电话最小化保存并加密/脱敏。

**涉及文件**

- `erp-api/app/models/order.py`
- `erp-api/app/models/order_line.py`
- `erp-api/app/models/fulfillment.py`
- `erp-api/app/models/webhook_event.py`
- `erp-api/app/models/sync_job.py`
- `erp-api/app/modules/orders/{router,schemas,service,sync}.py`
- `erp-api/app/modules/tiktok_shop/webhook.py`
- `erp-api/app/workers/sync_worker.py`
- `erp-api/migrations/versions/003_orders.py`
- `erp-web/src/features/orders/api/order.api.ts`
- `erp-web/src/features/orders/types/order.types.ts`
- `erp-web/src/features/orders/queries/order.queries.ts`

**核心数据结构**

```text
orders(id, shop_id, external_order_id, order_number, status, external_status,
       currency, total_amount_minor, placed_at, platform_updated_at)
order_lines(id, order_id, channel_sku_id, external_line_id, quantity,
            unit_price_minor, discount_minor, line_total_minor)
fulfillments(id, order_id, external_fulfillment_id, status, carrier,
             tracking_number, shipped_at, delivered_at)
webhook_events(id, platform_event_id, shop_id, event_type, occurred_at,
               payload_json, payload_hash, status, processed_at)
sync_jobs(id, shop_id, entity_type, mode, cursor, status, started_at,
          finished_at, error_summary)
```

**接口**

```text
POST /api/tiktok/webhooks
GET  /api/orders?page=1&pageSize=20&shopId=&status=&updatedFrom=&updatedTo=
GET  /api/orders/{order_id}
POST /api/sync-jobs/orders
GET  /api/sync-jobs/{job_id}
```

**验收**

- 重复 webhook 不重复创建订单。
- 订单列表支持店铺、状态、时间范围、分页和详情。
- webhook 处理失败可重试，失败原因可在 ERP 中查看。
- 指定时间范围/全量回填成功后可进入游标增量，失败重试不漏单。

### P5：任务、同步和可观测性

**要做什么**

- 为商品、订单、Webhook 建立统一的可恢复任务状态机；业务处理器不同，但状态转换、租约、重试、恢复点和审计规则共用。
- 状态统一为 `queued → running → succeeded`；临时错误进入 `retry_wait` 后按退避时间重新排队，不可重试错误进入 `failed`，超过最大重试次数进入 `dead_letter`，人工取消进入 `cancelled`。
- Worker 领取任务时写入租约、执行实例和心跳。租约过期的 `running` 任务由调度器安全回收；商品/订单从任务级 `recovery_cursor` 续跑，Webhook 从已持久化事件重新处理。
- `succeeded/failed/dead_letter/cancelled` 为终态。人工重试创建关联原任务的新执行记录，不覆盖原任务状态、错误和尝试历史。
- 区分请求级与任务级重试，避免重试叠加：TikTok HTTP 请求保持最多 3 次尝试（首次 + 2 次重试），基础退避 `0.5s`、上限 `30s`；商品/订单任务最多 5 次尝试，Webhook 任务最多 8 次尝试。
- 任务退避使用 full jitter：`random(0, min(30m, 30s * 2^(attempt-1)))`，其中 30 分钟只限制本地计算的退避。平台返回有效 `Retry-After` 时至少等待平台指定时长；若超过 24 小时则暂停自动重试并告警，等待管理员确认。不得在 Worker 内长时间 sleep，写入 `next_retry_at` 后释放租约。
- 仅对 `429`、超时、网络中断和 `5xx` 自动重试；参数/权限等确定性 `4xx` 直接 `failed`，授权失效在单次令牌刷新失败后进入 `failed` 并告警。可重试错误耗尽次数后进入 `dead_letter`。
- 人工重试要求 `sync:trigger` 权限，必须填写原因并记录操作者、原任务 ID 和恢复点；创建新任务执行，不重置或覆盖原终态任务。若配置、授权或数据错误尚未解除，应拒绝重复提交。
- 默认租户级并发配额为商品/订单同步 2 个、Webhook 处理 4 个；同一 `tenant_id + shop_id + entity_type` 同时最多 1 个运行任务。配额通过配置调整，队列领取时原子校验，Webhook 使用独立队列以免被全量同步阻塞。
- 统一记录任务指标：`sync_job_active_duration_seconds` 为各次 `running` 有效处理时间之和（不含排队和退避），`sync_job_elapsed_seconds` 为首次入队到终态的总历时；另记录 `queue_wait_seconds` 和各次尝试耗时，避免把限流等待误判为处理性能下降。
- 每个任务记录 `received_count/succeeded_count/failed_count`。记录完成页面事务提交后才增加 `succeeded_count`；页面回滚不得计成功。`failed_count` 只统计任务终态时仍未落库的源记录，重试过程中的瞬时失败单独计入 `attempt_error_count`，不得重复累计为业务失败。
- `last_successful_at` 按 `tenant_id + shop_id + entity_type` 保存，仅在指定时间范围/全量或增量任务整批进入 `succeeded` 后更新；部分成功、失败、取消、死信及单个 Webhook 事件不得推进该时间。
- `platform_rate_limit_total` 在收到 TikTok `429` 时逐次增加，包括请求级重试中的每次响应；同时记录安全的 endpoint 类别和 `Retry-After`，不得按最终任务失败数推算限流次数。
- 指标标签只使用 `platform/entity_type/mode/status/error_class` 等有限枚举。`tenant_id/shop_id/sync_job_id` 只进入受控业务统计、日志或 trace 关联字段，不作为无界时序指标标签；游标、外部商品/订单 ID、地址和电话禁止进入指标或日志标签。

**涉及文件**

- `erp-api/app/modules/sync_jobs/*`
- `erp-api/app/workers/*`
- `erp-api/app/core/logging.py`
- `erp-api/app/modules/observability/*`
- `erp-web/src/services/observability/*`
- `docs/observability.md`

**预计依赖**

- 临时测试：FastAPI `BackgroundTasks` 仅用于短任务
- 推荐：Celery + Redis，或 Arq + Redis
- 生产：独立 worker，不在 Web 进程中执行长时间全量同步

**验收**

- Webhook 请求不等待完整同步。
- 任务可查询状态，可安全重试，重试不产生重复数据。
- 任务状态转换使用条件更新，确保同一任务同一时刻最多只有一个有效租约；重复投递和 Worker 崩溃不会造成重复业务记录。
- 临时错误可自动恢复，超过重试上限进入死信；管理员可查看完整尝试历史并从最近安全恢复点重新执行。
- 测试使用固定随机源验证退避范围、`Retry-After` 优先级和最大等待时间；并发测试证明租户配额及同店铺同实体互斥生效，队列饱和时任务保持 `queued` 而不是丢失。
- 指标测试覆盖事务提交/回滚、重试后成功、最终失败、取消、死信和连续多个 `429`；验证计数不重复、`last_successful_at` 只在整批成功时推进，指标标签不含高基数 ID 或 PII。

### P6：测试、临时联调和切换真实 API

**要做什么**

- 单元测试覆盖签名、token 加密、OAuth state、权限、normalizer 和幂等 upsert；每类必须同时包含成功、拒绝/异常和敏感信息不泄露场景。
- 签名：固定时间和固定请求体校验规范化 query、原始 JSON bytes、路径及 HMAC 结果；query/body 改动必须导致签名变化，认证换 token 请求不得误签名，日志不得包含 App Secret 或 access token。
- token 加密：验证加密后不含明文、正确密钥可往返解密、随机 nonce 使相同明文产生不同密文、错误密钥和篡改密文解密失败；模型和日志只暴露 ciphertext 字段。
- OAuth state：验证高熵随机值、绑定 `user_id + tenant_id`、短 TTL、一次性消费；缺失、未知、过期、跨租户和重放 state 均拒绝，失败时不得交换授权码。
- 权限：对 `shops:manage/products:view/orders:view/sync:trigger/orders:buyer-pii:view` 做允许与拒绝测试；多权限依赖要求全部满足，未知权限码启动时失败，并验证不同租户不能借相同资源 ID 越权访问。
- normalizer：用冻结的 TikTok fixture 覆盖商品/SKU、订单/订单项/履约；校验金额转最小货币单位、UTC 时间、状态映射、可空/未知枚举、字段缺失和类型错误。平台新增字段应被安全忽略，平台原始字段和 PII 不得意外进入内部响应模型。
- 幂等 upsert：同一 `tenant_id + shop_id + external_id` 重放结果只有一条记录；更新可变字段但保持内部 ID；不同店铺/租户可使用相同 external ID。覆盖乱序旧事件不覆盖新值、父子实体原子提交、页面回滚不推进恢复游标，以及重复页面/Webhook/任务重试不重复累计业务记录和成功指标。
- API 测试覆盖登录、店铺、商品、订单、Webhook、统一错误契约和租户隔离；所有端点同时验证 HTTP 状态码、业务 `code`、响应包装和 `requestId`。
- 登录：验证码响应使用 `Cache-Control: no-store`；正确凭据可登录并访问 current-user，错误验证码/密码返回通用错误且验证码立即失效；验证码不可跨会话或重放。无效/过期 token 返回 `401 AUTH_UNAUTHORIZED`，登出后原会话不可再用。
- 店铺：`shops:view` 可查询列表/详情且响应不含明文 token，`shops:manage` 才能授权、刷新和断开；OAuth callback 拒绝缺失/过期/重放 state。不存在或其他租户店铺统一返回 `404 RESOURCE_NOT_FOUND`，不得泄露其存在性。
- 商品：列表验证 1-based 分页、最大 `pageSize`、`shopId/keyword/status` 筛选、空页和稳定排序；详情返回商品及 SKU，不存在或跨租户均为 `404`。触发同步要求 `sync:trigger`，重复运行冲突返回 `409 RESOURCE_CONFLICT`。
- 订单：列表验证店铺、状态、UTC 时间窗口、分页和非法时间范围；详情金额使用 `amountMinor + currency`。普通 `orders:view` 响应只含脱敏地址/电话，完整 PII 另需 `orders:buyer-pii:view`；不存在或跨租户订单统一返回 `404`。
- Webhook：验签失败、过期时间戳、非法 payload 不持久化也不入队；合法事件持久化后快速返回 `2xx`。同一事件重复投递仍返回 `2xx`，但原始事件和队列消息各只有一份；队列不可用时不得先返回成功，防止事件丢失。
- 错误契约：参数组合错误、未认证、无权限、资源不存在、状态冲突、字段校验、限流、平台错误、依赖不可用和未预期错误分别覆盖 `400/401/403/404/409/422/429/502/503/500`，并断言 `details` 不含 token、密钥、SQL、堆栈或买家 PII。
- 租户隔离：使用两个租户和可碰撞的 external ID 建立数据；租户 A 的列表、详情、同步任务及写操作都不能读取或修改租户 B 数据。跨租户详情返回 `404` 而非 `403`，数据库会话缺少租户上下文时请求必须失败关闭（fail closed）。
- 集成测试分两层：CI 必跑独立进程的受控 TikTok mock server；staging/发布前再跑 TikTok 测试店铺只读冒烟。进程内 `httpx.MockTransport` 只算单元测试，不能替代真实 HTTP、数据库、Redis、队列和 Worker 链路。
- 受控环境启动 ERP API、PostgreSQL、Redis、Worker 和 mock server。mock server 必须校验请求签名、access token、query/body 原始字节，并提供确定性 fixture、分页 cursor、订单时间窗口和 Webhook 签名；测试不得依赖外网或真实平台密钥。
- CI 场景覆盖 OAuth 换 token/刷新、商品全量与指定范围初始化、订单时间窗口回填、首轮成功后的游标增量、商品/订单幂等 upsert、Webhook 验签/去重/可靠入队，以及内部列表/详情 API 查询结果。
- 故障场景覆盖 `429 + Retry-After`、超时、连接中断、`5xx`、确定性 `4xx`、无效/过期 token、畸形响应、分页中途失败、Worker 在事务前后退出和队列短暂不可用；断言重试/死信符合规则、页面事务回滚、恢复游标正确且失败不推进已提交游标。
- 测试店铺仅使用专用非生产店铺和受保护 CI/staging secrets，不在 PR 日志或测试报告输出 token、签名密钥、原始买家 PII。使用固定只读数据窗口，禁止对生产店铺运行，禁止创建、修改或删除平台业务数据。
- 测试店铺冒烟复用 mock server 的核心断言：授权与店铺身份、至少两页商品/SKU（数据不足时验证单页终止）、明确时间窗口订单、一次增量续跑和一个签名 Webhook。记录平台 API 版本、scope、request id 和脱敏结果，失败时区分代码回归与平台不可用，但未通过不得晋级生产。
- 受控 mock server 测试为每个 PR 的稳定门禁；测试店铺测试在手动 staging、定时 nightly 和 release candidate 执行。外部平台不可用允许标记基础设施失败后重跑，不得改为跳过或视为通过。
- 本机后端监听 `localhost:8080`，用 Cloudflare Tunnel/ngrok 获取 HTTPS 回调。
- `VITE_USE_MOCK=false` 时按商品 → 订单顺序逐模块切换。

**涉及文件**

- `erp-api/tests/unit/*`
- `erp-api/tests/api/*`
- `erp-api/tests/integration/*`
- `erp-api/pytest.ini`
- `erp-api/.env.example`
- `erp-web/.env.development.local`
- `erp-web/tests/e2e/*`
- `docs/environment-release.md`

**验收**

- OAuth 授权、token 保存、商品同步、订单查询、重复 webhook 全流程通过。
- 现有签名、token 加密、state 和权限测试保持回归通过；normalizer 与幂等 upsert 测试必须随商品/订单同步模块新增，在对应实现合并前不得标记完成。
- 现有登录、店铺连接、TikTok 错误映射和租户作用域 API 测试保持回归通过；商品、订单、Webhook 入队和同步任务 API 测试随对应端点实现新增，在全矩阵通过前不得切换真实流量。
- 受控 mock server 必须证明 API → TikTok HTTP → 数据库/队列 → Worker → 内部查询 API 的端到端链路；测试店铺只读冒烟通过并留存脱敏报告后，发布候选版本才能进入生产灰度。
- `ruff check`、`pytest`、前端 `npm run lint:types`、`npm run test`、`npm run build` 全部通过。

## 3. 建议环境变量

后端 `.env.example` 只列名称和示例占位符，不提交真实值：

```dotenv
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8080
DATABASE_URL=postgresql+asyncpg://erp:change-me@localhost:5432/erp
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=replace-in-secret-manager
TOKEN_ENCRYPTION_KEY=
TIKTOK_APP_KEY=replace-in-secret-manager
TIKTOK_APP_SECRET=
TIKTOK_REDIRECT_URI=https://temporary-tunnel.example/shops/tiktok/callback
ALLOWED_ORIGINS=http://localhost:5173
```

`TIKTOK_APP_SECRET`、`TOKEN_ENCRYPTION_KEY`、数据库密码和 JWT 密钥绝不能放入 React 的 `VITE_*` 变量。

## 4. 推荐执行顺��与首个交付物

按 `P0 → P1 骨架 → P1 数据库/认证 → P2 OAuth → P2 客户端安全层 → P3 商品 → P4 订单/Webhook → P5 任务 → P6 联调` 执行。

首个可验收版本不是“所有 ERP 模块完成”，而是：

1. FastAPI 可启动并通过健康检查；
2. React 可使用真实登录接口；
3. 一个美国跨境 TikTok Shop 店铺可以完成 OAuth 授权；
4. 连接凭证只在后端加密保存；
5. 商品/SKU 可幂等同步并分页查询；
6. 订单可按时间窗口查询，重复 webhook 不重复入库。

## 5. 明确暂缓事项

- 仓库模块及库存同步
- 广告、财务、结算和对账
- TikTok 平台写操作（改价、改库存、发货、退款）
- 多平台抽象层
- 复杂报表和 BI

这些功能应在 OAuth、数据模型、同步、权限和审计链路稳定后再立项。

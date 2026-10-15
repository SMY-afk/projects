# ERP 对接 TikTok Shop 真实数据实施计划

> 状态：核心店铺、商品、订单和同步链路已实施，保留为历史范围与契约基线（更新于 2026-08-19）。库存仍明确暂缓；实时运行状态以 `docs/tiktok-shop/data-development-status.md` 为准。

## 1. 目标与边界

本计划已确认“TK”指 **TikTok Shop**。目标是将当前前端中的 Mock 数据替换为由 ERP 后端统一提供的真实业务数据，首批完成店铺、商品和订单的查询与同步闭环。库存模块暂时留白：不接入 TikTok Shop 库存、不建设库存后端数据表和同步任务、不展示前端假库存。

浏览器不得直接调用 TikTok Shop Open API，也不得保存 `appSecret`、店铺授权密钥或刷新令牌。所有平台授权、签名、回调验签、限流、重试、数据标准化和持久化均由 ERP 后端处理；`erp-web` 只调用内部 `/api`。

首期范围：

- 店铺授权与连接状态；
- TikTok Shop 的商品、SKU、订单、履约/物流状态同步；
- 同步任务、失败告警与数据可追溯；
- 前端商品、订单列表/详情切换为内部真实 API。

暂不在首期承诺：库存、广告、结算/财务对账、多平台聚合、ERP 向 TikTok Shop 反向改价/改库存。它们依赖首期主数据和同步机制稳定后再排期。

## 2. 推荐推进顺序

```text
TikTok Shop 授权/回调
        ↓
店铺连接与令牌安全存储
        ↓
商品 + SKU 主数据同步 ──→ SKU 映射
        ↓                        ↓
订单增量同步 / Webhook ──→ 订单明细与履约
        ↓
内部 ERP API → erp-web 切换 Mock → 联调与上线观测
```

## 3. 分阶段执行清单

| 阶段            | 要做什么                                                                                                                  | 依赖                                                    | 验收结果                                                            |
| --------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------- |
| 0. 接入准备     | 申请/确认 TikTok Shop 开放平台应用、目标区域、店铺类型和所需 scope；确认 API 版本、Webhook 事件、速率限制与数据保留要求。 | 平台开发者账号、商家授权人、合规审批。                  | 拿到 sandbox 或测试店铺；形成已签字的字段与权限清单。               |
| 1. 领域与契约   | 定义内部统一模型、状态枚举、分页/错误/时间/金额规范；不把 TikTok 原始字段直接暴露给前端。                                 | 业务确认商品、订单和履约口径。                          | `openapi.yaml` 或等价 API 文档；数据库迁移可执行。                  |
| 2. 接入后端基础 | 建立 TikTok Shop Connector：OAuth/授权回调、令牌加密存储、请求签名、限流、重试、审计日志。                                | 阶段 0 的 app key、app secret、回调地址、密钥管理服务。 | 可安全连接测试店铺，能显示连接成功/失效。                           |
| 3. 商品与 SKU   | 全量拉取商品/SKU，保存平台原始响应和规范化实体；建立内部 SKU 与平台 SKU 映射。                                            | 阶段 2；内部 SKU 编码规则。                             | 前端商品页可按店铺、状态、关键词分页查到真实数据。                  |
| 4. 订单与履约   | 首次回填订单，再用 Webhook + 定时补偿同步订单、订单项和履约状态；实现幂等去重。                                           | 阶段 2、3；订单状态流转和隐私字段规则。                 | 可查到真实订单和明细，重复事件不会产生重复订单。                    |
| 5. 前端切流     | 完善列表和详情接口、查询参数、权限与状态页；先按测试店铺或白名单账号灰度关闭 Mock。                                       | 阶段 3--4 的内部 API。                                  | `VITE_USE_MOCK=false` 时商品和订单页面可用，Mock 仍可用于离线开发。 |
| 6. 上线运维     | 配置任务监控、延迟/失败告警、数据对账、回放和发布回滚。                                                                   | 可观测性平台、值班人和处置流程。                        | 能定位某店铺某次同步的数据来源、失败原因和重试记录。                |

## 4. 每阶段具体任务、文件与数据

### 阶段 0：平台接入与业务口径确认

1. 确认首批国家/站点、店铺数量、是否为跨境店、订单同步时间范围和目标数据时效。
2. 逐项确认 TikTok Shop 实际批准的权限：商品读取、订单读取、履约/物流读取及 Webhook。
3. 明确业务口径：取消订单是否计销量、退款如何展示、金额展示币种和汇率来源。
4. 建立字段映射表：每个 ERP 字段必须标注 TikTok 源字段、转换规则、可空性、更新时间和负责人。

建议新增文件：

- `docs/tiktok-shop/connection-scope.md`：应用、区域、scope、回调 URL、责任人；不记录密钥。
- `docs/tiktok-shop/field-mapping.md`：平台字段到内部字段的映射。
- `docs/tiktok-shop/order-status-mapping.md`：平台状态到内部状态的映射。
- `docs/tiktok-shop/data-dictionary.md`：金额、时间、时区与隐私规则。

关键依赖：TikTok Shop 开放平台准入、商家授权、测试店铺、HTTPS 回调域名、KMS/Secret Manager。平台的具体 endpoint 和 scope 以当前开发者文档及已获批权限为准，不要按前端 Mock 猜测。

### 阶段 1：内部数据模型和 API 契约

后端先定义内部稳定模型。金额使用最小货币单位整数，例如 `amountMinor: 29900` 配合 `currency: "USD"`；所有时间使用 UTC ISO 8601，例如 `2026-08-10T10:20:00Z`。列表统一采用当前项目已约定的 `{ items, total, page, pageSize }`，页码从 1 开始。

建议后端目录（技术栈未定，按职责组织即可）：

```text
erp-api/
  src/modules/tiktok-shop/
    tiktok-client.*          # 签名、请求、限流与错误转换
    authorization.*          # 授权回调、令牌刷新与撤销
    webhook.*                # 验签、落库、异步投递
    sync/                    # 商品、订单同步任务
  src/modules/catalog/
  src/modules/orders/
  src/modules/shops/
  migrations/
  openapi/
```

建议前端新增/调整文件：

- `src/features/shops/**`：新增店铺连接管理模块。
- `src/features/products/types/product.types.ts`、`src/features/orders/types/order.types.ts`：替换展示型 Mock 类型为真实领域类型。
- `docs/backend-contract-confirmation.md`：补充店铺、商品、订单的确认项。
- `docs/product-api-pilot.md`：从单一商品试点扩展为商品和订单正式契约。

首批内部接口：

```text
GET  /shops                         # 当前租户已连接店铺
POST /shops/tiktok/authorize        # 创建授权跳转地址/状态
GET  /shops/tiktok/callback         # 后端接收 OAuth 回调
GET  /products?page=&pageSize=&shopId=&keyword=&status=
GET  /products/{id}
GET  /orders?page=&pageSize=&shopId=&status=&updatedFrom=&updatedTo=
GET  /orders/{id}
POST /sync-jobs                     # 管理员手动触发，需审计
GET  /sync-jobs/{id}
```

### 阶段 2：店铺连接、授权和安全基础

1. 后端生成 `state`，发起 TikTok Shop 授权；回调时校验 `state` 并交换令牌。
2. `access_token` 和 `refresh_token` 仅加密存入服务端；设置自动刷新和授权过期告警。
3. 为每一次平台请求记录 `shopId`、请求类型、平台 request id、耗时、结果和脱敏错误，不记录令牌或完整买家隐私数据。
4. Webhook 入口先做到：验签、快速返回、原始事件持久化、异步队列消费。不能在 Webhook HTTP 请求中直接完成全量同步。
5. 重试分两层：TikTok HTTP 请求最多 3 次尝试（首次 + 2 次重试，`0.5s` 起、`30s` 封顶）；商品/订单任务最多 5 次尝试，Webhook 任务最多 8 次尝试。任务使用 full jitter 指数退避 `random(0, min(30m, 30s * 2^(attempt-1)))`；30 分钟仅为本地退避上限，有效 `Retry-After` 至少等待平台指定时长，超过 24 小时则暂停并告警。
6. 自动重试仅覆盖 `429`、超时、网络中断和 `5xx`。确定性 `4xx` 直接失败；授权失效只允许刷新令牌一次，仍失败则告警。可重试错误耗尽次数后进入死信。
7. 默认每租户最多同时运行 2 个商品/订单同步任务和 4 个 Webhook 处理任务，同一店铺同一实体类型最多 1 个；Webhook 使用独立队列，避免被长时间全量同步阻塞。

新增核心表：

| 表                     | 关键字段                                                                                      | 用途                                             |
| ---------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `shops`                | `id, tenant_id, platform, platform_shop_id, region, name, status`                             | ERP 内部店铺身份。                               |
| `shop_connections`     | `shop_id, auth_status, access_token_ciphertext, refresh_token_ciphertext, expires_at, scopes` | 授权状态和加密令牌。                             |
| `webhook_events`       | `id, platform_event_id, shop_id, event_type, occurred_at, payload_json, status`               | 事件去重、回放、审计。                           |
| `sync_jobs`            | `id, shop_id, entity_type, mode, cursor, started_at, finished_at, status, error_summary`      | 同步进度、任务恢复游标和最近成功任务的增量起点。 |
| `raw_platform_records` | `id, shop_id, entity_type, external_id, payload_json, fetched_at, payload_hash`               | 原始数据追溯；按保留策略清理。                   |

唯一约束至少包括：`shops(tenant_id, platform, platform_shop_id)`、`webhook_events(platform_event_id)`；未知或缺失 event id 时使用“事件类型 + 外部对象 id + 发生时间 + payload hash”的幂等键。

商品、订单和 Webhook 业务处理共用可恢复任务状态机：`queued → running → succeeded`；临时错误进入 `retry_wait`，不可重试错误进入 `failed`，超过重试上限进入 `dead_letter`，人工取消进入 `cancelled`。Worker 领取任务时必须持有带期限的租约并持续心跳；租约过期后由调度器回收。商品/订单从任务级恢复游标续跑，Webhook 从已持久化原始事件重放。终态任务不可原地改写，人工重试创建关联原任务的新执行记录，以保留完整尝试和审计历史。

人工重试要求 `sync:trigger` 权限并填写原因，记录操作者、原任务 ID、错误摘要和恢复点。系统在授权、配置或数据错误未解除时应拒绝重复提交。任务进入 `retry_wait` 时写入 `next_retry_at` 并释放 Worker 租约，不允许占用 Worker 原地等待。

### 阶段 3：商品和 SKU 主数据

1. 首轮支持指定时间范围或全量同步：商品默认全量初始化，也允许按平台更新时间指定范围回补；首轮成功后再以平台返回的 cursor 做增量同步。
2. 游标按店铺和实体类型隔离。每页完成幂等 upsert 后记录任务恢复游标，整批成功后才提交下一轮增量游标；失败任务不能推进已提交游标。
3. 把“商品（SPU）”与“可售 SKU”分开，SKU 是订单项关联的连接键。
4. 用 `external_id` 保存 TikTok Shop 平台 ID，用内部 `id` 做 ERP 主键；禁止用名称匹配。
5. SKU 未映射时标为 `unmapped`，在设置/店铺管理页处理，不能自动猜测匹配。

建议表结构：

| 表                 | 关键字段                                                                                             | 依赖                           |
| ------------------ | ---------------------------------------------------------------------------------------------------- | ------------------------------ |
| `products`         | `id, tenant_id, title, status, category_id, primary_image_url, updated_at`                           | 可聚合多个平台商品。           |
| `product_variants` | `id, product_id, internal_sku, title, attributes_json, status`                                       | SKU 主数据。                   |
| `channel_products` | `id, shop_id, product_id, external_product_id, platform_status, external_updated_at`                 | 店铺商品映射。                 |
| `channel_skus`     | `id, channel_product_id, variant_id, external_sku_id, seller_sku, external_sku_code, mapping_status` | 平台 SKU 与内部 SKU 的桥接表。 |

前端修改点：

- 改造 `src/features/products/api/product.api.ts`：为真实 API 加入服务端分页列表和详情请求；`mockProductApi` 仅供显式 Mock 模式使用，真实请求失败不得自动回退 Mock，也不要在文件内长期保存演示数组。
- 改造 `src/features/products/queries/product.queries.ts`：查询键必须包含 `shopId/page/pageSize/keyword/status`。
- 改造 `src/features/products/types/product.types.ts`：增加 `shopId`、`externalProductId`、SKU 汇总、`syncedAt`；金额不使用格式化字符串。
- 补充 `src/features/products/queries/product.queries.test.tsx` 和 `tests/e2e/products.spec.ts`。

### 阶段 4：订单、订单项与履约同步

1. 首轮默认按明确时间窗口回填订单；确需全量时由管理员显式触发，避免默认无限回溯造成平台限流和不必要的隐私存储。
2. 指定时间范围/全量回填成功后才启用游标增量。订单游标按店铺独立保存，整批成功后提交，失败任务不能推进已提交游标。
3. Webhook 负责“尽快发现变化”，定时游标增量任务负责“补偿漏事件”；二者写入相同的幂等 upsert 服务。
4. 订单头、订单项、支付金额、收货信息和包裹/履约记录分别建模。地址和电话按最小化原则保存/脱敏，并控制可见权限。
5. 状态转换以映射表为准，保留 `externalStatus` 便于追踪新平台状态；状态不可倒退，除非平台事件版本/更新时间更新。

建议表结构：

| 表                | 关键字段                                                                                                                              | 依赖                       |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| `orders`          | `id, shop_id, external_order_id, order_number, status, external_status, currency, total_amount_minor, placed_at, platform_updated_at` | `shops`。                  |
| `order_lines`     | `id, order_id, channel_sku_id, external_line_id, quantity, unit_price_minor, discount_minor, line_total_minor`                        | `orders`、`channel_skus`。 |
| `fulfillments`    | `id, order_id, external_fulfillment_id, status, carrier, tracking_number, shipped_at, delivered_at`                                   | `orders`。                 |
| `order_addresses` | `order_id, recipient_name, phone_ciphertext, address_ciphertext, country_code`                                                        | `orders`；字段加密/脱敏。  |

前端修改点：

- `src/features/orders/types/order.types.ts`：将 `amount: string` 改为 `currency + totalAmountMinor`，增加 `shopId`、订单时间、履约状态和订单项摘要。
- `src/features/orders/api/order.api.ts`：从无参数 `getList()` 改为带 `OrderListParams` 的分页请求，并新增 `getDetail(id)`。
- `src/features/orders/queries/order.queries.ts`：查询 key 纳入筛选条件，增加详情 key 和同步后失效策略。
- `src/features/orders/pages/*`、`components/order-list.tsx`：增加店铺/状态/时间筛选，详情展示订单项与物流；处理 loading/error/empty。
- 新增 Hook、页面和 `tests/e2e/orders.spec.ts` 的成功、无权限、空结果和错误态测试。

### 后续阶段：库存模块（当前留白）

库存不属于本期范围：不设计库存接口、数据表、同步任务或前端功能。当前仅保留 `/warehouse` 导航入口，并显示“库存模块正在建设中”。后续需要单独确认库存权威来源（TikTok Shop、WMS 或 ERP 仓）后再创建专项计划。

### 阶段 5：前端切换真实 API

当前项目已经有良好的切换基础：`src/services/api-mode.ts` 的 `VITE_USE_MOCK`，以及 `src/services/http-client.ts` 的 token、错误规范化和契约版本请求头。切换按以下顺序执行：

1. 后端 staging 部署并配置 Vite 代理目标；创建 `.env.staging`（不提交任何密钥）。
2. 保持 `VITE_USE_MOCK=true` 开发演示不受阻，同时让测试环境/白名单用户设为 `false`。
3. 逐个模块关闭 Mock：商品 → 订单；`VITE_USE_MOCK=false` 时对应模块只调用 ERP API，失败时展示真实错误，不得静默回退 Mock。每个模块先验证列表、筛选、分页、详情、空数据、无权限和 API 失败；商品从详情返回后保留列表筛选与分页状态。`/warehouse` 保持为“库存模块正在建设中”占位页。
4. 所有店铺连接、手动同步、查看买家隐私信息等操作补充权限码，例如 `shops:manage`、`sync:trigger`、`orders:buyer-pii:view`。
5. 将 `src/features/settings/api/setting.api.ts` 从本地数组改为内部设置 API，首期用于同步频率和告警开关；库存预警阈值延后至库存模块启动时实现。

环境变量只保留公开配置：

```dotenv
VITE_USE_MOCK=false
VITE_API_BASE_URL=/api
VITE_API_CONTRACT_VERSION=v1
VITE_API_PROXY_TARGET=https://staging-api.example.com
```

TikTok Shop 的 app secret、Webhook 签名密钥、数据库密码和加密密钥只能配置在后端密钥管理服务/CI 的安全变量中，绝不能进入 `.env`、前端构建产物或 git。

### 阶段 6：数据质量、监控和上线

1. 为每家店铺监控：授权有效期、最近整批成功同步时间、待处理事件数、失败率、API 限流次数、同步延迟。最近成功时间按店铺和实体类型保存，仅在指定范围/全量或增量任务整批成功后更新。
2. 每日做抽样或全量对账：订单数、订单金额、SKU 数；差异生成任务，不直接覆盖人工修正。库存差异对账随库存模块启用后加入。
3. 将 `src/services/observability/` 的前端接口耗时与后端同步任务指标关联到 `shopId`/`syncJobId`（不得上传买家 PII）。
4. 发布采取灰度：测试店铺 → 单个生产店铺 → 全部店铺。保留上一个稳定前端产物及后端迁移回滚方案。
5. 制定故障操作：令牌失效、Webhook 验签失败、平台限流、数据滞后、字段新增/状态未知分别有负责人和处理时限。
6. 监控各状态任务数、队列等待时间、运行时长、租约回收次数、自动重试次数和死信数量；死信与长期 `running` 任务必须告警。
7. 任务同时记录有效处理耗时与排队到终态总历时，以及 `received_count/succeeded_count/failed_count`。成功数量只在页面事务提交后增加；最终失败数量与重试过程错误分开，避免重复计数。TikTok 每次 `429`（包括请求级重试）均增加平台限流计数。
8. 通用时序指标标签仅允许 `platform/entity_type/mode/status/error_class` 等有限枚举；`tenant_id/shop_id/sync_job_id` 放入受控业务统计、日志或 trace，不把游标、外部业务 ID 和买家 PII 作为标签。
9. 后端单元测试覆盖签名、token 加密、OAuth state、权限、商品/订单 normalizer 和幂等 upsert。必须包含签名篡改、密文篡改、state 过期/重放/跨租户、权限拒绝、未知平台字段、乱序事件、重复投递和事务回滚场景，并验证日志与响应不泄露密钥、token 或买家 PII。
10. API 测试覆盖登录、店铺、商品、订单、Webhook、统一错误码和租户隔离。使用两个租户验证列表、详情、同步任务和写操作；跨租户资源统一表现为 `404`。Webhook 验证签名失败不落库、合法事件持久化后快速返回、重复事件只入队一次，且任何错误响应都不泄露密钥、token、堆栈或买家 PII。
11. 集成测试采用双层门禁：每个 PR 使用独立受控 mock server 验证真实 HTTP 签名、分页游标、数据库、Redis、队列和 Worker；nightly/staging/release candidate 使用专用 TikTok 测试店铺做只读冒烟。两层复用授权、商品指定范围/全量与增量、订单时间窗口与增量、Webhook 及错误恢复断言。
12. mock server 必须可确定地产生 `429/Retry-After`、超时、连接中断、`5xx`、确定性 `4xx`、过期 token、畸形响应和分页中断，验证事务回滚、恢复游标、已提交游标、重试和死信。测试店铺使用受保护 secrets 和固定只读窗口，禁止连接生产店铺或修改平台数据；平台不可用可按基础设施失败重跑，但未通过不得晋级生产。

## 5. 首期最小可用版本（MVP）建议

为了尽快从假数据走到可用真实数据，建议 MVP 只覆盖“单区域、1--3 家 TikTok Shop 店铺、只读数据”：

1. 管理员完成店铺授权；
2. 每 15--30 分钟同步商品/SKU、订单，并接收订单变更 Webhook；
3. 商品、订单两个现有页面读取内部 API；库存页面保持占位；
4. 列表支持店铺、时间、状态和关键词筛选，订单支持详情；
5. 显示“最后同步时间”和失败状态；
6. 完成权限、审计、错误告警和最基本对账。

该版本不含反向写入平台、广告和财务结算，能把数据链路、模型和运维方式先跑稳，后续扩展成本最低。

## 6. 开工前必须确认的决策

1. 首发国家/站点和店铺数是多少？
2. 是只读取平台数据，还是还要向平台推送发货、价格？库存反向同步在库存模块重新立项时确认。
3. 库存模块重新排期时，库存的权威来源是 TikTok Shop、WMS，还是人工 ERP 仓？
4. 是否已有后端、数据库、队列、对象存储和密钥管理；若没有，需要先将它们列为阶段 1/2 的基础设施交付。
5. 订单及地址等个人信息的保留期限、可查看角色和脱敏规则是什么？
6. 业务要求的数据延迟是分钟级、小时级还是日级？这决定是否必须上线 Webhook、队列和高频补偿。

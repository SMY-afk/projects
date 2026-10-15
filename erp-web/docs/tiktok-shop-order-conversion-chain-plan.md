# TikTok Shop 订单成交链路识别实施计划

> 状态：一期实现与自动化回归已完成，保留为分类规则和回填治理基线（更新于 2026-08-19）。历史回填继续使用明确时间窗、先执行最新 30 天并对账，较早窗口需单独批准。

## 1. 目标、范围与硬性原则

### 1.1 目标

ERP 必须为每一笔已同步的 TikTok Shop 订单产出一条可查询、可筛选、可追溯的成交链路。例如：

- `自然流 > 达人 > 视频订单`
- `广告流 > 自营 > 直播订单`
- `自然流 > 商城 > 搜索或推荐`
- `样品订单`
- `买样返款订单`

每笔订单都必须有一条归类记录，但这不等于每笔订单都能被平台数据确认。无法由平台证据确认时，链路必须为 `unknown`，并保存原因；严禁因为没有广告匹配就自动归为自然流。

### 1.2 本期范围

- 从 TikTok Shop 订单详情、订单项及可用的联盟/达人订单数据提取订单级成交来源；
- 为正常订单生成“流量来源 + 经营主体 + 成交入口”的三级链路；
- 识别样品订单、买样返款订单等特殊订单；
- 为历史已同步订单做限定时间窗口的详情回查和补分类；
- 在 ERP 订单列表和详情中展示、筛选成交链路及其判定状态。

### 1.3 不在本期范围

- 用 TikTok Ads 日报按活动、商品、日期估算后，伪造为单笔订单的广告来源；
- 退款、结算、利润或广告 ROI 的财务口径；
- 手工覆盖和多触点归因。若一期后确有运营需求，再单独设计审计流程。

### 1.4 判定原则

1. 特殊订单优先：`sample`、`purchase_sample_rebate` 覆盖普通流量链路展示。
2. 平台直接字段优先：订单详情或订单级联盟/广告转化标识是唯一可确认依据。
3. 显式规则其次：仅可依据已确认的平台字段组合，不得依据金额、商品名称或“未命中广告”猜测。
4. `unknown` 是合法且必须保留的结果；它与“自然流”不同。
5. 不在浏览器、日志或业务 API 返回完整平台原始响应、Token、买家 PII。

## 2. 目标分类模型

截图中的树形类型不应存成大量互斥枚举，而应拆为以下维度，并在页面组合显示。

| 维度                    | 内部值                                                                                                     | 说明                                             |
| ----------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `traffic_source`        | `organic` / `paid_ads` / `unknown`                                                                         | 自然流、广告流或无法确认。                       |
| `operator_subject`      | `creator` / `self_operated` / `mall` / `unknown`                                                           | 达人、自营、商城。                               |
| `entry_point`           | `video` / `live` / `offsite` / `showcase` / `affiliate_product_page` / `search_recommendation` / `unknown` | 视频、直播、站外、橱窗、联盟商品页、搜索或推荐。 |
| `special_order_type`    | `normal` / `sample` / `purchase_sample_rebate` / `unknown`                                                 | 样品和买样返款等特殊订单。                       |
| `classification_status` | `confirmed` / `derived` / `unknown`                                                                        | 平台直接确认、已批准规则推导、缺少证据。         |

`chain_code` 是稳定的机器可读值：仅当正常订单的三段维度全部确认时生成 `<traffic_source>.<operator_subject>.<entry_point>`；特殊订单为 `sample` 或 `purchase_sample_rebate`；证据不足或冲突时为 `unknown`。页面标签由上述字段动态生成，避免把显示文案当作数据主键。

### 2.1 固化枚举与显示契约

以下值是唯一允许写入内部归因 DTO、数据库和 API 响应的枚举；平台原始值必须先经过白名单映射，未识别值一律转为 `unknown`，不得原样扩展枚举。

| 字段                    | 固定枚举                                                                                             | 允许生成的 `chain_code` / 显示                                                                                                           |
| ----------------------- | ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `traffic_source`        | `organic`、`paid_ads`、`unknown`                                                                     | 正常链路第一段；`unknown` 不得降级为 `organic`。                                                                                         |
| `operator_subject`      | `creator`、`self_operated`、`mall`、`unknown`                                                        | 正常链路第二段；`unknown` 不得根据店铺或商品归为 `self_operated`。                                                                       |
| `entry_point`           | `video`、`live`、`offsite`、`showcase`、`affiliate_product_page`、`search_recommendation`、`unknown` | 正常链路第三段；`unknown` 不得根据内容报表或商品类型猜测。                                                                               |
| `special_order_type`    | `normal`、`sample`、`purchase_sample_rebate`、`unknown`                                              | `sample` 生成 `sample`；`purchase_sample_rebate` 生成 `purchase_sample_rebate`；正常订单只有三段确认且该值为 `normal` 时才生成三段链路。 |
| `classification_status` | `confirmed`、`derived`、`unknown`                                                                    | 必要维度为 `unknown` 或存在未解决冲突时为 `unknown`；不支持字段不算 `derived`。                                                          |

### 2.2 特殊订单优先级

1. 先判断特殊订单，再判断正常三段链路；特殊订单显示覆盖正常链路，但已取得的正常维度仍保存在证据中。
2. 特殊类型按“具体优先于泛化”处理：明确的 `purchase_sample_rebate` 高于泛化的 `sample` 标记；明确的 `sample` 高于明确的 `normal`；没有正向证据时为 `unknown`。
3. `is_sample_order=false` 不能单独证明 `normal`。已实测 Seller Center 的“买返样品”样本曾返回 `false`，该布尔值只能作为候选/证据字段，不能覆盖人工标签或自动生成特殊类型。
4. Seller Center 标签只作为验收样本；除非取得可按订单 ID 关联的订单级接口，否则不得作为生产批量分类信号。

### 2.3 `unknown` 策略

- `unknown` 是合法且可持久化的结果，不是错误状态；枚举字段不得写 `null`、空字符串或平台未知原值替代它。
- `unknown` 按维度保存：已确认维度不被抹掉，但只要正常链路任一必要维度为 `unknown`，或特殊类型未确认，`chain_code` 主值就是 `unknown`，页面显示“未知”。
- 当前详情接口未返回的自然/广告、达人/自营/商城、视频/直播/站外/橱窗/联盟商品页/搜索推荐字段，统一为 `unknown`，原因写入证据：`missing_platform_field` 或 `unsupported_endpoint`。
- 出现更强订单级证据时允许 `unknown -> derived/confirmed`；较弱、较旧或仅汇总级数据不得覆盖强结论。

### 2.4 冲突处理顺序

按以下顺序处理，任何一步无法消除冲突都停止判定并输出 `unknown`：

1. **过滤范围**：只接受订单级、可按 `platform_order_id` 精确关联的证据；GMV 汇总、日报、商品维度或金额相似度不得进入分类器。
2. **来源强度**：同一字段优先级为“订单详情直接字段” > “已验证的联盟/Ads 订单级关联 ID” > “批准的规则推导” > “Seller Center 汇总或人工标签（仅验收）”。低优先级信号不得覆盖高优先级信号。
3. **特殊覆盖**：按 2.2 解析特殊类型；确认的特殊类型覆盖正常链路显示，特殊类型冲突则不生成正常链路。
4. **同源新旧**：同一来源多个版本使用较新的 `source_updated_at` / 平台 `update_time`；旧响应不得回写新结论。相同时间戳但摘要不同，视为冲突。
5. **同优先级冲突**：两个不同枚举值处于同一强度且无法按更新时间裁决时，该维度置 `unknown`，证据原因记为 `conflicting_signals`；不得按代码顺序、金额或概率任选一个。
6. **最终输出**：正常链路只有在 `traffic_source`、`operator_subject`、`entry_point` 和 `special_order_type=normal` 全部确认时才生成三段 `chain_code`；否则 `chain_code=unknown`、`classification_status=unknown`。特殊类型确认时只输出其特殊 `chain_code`。

`classification_method` 保持现有来源值（`shop_order_detail`、`affiliate_order`、`ads_order_link`、`rule`）；发生未解决冲突时在 `evidence_json.reason` 写入 `conflicting_signals`，不伪造获胜来源。

### 2.5 `attribution` 返回对象与列表筛选参数

#### 详情对象

`GET /api/orders/{orderId}` 在现有订单字段之外增加 `attribution`；无归因记录时仍返回对象，所有无法确认的维度使用 `unknown`，不返回 `null` 代替枚举值。

```json
{
  "trafficSource": "unknown",
  "operatorSubject": "unknown",
  "entryPoint": "unknown",
  "specialOrderType": "unknown",
  "chainCode": "unknown",
  "classificationStatus": "unknown",
  "classificationMethod": "shop_order_detail",
  "sourceUpdatedAt": "2026-08-13T02:45:49Z",
  "evidenceSummary": [
    {
      "source": "shop_order_detail",
      "fieldPath": "data.orders[].is_sample_order",
      "value": "false",
      "strength": "medium",
      "reason": "missing_platform_field"
    }
  ]
}
```

字段契约：

| 字段                   | 类型/枚举                                                                                                  | 说明                                                                                                                            |
| ---------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `trafficSource`        | `organic` / `paid_ads` / `unknown`                                                                         | 正常链路的流量来源；当前详情接口未提供时为 `unknown`。                                                                          |
| `operatorSubject`      | `creator` / `self_operated` / `mall` / `unknown`                                                           | 正常链路的经营主体。                                                                                                            |
| `entryPoint`           | `video` / `live` / `offsite` / `showcase` / `affiliate_product_page` / `search_recommendation` / `unknown` | 正常链路的成交入口。                                                                                                            |
| `specialOrderType`     | `normal` / `sample` / `purchase_sample_rebate` / `unknown`                                                 | 特殊订单优先于普通三段链路。                                                                                                    |
| `chainCode`            | 字符串                                                                                                     | 三段链路编码、`sample`、`purchase_sample_rebate` 或 `unknown`。                                                                 |
| `classificationStatus` | `confirmed` / `derived` / `unknown`                                                                        | 判定强度状态；缺字段和未解决冲突必须为 `unknown`。                                                                              |
| `classificationMethod` | `shop_order_detail` / `affiliate_order` / `ads_order_link` / `rule`                                        | 最终采用的证据来源；无强证据但仍需记录时使用 `shop_order_detail`，不伪造 Ads/联盟来源。                                         |
| `sourceUpdatedAt`      | UTC ISO 8601 或 `null`                                                                                     | 最终证据对应的平台/外部来源更新时间；没有来源时间时为 `null`。                                                                  |
| `evidenceSummary`      | 数组                                                                                                       | 脱敏证据摘要；只允许字段路径、枚举值、判定强度、原因和不可逆外部 ID 指纹，不得返回原始 payload、Token、买家 PII 或完整广告 ID。 |

`evidenceSummary[].strength` 固定为 `strong` / `medium` / `auxiliary` / `unsupported`；`reason` 固定为 `missing_platform_field`、`unsupported_endpoint`、`platform_no_order_level_evidence`、`conflicting_signals`、`stale_signal`、`validated_seller_center_label` 之一。`platform_no_order_level_evidence` 表示外部 Ads/GMV Max/联盟响应存在，但没有可用于精确关联当前订单的订单 ID 或订单项 ID；此时链路必须保持 `unknown`。详情响应同时返回面向用户的 `reasonLabel=平台无订单级证据`。列表响应不返回 `evidenceSummary`，避免扩大响应和泄露证据细节。

#### 列表筛选参数

`GET /api/orders` 在既有参数基础上增加以下单值筛选；所有筛选作用于订单当前唯一有效的归因记录，而不是历史版本：

| 参数                   | 类型/允许值                                                                                                | 行为                                                               |
| ---------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `trafficSource`        | `organic` / `paid_ads` / `unknown`                                                                         | 精确匹配 `traffic_source`；传 `unknown` 可筛出尚无来源证据的订单。 |
| `operatorSubject`      | `creator` / `self_operated` / `mall` / `unknown`                                                           | 精确匹配 `operator_subject`。                                      |
| `entryPoint`           | `video` / `live` / `offsite` / `showcase` / `affiliate_product_page` / `search_recommendation` / `unknown` | 精确匹配 `entry_point`。                                           |
| `specialOrderType`     | `normal` / `sample` / `purchase_sample_rebate` / `unknown`                                                 | 精确匹配特殊订单类型；不依据金额或 `is_sample_order` 猜测。        |
| `classificationStatus` | `confirmed` / `derived` / `unknown`                                                                        | 精确匹配判定状态。                                                 |
| `chainCode`            | `organic                                                                                                   | paid_ads`.`creator                                                 | self_operated | mall`.`video | live | offsite | showcase | affiliate_product_page | search_recommendation`，或 `sample`/`purchase_sample_rebate`/`unknown` | 精确匹配最终显示链路；不接受任意字符串；正常三段编码不允许包含 `unknown`。 |

既有 `page`、`pageSize`、`shopId`、`keyword`、`status`、`updatedFrom`、`updatedTo` 参数语义保持不变：页码从 1 开始，`pageSize` 最大 100，时间范围为 `[updatedFrom, updatedTo)`。未传归因参数表示不筛选；空字符串按未传处理；未知枚举或组合值返回 `422 VALIDATION_ERROR`，不得静默转为 `unknown`。筛选条件必须进入服务端 SQL 和前端 Query Key，不能先拉全量订单再在浏览器过滤。

## 3. 数据流与关联边界

```text
TikTok Shop 订单列表/详情
        -> 规范化 TikTokOrder DTO（仅允许字段）
        -> orders / order_lines（现有订单事实）
        -> OrderChainClassifier（纯规则）
        -> order_attributions（一单一条当前成交链路）
        -> /api/orders 列表、详情与筛选

TikTok Shop 联盟/达人订单数据（仅在订单详情字段不足时）
        -> 仅按平台订单 ID 或订单项 ID 精确关联
        -> OrderChainClassifier

TikTok Ads / GMV Max（条件性后续来源）
        -> 仅在返回订单 ID 或可验证的订单级转化 ID 时关联
        -> 不具备订单级标识时只能做汇总报表，不参与本期单订单判定
```

## 4. 依赖与前置决策

### 4.1 外部依赖

| 依赖                          | 用途                               | 负责人/确认物                          |
| ----------------------------- | ---------------------------------- | -------------------------------------- |
| TikTok Shop 订单读取权限      | 拉取订单详情及其来源字段。         | 已授权店铺和当前批准的 scope。         |
| Seller Center 标注样本        | 建立“已知类型订单”的真值集。       | 每个可见类型至少 1 笔脱敏订单 ID。     |
| TikTok Shop 联盟/达人能力     | 订单详情不含达人标识时的补充来源。 | 接口、scope、订单 ID 关联能力。        |
| TikTok Ads / GMV Max 能力     | 仅用于验证订单级广告转化标识。     | 广告账户授权和可返回订单级 ID 的证明。 |
| PostgreSQL、Redis、ARQ Worker | 迁移、幂等存储、历史补分类任务。   | 现有 ERP 运行基础设施。                |

### 4.2 需要业务确认的决策

1. 样品/买样返款始终覆盖普通成交链路展示；但 `is_sample_order` 单独不足以确认样品细分类。
2. 平台信号按第 2.4 节固定顺序处理：订单级直接字段优先，未解决冲突落为 `unknown`；不得用金额、商品或汇总报表裁决。
3. `unknown` 是合法持久化结果；当前订单详情不支持的来源维度统一显示“未知”，不得默认归为自然流。
4. Seller Center 标签仅作为脱敏验收样本；自动分类必须依赖可按订单 ID 关联的订单级字段或凭证。
5. 历史补分类的起止日期仍需业务确认；实现前可先以最近 30 天试运行，但不能视为平台详情保留期限。

数据库 schema、公共 API 和权限码会改变，须在第 3 步评审通过后再实施。

## 5. 数据结构设计

### 5.1 新表：`order_attributions`

一笔订单只保留一条“当前有效”的成交链路；重新同步时按平台更新时间和来源哈希幂等更新。

| 字段                    | 类型/约束          | 说明                                                               |
| ----------------------- | ------------------ | ------------------------------------------------------------------ |
| `id`                    | UUID，主键         | 内部主键。                                                         |
| `tenant_id`             | UUID，非空         | 租户隔离字段。                                                     |
| `order_id`              | UUID，非空         | ERP 订单 ID。                                                      |
| `traffic_source`        | varchar(32)，非空  | `organic`、`paid_ads`、`unknown`。                                 |
| `operator_subject`      | varchar(32)，非空  | `creator`、`self_operated`、`mall`、`unknown`。                    |
| `entry_point`           | varchar(48)，非空  | 视频、直播等入口或 `unknown`。                                     |
| `special_order_type`    | varchar(48)，非空  | 正常、样品、买样返款或 `unknown`。                                 |
| `chain_code`            | varchar(160)，非空 | 稳定的三级链路编码。                                               |
| `classification_status` | varchar(24)，非空  | `confirmed`、`derived`、`unknown`。                                |
| `classification_method` | varchar(32)，非空  | `shop_order_detail`、`affiliate_order`、`ads_order_link`、`rule`。 |
| `platform_source_code`  | varchar(128)，可空 | 平台返回的允许保存的来源码。                                       |
| `creator_external_id`   | varchar(128)，可空 | 仅在平台明确返回时保存。                                           |
| `campaign_external_id`  | varchar(128)，可空 | 仅在订单级广告标识可验证时保存。                                   |
| `evidence_json`         | JSONB，可空        | 仅保留字段名、枚举值、关联 ID 和规则版本；不是原始响应。           |
| `source_updated_at`     | timestamptz，可空  | 平台来源数据更新时间。                                             |
| `source_hash`           | varchar(64)，非空  | 允许字段的哈希，用于幂等更新。                                     |
| `classified_at`         | timestamptz，非空  | 当前判定完成时间。                                                 |

约束与索引：

- `UNIQUE (tenant_id, order_id)`，约束名建议为 `uq_order_attributions_tenant_order`；
- 复合外键 `(order_id, tenant_id) -> orders(id, tenant_id)`，租户边界与现有订单模型一致；
- 索引：`(tenant_id, chain_code)`、`(tenant_id, classification_status)`、`order_id`；
- 不存完整原始 payload、Token、买家姓名、电话、地址或广告凭据。

### 5.2 后端 DTO 与内部类型

在字段核验完成前，TikTok 实际字段名称不写死。实现后应新增以下内部类型：

```text
TikTokOrderAttributionSignal
  is_sample_order?: bool
  source_updated_at?: datetime

OrderAttributionDecision
  traffic_source: str
  operator_subject: str
  entry_point: str
  special_order_type: str
  chain_code: str
  classification_status: str
  classification_method: str
  evidence: dict[str, str]
```

## 6. 分步执行计划

### 步骤 0：建立真值样本与平台字段映射

**要做什么**

1. 从 Seller Center 各找一笔已知类型订单：自然/广告、达人/自营/商城、视频/直播/站外/橱窗/联盟商品页/搜索推荐、样品、买样返款。
2. 以脱敏方式调用订单详情，比较 Seller Center 标签与 API 返回字段。
3. 建立“平台字段 -> 内部字段 -> 显示链路 -> 判定强度”的映射表；未返回的字段明确标为“不支持”。
4. 核验同一订单更新后来源字段是否会变化，以及历史订单详情可回查的时间范围。

**涉及文件**

- 新增 `erp-web/docs/tiktok-shop-order-conversion-chain-field-mapping.md`
- 参考 `erp-api/src/erp_api/services/tiktok_order_schemas.py`
- 参考 `erp-api/src/erp_api/services/tiktok_order_client.py`

**依赖与数据结构**

- 已授权的真实 TikTok Shop 店铺；
- 脱敏后的真值订单 ID 列表；
- 本步骤只产出文档和测试 fixture，不将原始响应写入仓库或日志。

**完成标准**

- 每一个截图类型均标明：可直接识别、需补充联盟数据、需订单级 Ads 标识，或当前平台不支持；
- 字段名、枚举值和时间语义经真实响应验证，不按 Mock 或猜测实现。

### 步骤 1：确认归类口径并评审契约

**要做什么**

1. 固化第 2 节分类枚举、特殊订单优先级、`unknown` 策略和冲突处理顺序。
2. 定义订单详情中返回的 `attribution` 对象和列表筛选参数。
3. 评审数据库迁移、权限和历史回补范围；取得 schema/API 修改确认后再编码。

**涉及文件**

- 本文档
- 修改 `erp-web/docs/order-api-contract.md`
- 修改 `erp-web/docs/api-v1-contract.md`

**依赖与数据结构**

- 步骤 0 的字段映射；
- `OrderAttributionDecision` 数据结构；
- 现有内部响应保持 `{ items, total, page, pageSize }` 分页和 `amountMinor + currency` 约定。

**完成标准**

- 归类规则有唯一版本；
- API 只做加法字段扩展，不破坏现有订单列表和详情消费者；
- schema/API/权限变更获得确认。

### 步骤 2：建立领域模型和数据库迁移

**要做什么**

1. 新增 `OrderAttribution` SQLAlchemy 模型及其与 `Order` 的一对一关系。
2. 新建 Alembic migration，创建 `order_attributions`、复合外键、唯一约束和索引。
3. 在模型注册和 metadata 测试中加入新表；精确核验约束名和列顺序。

**涉及文件**

- 新增 `erp-api/src/erp_api/models/order_attribution.py`
- 修改 `erp-api/src/erp_api/models/order.py`
- 修改 `erp-api/src/erp_api/models/__init__.py`
- 新增 `erp-api/migrations/versions/<revision>_create_order_attributions.py`
- 修改/新增 `erp-api/tests/test_models.py`、`erp-api/tests/test_order_attribution_model.py`

**依赖与数据结构**

- 步骤 1 评审通过；
- PostgreSQL JSONB 和现有 `TenantScoped`、复合外键模式；
- 使用第 5.1 节表定义，不新增广告账户或广告日报表。

**完成标准**

- `alembic check`、升级/降级/再升级通过；
- 数据库元数据中存在精确的 `uq_order_attributions_tenant_order` 和复合外键；
- 跨租户订单不能创建或读取归因记录。

### 步骤 3：实现平台信号解析与纯归类器

**要做什么**

1. 在 `TikTokOrder` 中增加 `attribution_signal`，只容纳步骤 0 确认的字段。
2. 扩展订单详情与分页响应解析；字段缺失必须变为“无信号”，不能抛弃整笔订单。
3. 新建无副作用的 `OrderChainClassifier`：输入平台信号，输出 `OrderAttributionDecision`。
4. 为每条截图链路、冲突、缺失字段和未知枚举编写 fixture 测试。

**涉及文件**

- 修改 `erp-api/src/erp_api/services/tiktok_order_schemas.py`
- 必要时修改 `erp-api/src/erp_api/services/tiktok_order_client.py`
- 新增 `erp-api/src/erp_api/services/order_chain_classifier.py`
- 新增/修改 `erp-api/tests/test_order_chain_classifier.py`
- 修改 `erp-api/tests/test_tiktok_order_schemas.py`
- 新增脱敏 fixture：`erp-api/tests/fixtures/tiktok_order_attribution/*.json`

**依赖与数据结构**

- 步骤 0 的已验证字段映射；
- `TikTokOrderAttributionSignal`、`OrderAttributionDecision`；
- 不允许 fixture 含订单真实姓名、地址、电话、Token 或完整平台响应。

**完成标准**

- 每个已支持的成交链路都有通过的解析和归类测试；
- 未知/缺失字段只会产出 `unknown`，不会让同步失败；
- 分类规则可脱离数据库独立测试。

### 步骤 4：接入订单同步的幂等写入

**要做什么**

1. 新增 `OrderAttributionRepository`，在同一租户会话中 upsert 成交链路。
2. 在订单同步写入订单头、订单项后写入对应归因；按 `source_updated_at + source_hash` 避免旧响应覆盖新结论。
3. 将最新归因结论作为订单详情的关系数据加载，不修改订单金额、状态、PII 处理逻辑。
4. 若分页订单不含足够来源字段，按已验证能力补调用订单详情，不在列表接口中做 N+1 实时查询。

**涉及文件**

- 新增 `erp-api/src/erp_api/services/order_attribution_repository.py`
- 修改 `erp-api/src/erp_api/services/order_sync_repository.py`
- 修改 `erp-api/src/erp_api/services/order_sync_service.py`
- 必要时修改 `erp-api/src/erp_api/main.py`
- 新增 `erp-api/tests/test_order_attribution_repository.py`
- 修改 `erp-api/tests/test_order_sync_service.py`

**依赖与数据结构**

- 步骤 2 的数据库表、步骤 3 的归类器；
- 现有订单同步的按页提交、恢复游标和整批成功后提交增量游标规则；
- 新增写入不能改变 `orders`、`order_lines` 的现有唯一性和更新条件。

**完成标准**

- 同一订单重复同步不产生重复归因行；
- 更新后的平台来源能更新归因，旧来源不能回滚新结论；
- 订单同步失败时，订单与归因保持同一页事务一致性。

### 步骤 5：历史订单补分类

**要做什么**

1. 复用现有订单 `backfill` 同步入口，以明确的 `updatedFrom`、`updatedTo` 重拉订单详情并触发归类。
2. 首次仅运行最近 30 天，完成对账后再按审批的更早窗口分批回补。
3. 记录每批总订单数、`confirmed`/`derived`/`unknown` 数量、平台不支持字段数和失败原因。
4. 任务不得因单笔缺失来源字段失败；未知类型必须成功落库。

**涉及文件**

- 修改 `erp-api/src/erp_api/workers/order_jobs.py`
- 修改 `erp-api/src/erp_api/routers/orders.py`
- 修改 `erp-api/src/erp_api/core/config.py`（如需配置最大回补窗口）
- 修改 `erp-api/tests/test_order_sync_service.py`
- 新增 `erp-api/tests/test_order_attribution_backfill.py`

**依赖与数据结构**

- 步骤 4 已上线到测试环境；
- Redis/ARQ 和现有 `order_sync_runs`、`order_sync_cursors`；
- 历史订单详情 API 的允许时间范围和速率限制。

**完成标准**

- 一次回补可恢复、可重试、可观察，且不推进失败批次的已提交游标；
- 真值样本与 Seller Center 标记一致；
- 回补不会改变订单数量、金额、状态或 PII 保留策略。

### 步骤 6：条件性补充联盟与 Ads/GMV Max 订单级证据

**要做什么**

1. 若步骤 0 证明订单详情缺少达人字段，接入 TikTok Shop 联盟/达人订单数据，并仅以订单 ID 或订单项 ID 精确关联。
2. 若步骤 0 证明广告流无法从 Shop 订单判断，再核验 TikTok Ads/GMV Max 是否提供订单 ID 或可验证订单级转化 ID。
3. 仅在能够精确关联时，把联盟或广告证据交给归类器；Ads 日报、活动日报、商品日报只能用于汇总报表，禁止写入单订单链路。
4. 如果外部数据仍无订单级关联键，保持 `unknown`，并把“平台无订单级证据”展示为原因。

**涉及文件**

- 条件新增 `erp-api/src/erp_api/services/tiktok_affiliate_order_client.py`
- 条件新增 `erp-api/src/erp_api/services/tiktok_ads_conversion_client.py`
- 条件新增 `erp-api/src/erp_api/models/order_conversion_link.py`
- 条件新增对应 migration、repository、worker 与 tests
- 修改 `erp-api/src/erp_api/services/order_chain_classifier.py`

**依赖与数据结构**

- TikTok 额外 scope、独立授权和订单级关联 ID；
- `order_conversion_links` 仅保存 `tenant_id`、`order_id`、`source_system`、`external_conversion_id`、`evidence_hash`、`observed_at`；
- 不共享 TikTok Shop OAuth Token 和 Ads Token，不保存广告凭据到订单表。

**完成标准**

- 联盟/广告证据缺失不会影响 Shop 订单同步；
- 每一个 `paid_ads` 或 `creator` 的补充判定都能回查到精确订单关联键；
- 未满足订单级关联条件的 Ads 数据不能改变任何单笔订单类型。

### 步骤 7：扩展内部 API 与权限

**要做什么**

1. 在订单列表响应中增加简要 `attribution` 字段；在订单详情中增加完整链路、状态、方法和脱敏证据摘要。
2. 新增列表筛选：`trafficSource`、`operatorSubject`、`entryPoint`、`specialOrderType`、`classificationStatus`。
3. 订单列表查询使用 SQL 筛选和分页，不在前端过滤全量订单。
4. 延续 `orders:view` 读取权限；如后续加入人工修正，再单独评审 `orders:attribution:manage`，本期不新增写接口。

**涉及文件**

- 修改 `erp-api/src/erp_api/routers/orders.py`
- 修改 `erp-api/src/erp_api/services/order_repository.py`
- 修改 `erp-api/tests/test_order_routes.py`（若现有路由测试按模块命名不同则新增对应文件）
- 修改 `erp-web/docs/order-api-contract.md`
- 修改 `erp-web/docs/api-v1-contract.md`

**依赖与数据结构**

- 步骤 2 的模型和步骤 4 的数据；
- `OrderAttributionResponse`、`OrderListParams` 的加法字段；
- 现有订单 API 版本、鉴权和跨租户 404 语义。

**完成标准**

- 普通订单查看权限可读取归因但不能读取额外 PII；
- 每个筛选条件均进入数据库查询和前端 Query Key；
- 旧客户端未传新增参数时行为保持不变。

### 步骤 8：订单页面展示与筛选

**要做什么**

1. 订单列表增加“成交链路”和“判定状态”列，支持按截图中的一级、二级、三级类型筛选。
2. 订单详情新增“成交链路”卡片：显示完整路径、确认/推导/未知状态、判定时间和安全的证据摘要。
3. `unknown` 使用明确文案“未识别：订单详情未返回来源字段”，不得显示为自然流。
4. 当前 `/ads` 占位页不在本期替换；本期入口只在订单模块，避免前端先做没有可靠数据的广告看板。

**涉及文件**

- 修改 `erp-web/src/features/orders/types/order.types.ts`
- 修改 `erp-web/src/features/orders/api/order.api.ts`
- 修改 `erp-web/src/features/orders/queries/order.queries.ts`
- 修改 `erp-web/src/features/orders/pages/order-list-page.tsx`
- 修改 `erp-web/src/features/orders/pages/order-detail-page.tsx`
- 修改 `erp-web/src/features/orders/components/order-list.tsx`
- 新增 `erp-web/src/features/orders/components/order-attribution-card.tsx`
- 新增/修改对应 CSS 与 `*.test.tsx`
- 修改 `erp-web/tests/e2e/orders.spec.ts`

**依赖与数据结构**

- 步骤 7 的真实 API；
- React Query Key 必须含全部新增筛选条件；
- 继续使用项目现有权限守卫和错误页，不对 API 失败静默回退到 Mock。

**完成标准**

- 列表、详情、空态、无权限和服务端错误态均正确；
- 任一组合筛选刷新后仍保留查询条件；
- 展示文案与 `chain_code` 映射集中维护并有单元测试。

### 步骤 9：验证、灰度与上线

**要做什么**

1. 执行模型、迁移、解析、归类器、仓储、路由、前端 Query、E2E 回归测试。
2. 在单店铺灰度，将真值样本逐笔与 Seller Center 对比；记录不一致原因，不以人工改库修正。
3. 跑最近 30 天回补，审查 `confirmed`、`derived`、`unknown` 覆盖率和未知原因分布。
4. 发布后监控同步时长、失败率、来源字段缺失率、分类覆盖率和分类变更数；日志只含订单内部 ID、店铺 ID、请求 ID 和错误码。

**涉及文件**

- 修改/新增 `erp-api/tests/test_models.py`
- 修改/新增 `erp-api/tests/test_tiktok_order_schemas.py`
- 修改/新增 `erp-api/tests/test_order_chain_classifier.py`
- 修改/新增 `erp-api/tests/test_order_attribution_repository.py`
- 修改/新增 `erp-api/tests/test_order_sync_service.py`
- 修改/新增 `erp-api/tests/test_order_routes.py`
- 修改 `erp-web/src/features/orders/**/*.test.ts*`
- 修改 `erp-web/tests/e2e/orders.spec.ts`

**依赖与数据结构**

- 测试数据库、现有 `.venv`、前端依赖、单店铺灰度授权；
- 使用脱敏 fixture 和模拟响应，真实订单仅用于受控验收；
- 不依赖 Ads 日报作为订单级测试数据。

**完成标准**

- 迁移、后端回归、前端 lint/type/test/build 和 E2E 全部通过；
- 灰度店铺中，每笔已同步订单均有一条归因记录，`unknown` 有明确原因；
- 真值样本的已支持类型准确率为 100%，且不会产生跨租户数据、PII 泄露或订单金额变化。

## 7. 推荐实施顺序与里程碑

| 里程碑           | 包含步骤 | 可交付结果                                                   |
| ---------------- | -------- | ------------------------------------------------------------ |
| M0：可实施契约   | 0-1      | 经真实响应验证的字段映射、分类口径、批准的 schema/API 变更。 |
| M1：新订单可识别 | 2-4      | 新同步订单自动写入可追溯成交链路。                           |
| M2：历史订单补齐 | 5        | 指定时间窗口的历史订单完成补分类与对账。                     |
| M3：运营可用     | 7-9      | 订单页筛选和详情解释上线，单店铺灰度验证完成。               |
| 条件扩展         | 6        | 仅在拿到订单级关联键后补充联盟或 Ads/GMV Max 证据。          |

## 8. 最终验收清单

- [ ] 每笔订单都有且仅有一条当前 `order_attributions` 记录。
- [ ] 正常订单能展示“流量来源 > 经营主体 > 成交入口”；特殊订单展示特殊类型。
- [ ] 没有平台证据的订单展示 `unknown` 和原因，绝不默认归为自然流。
- [ ] 每个 `confirmed` 或 `derived` 结论可追溯到允许保存的平台字段和规则版本。
- [ ] 重复同步、重试、Webhook 与定时同步不会产生重复归因或旧数据回写。
- [ ] 历史回补不改变现有订单数量、金额、状态、SKU 关联或 PII 策略。
- [ ] API、页面、权限、迁移和回归验证全部通过。

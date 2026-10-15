# 联盟中心 Excel 优先接入与 API 转换计划

## 1. 目标与执行顺序

统一数据流如下：

```text
Excel parser ─┐
              ├→ AffiliateCreatorMetric → PostgreSQL → ERP 联盟中心
API parser ───┘

第二资源：AffiliateVideoMetric（所有视频）
```

实施顺序固定为：

1. Excel 达人报表导入 ERP；
2. 监听联盟中心请求，逆向达人接口并接入同一领域模型；
3. 条件成熟时将来源替换为官方 API；
4. 最后接入“所有视频”，复用已有视频内容和表现快照能力。

资源和查询契约已经冻结：

- `creators`（达人）与 `videos`（所有视频）是两个独立资源，禁止将视频作为达人报表的子字段；
- 两个资源共用且仅使用 `shopId + windowStart + windowEnd + shopTimezone + currency + filters` 六个查询维度；
- `shopId` 是单个 ERP 店铺 ID。“跨境4店”只是当前有效店铺的范围标签，不表示四个店；
- `windowStart`、`windowEnd` 是店铺本地日期且首尾均包含，调用上游 API 时转换为 DST 安全的 UTC 半开区间；
- 查询指纹由 `resource + 六个查询维度` 的规范 JSON 生成，`filters` 键顺序不影响指纹。

## 2. 已确认的 Excel 契约

- 工作表：`Sheet 1`；
- 数据范围：`A1:X935`，共 24 列、934 位达人；
- 所有指标在源文件中均是文本；
- `--` 表示缺失值，落库为 `NULL`；
- 点击率如 `5.67%`，规范化为十进制 `0.0567`；
- 金额当前按 USD 两位小数转换为 minor unit，`795.84` 存为 `79584`；
- 文件只在文件名中带日期和“跨境4店”，不包含店铺 ID、币种、时区；这些信息必须在导入时显式确认；
- TikTok 导出的 worksheet dimension 可能错误标为 `A1`，解析器必须从实际 cell 数据重算范围。

非标准数字必须先经过统一规范化，再按字段类型校验：

| 输入形式                          | 处理规则                                          |
| --------------------------------- | ------------------------------------------------- |
| `--`、`—`、`N/A`、空单元格        | 仅允许出现在可空字段，保存为 `NULL`               |
| `$1,234.50`、`USD 1,234.50`       | USD 金额转为 minor unit                           |
| `1.2K`、`2.5万`、`1M`、`1亿`      | 展开缩写后再校验整数或金额精度                    |
| `5.67%`、`5.67％`                 | 转为 `0.0567`；Excel 原生数值百分比直接保留比例值 |
| `(34.80)`                         | 按会计负数解析为 `-34.80`                         |
| `1,2,3`、`1K-2K`、`1.2K+`、`<100` | 属于错误分组、区间或近似值，拒绝导入              |

计数、曝光、粉丝和平均客户数不得为负；点击率必须处于 0% 到 100%；金额超过两位小数不得静默四舍五入。必填指标遇到缺失标记时直接返回具体行号和字段名。

24 个字段全部进入正式映射：达人用户名、5 个联盟 GMV 字段、成交件数、佣金、固定费用、平均订单金额、橱窗商品数、订单量、点击率、曝光、平均客户数、直播/视频数、定向/公开合作 GMV 与佣金、退款 GMV/商品数、粉丝数。

## 3. 数据库分层

### 3.1 达人身份层：`affiliate_creators`

稳定字段：

- `tenant_id`
- `username` / `username_normalized`
- `creator_open_id`：Excel 阶段为空，API 阶段补齐
- `attributes`
- `first_seen_at` / `last_seen_at`

去重键：`tenant_id + username_normalized`。接入 API 后优先使用 `creator_open_id` 识别稳定身份，再做用户名别名归并。

### 3.2 报表窗口层：`affiliate_creator_reports`

一份文件、一次 API 查询对应一个报表批次：

- `period_start` / `period_end`：数据库内部列名，对外映射为闭区间 `windowStart` / `windowEnd`；
- `affiliate_creator_report_shops`：每个 report 必须且只能关联一个 `shopId`；
- `timezone`：数据库内部列名，对外映射为 `shopTimezone`；
- `currency` / `filters` / `scope_label`；
- `source_kind`：`excel_upload`、后续 `browser_capture` 或 `official_api`；
- `source_file_sha256`：文件幂等；
- `query_fingerprint + revision_no`：同一窗口多次导入保留版本；
- `row_count` / `status` / `imported_at`。

### 3.3 时间窗口指标层：`affiliate_creator_metrics`

每个 `report_id + creator_id` 一行，保存 Excel 的 23 个指标。不同日期范围不会更新旧行；同一范围重导生成 revision，便于退款、归因延迟和佣金变化对账。

## 4. 分步执行计划

### 步骤 1：Excel 解析与校验

做什么：

1. 严格验证 `.xlsx`、单工作表和 24 个表头；
2. 修复错误 worksheet dimension 后读取全部行；
3. 拒绝公式、重复用户名、非法金额/整数/百分比；
4. 生成 SHA-256、行数、文件名日期候选和警告；
5. 只做预览，不在用户确认元数据前写库。

文件：

- `erp-api/src/erp_api/services/affiliate_creator_excel_parser.py`
- `erp-api/src/erp_api/services/tiktok_number_parser.py`
- `erp-api/tests/test_affiliate_creator_excel_parser.py`

依赖：`openpyxl>=3.1,<4`。

验收：给定真实文件必须解析 934 行、24 列；`--`、金额和百分比转换测试通过。

### 步骤 2：PostgreSQL 落库与权限

做什么：

1. 创建四张表及租户安全复合外键；
2. 添加 `affiliate-center:view` 权限并授予 admin；
3. 同文件、同查询范围重复上传返回原报表；
4. 同查询范围、不同文件生成新 revision；
5. 导入事务内验证唯一 `shopId` 属于当前 tenant。

文件：

- `erp-api/src/erp_api/models/affiliate_creator.py`
- `erp-api/src/erp_api/services/affiliate_creator_repository.py`
- `erp-api/migrations/versions/d3e4f5a6b7c8_create_affiliate_creator_reports.py`
- `erp-api/src/erp_api/core/permissions.py`
- `erp-api/src/erp_api/bootstrap.py`

验收：迁移 head 为 `d3e4f5a6b7c8`，模型约束测试与全量后端测试通过。

### 步骤 3：内部上传与读取 API

接口：

- `GET /api/affiliate-center/resources`
- `GET /api/affiliate-center/shops`
- `POST /api/affiliate-center/imports/preview`
- `POST /api/affiliate-center/imports`
- `GET /api/affiliate-center/reports`
- `GET /api/affiliate-center/reports/{reportId}/creators`

预览和导入要求 `affiliate-center:view + sync:trigger`；读取要求 `affiliate-center:view`。上传最大 15 MB，不保存原文件，仅保存哈希和来源文件名。

文件：

- `erp-api/src/erp_api/routers/affiliate_center.py`
- `erp-api/src/erp_api/main.py`
- `erp-api/tests/test_affiliate_center_routes.py`

验收：无权限返回 403；错误表头/格式返回 422；未知店铺无法写库；重复文件幂等。

### 步骤 4：ERP 联盟中心页面

做什么：

1. 顶部导航在“畅销榜”后加入“联盟中心”；
2. 页面包含可独立切换的“达人”和“所有视频”资源标签；视频资源在 Parser 接入前显示明确空状态；
3. 上传后先预览，再确认单一店铺、日期、币种、时区和范围名；
4. 支持报表窗口切换和达人指标分页表格；
5. 不提供 Mock 静默回退，真实接口失败必须可见。

文件：

- `erp-web/src/features/affiliate-center/`
- `erp-web/src/router/route-metadata.tsx`
- `erp-web/src/router/route-pages.tsx`
- `erp-web/src/auth/permission-codes.ts`
- `erp-web/src/services/auth/mock-auth-api.ts`

验收：导航受权限控制；生产构建、lint 和前端测试通过；可完成预览、导入、切换报表和分页读取。

### 步骤 5：逆向达人 API

做什么：

1. 在卖家本人已登录的浏览器内监听响应；
2. 手工切换日期、筛选、排序和翻页，记录 host/method/path、分页和字段结构；
3. 响应 fixture 先脱敏，不记录 Cookie、token、签名和请求头；
4. 建立 `ApiAffiliateCreatorParser`，输出与 Excel parser 相同的规范 DTO；
5. 增加全量分页终止、重复 cursor、429/403、结构漂移和 completeness 校验；
6. `creator_open_id` 与现有 username 进行可审计归并；
7. `source_kind=browser_capture`，写入同一 report/metric 表。

建议新增文件：

- `erp-api/src/erp_api/services/affiliate_creator_api_parser.py`
- `erp-api/src/erp_api/services/affiliate_creator_capture_service.py`
- `erp-api/tests/fixtures/tiktok_affiliate_center/creators/`
- 对应 parser/capture/pagination 测试

验收：Excel 与 API 的同一业务行规范化结果一致；API 字段缺失时为 `NULL`，不能伪造 0；完整性不满足时 report 标为 partial，不覆盖 complete revision。

### 步骤 6：转换为官方 API

转换原则：路由、数据库、ERP 页面不变，只替换 source adapter。

```text
Excel row ─→ ExcelAffiliateCreatorParser ─┐
Browser payload ─→ ApiAffiliateCreatorParser ─┼→ AffiliateCreatorMetricInput
Official response ─→ OfficialAffiliateParser ─┘
```

官方化时需要：

1. 用 Open ID 作为达人稳定键，用户名降级为可变展示字段；
2. 将本地闭区间转换为 `[UTC start, UTC end)`，正确处理夏令时，并保留原始 `shopTimezone`；
3. 按官方 currency exponent 转 minor unit，不再固定两位小数；
4. 将官方 request ID、cursor、total count 写入同步运行审计，不写业务日志；
5. 对同一查询生成新的 `official_api` revision，与 Excel/监听器结果做差异对账；
6. 连续多个窗口一致后，前端默认来源切换为官方 API，Excel 保留为人工补录和审计通道。

### 步骤 7：所有视频

1. 先冻结“所有视频”页面真实字段、时间范围和分页；
2. 视频内容维度写入现有 `tiktok_video_contents`；
3. 时间窗口指标写入现有 `tiktok_video_performance_snapshots`；
4. 用 `creator_open_id` 关联达人，Excel 阶段无法可靠关联时保持为空；
5. 页面启用“所有视频”标签，增加达人/商品/日期筛选；
6. 官方 API 优先复用已有 Analytics 202605 客户端和同步运行/游标机制，避免重复建表。

## 5. 当前状态与阻塞边界

- 代码、迁移、Excel 解析和 ERP 页面已完成；
- 本地 PostgreSQL 已应用 `d3e4f5a6b7c8`；
- 用户已确认“跨境4店”是报表范围标签，对应 ERP 当前唯一的 active shop `Akeleo Fun Toys`，不是四个独立 shop；
- 2026-07-06 至 2026-07-12 的实际 Excel 已按 `America/Los_Angeles`、`USD` 导入；
- 数据库报表行数和指标行数均为 934，且 GMV、预计佣金、订单量和曝光合计与解析结果一致；
- 相同文件和查询范围再次导入会命中 SHA-256 幂等键并返回原报表，不会重复写入。

# 联盟中心页面采集与展示契约

状态：第 0 步已冻结。后续发现真实端点时只能补充端点和字段映射，不得放宽本文件的会话、安全、TTL 和完整性边界。

## 1. 页面展示口径

### 1.1 达人资源

一行代表：一个 `creator` 在一个 `shopId + window + currency + filters + revision` 中的表现。页面只读取最新的 `complete` revision，不跨窗口相加，不用旧窗口填充新窗口。

| 页面列     | 字段                       | 定义                             | 存储单位          | 页面单位                  | 时间语义             |
| ---------- | -------------------------- | -------------------------------- | ----------------- | ------------------------- | -------------------- |
| 达人       | `username`                 | 达人用户名                       | 字符串            | 原值                      | 身份字段             |
| 联盟 GMV   | `affiliateGmvMinor`        | 窗口内该达人产生的联盟成交总额   | 币种最小单位      | `query.currency` 主币单位 | 查询窗口汇总         |
| 视频 GMV   | `affiliateVideoGmvMinor`   | 窗口内带货视频产生的联盟成交总额 | 币种最小单位      | 主币单位                  | 查询窗口汇总         |
| 直播 GMV   | `affiliateLiveGmvMinor`    | 窗口内直播产生的联盟成交总额     | 币种最小单位      | 主币单位                  | 查询窗口汇总         |
| 预计佣金   | `estimatedCommissionMinor` | 平台按当前归因状态估算的佣金     | 币种最小单位      | 主币单位                  | 查询窗口汇总         |
| 订单量     | `affiliateOrderCount`      | 归因给达人的联盟订单数量         | orders            | 整数                      | 查询窗口汇总         |
| 成交件数   | `itemsSold`                | 归因给达人的商品件数             | items             | 整数                      | 查询窗口汇总         |
| 商品曝光   | `productImpressions`       | 联盟商品曝光次数                 | impressions       | 整数                      | 查询窗口汇总         |
| 点击率     | `clickThroughRate`         | 平台导出的点击率                 | `0..1` 十进制比率 | 百分比                    | 查询窗口汇总         |
| 带货视频数 | `affiliateVideoCount`      | 计入表现的带货视频数量           | videos            | 整数                      | 查询窗口汇总         |
| 直播数     | `affiliateLiveCount`       | 计入表现的直播场次数量           | live sessions     | 整数                      | 查询窗口汇总         |
| 粉丝数     | `affiliateFollowerCount`   | 报表生成时观察到的粉丝数         | followers         | 整数                      | 时点值，不是窗口累计 |

金额必须带报表 `currency`，数据库保存 minor unit，页面按主币单位格式化。不同币种、不同窗口或不同 revision 禁止直接相加。空值显示 `—`，不能转成 `0`。

默认排序固定为：

```text
affiliateGmvMinor DESC, username ASC
```

排序只在当前选中的完整 revision 内由 PostgreSQL 执行；空值排最后，`username ASC` 是稳定的并列排序键。当前页面不提供会改变查询指纹的临时客户端排序。

### 1.2 所有视频资源

视频资源保持独立，但截图和 Excel 没有提供可验证的视频字段与单位。因此当前状态固定为 `awaiting_verified_payload`：页面不展示生产视频指标、不设置默认业务排序。必须先在当前登录页面命中真实响应并验证字段、单位和平台排序，才能通过契约变更启用。

### 1.3 时间窗口

`windowStart`、`windowEnd` 是 `shopTimezone` 下首尾均包含的本地日期。请求时间戳转换为：

```text
[windowStart 00:00, windowEnd + 1 day 00:00) in shopTimezone -> UTC
```

转换使用 IANA 时区规则，跨夏令时的一天可能是 23 或 25 小时。

## 2. 页面监听边界

页面监听只能在用户当前已经登录并有权访问的 BrowserContext 内运行：

```text
当前登录页面 -> 白名单响应事件 -> 递归脱敏 -> 业务响应页 -> 后端规范化写入
```

强制规则：

1. Cookie、Authorization、access/refresh token、CSRF、OAuth code/state、session ID、签名和完整请求头不得离开浏览器会话；
2. 不向后端发送浏览器请求模板、动态签名 query、请求头或 Cookie；
3. 受控翻页只能让页面自身发起，或在同一 page context 内仅修改已批准的分页/筛选参数；
4. 后端不实现页面私有签名算法，不在浏览器外重放私有请求，也不持有 BrowserContext；
5. 会话退出、CAPTCHA、403 或登录失效立即停止并标记 `session_required`/`failed`，不转移凭证继续运行；
6. 浏览器到后端的唯一数据交接是脱敏后的业务响应和无敏感值的采集统计。

## 3. 原始响应和日志治理

### 3.1 原始响应 TTL

- 只保存递归删除禁止字段后的“脱敏原始响应”；
- 固定 TTL 为 7 天，过期后清空 raw payload，规范化事实和同步审计继续保留；
- raw payload 仅后端租户/店铺隔离存储，不进入 ERP 列表 API、浏览器缓存或导出文件；
- 如果脱敏无法确认完成，本页不得落 raw payload，只记录安全失败分类。

### 3.2 日志字段白名单

日志只能包含以下键：

```text
event, resource, tenant_id, shop_id, run_id, request_id, endpoint_key,
http_status, status, page_index, pages_fetched, records_received,
records_unique, duplicates, expected_total, duration_ms, failure_category,
cursor_hash, host, method, path, content_type, pagination_mode,
payload_discriminator
```

`cursor_hash` 只能是不可逆摘要；不记录原 cursor。白名单之外的字段由代码直接拒绝，不能依赖调用者自觉脱敏。

### 3.3 禁止字段

原始响应、fixture、日志和错误信息都禁止包含：

```text
access_token, refresh_token, authorization, cookie, set_cookie,
x_tts_access_token, csrf_token, oauth_code, oauth_state, session_id,
sign, signature, password, headers, request_headers, response_headers,
request_body, email, phone, address, buyer, recipient,
message, chat, conversation
```

匹配时忽略大小写以及 `_`、`-` 等分隔符，并递归处理对象和数组。

## 4. “全量完成”定义

每个资源独立计算，达人完成不代表视频完成。

终止条件满足任意一个：

```text
has_more == false
OR
next_cursor is null / empty / whitespace
```

随后按资源稳定键去重：

- 达人：优先 `creatorOpenId`；Excel 来源使用 `username_normalized`；
- 视频：`platformVideoId`；
- 日志和循环检测只保存这些标识或 cursor 的不可逆摘要，不保存浏览器凭证。

最终判断：

| 分页终止 | `total_count` | 唯一记录数           | 结果                                     |
| -------- | ------------- | -------------------- | ---------------------------------------- |
| 否       | 任意          | 任意                 | 未完成，继续分页或因保护条件标记 partial |
| 是       | 不提供        | 任意非负数           | complete                                 |
| 是       | 提供          | 等于 `total_count`   | complete                                 |
| 是       | 提供          | 不等于 `total_count` | partial，禁止发布为 complete             |

最大页数、超时、连续空页、重复 cursor、429、结构漂移等保护条件只能结束运行，不能单独证明“全量完成”。

## 5. 代码落点

- 后端展示定义：`erp_api.services.affiliate_center_display_contract`
- 会话/TTL/日志/禁止字段/完整性：`erp_api.services.affiliate_center_capture_policy`
- 端点契约脱敏观察器：`erp_api.services.affiliate_center_contract_observer`
- 联盟分析 CDP 同步器：`backend.app.services.tiktok_affiliate_analytics_capture`
- UI 受控翻页器：`backend.app.services.tiktok_affiliate_analytics_pager`
- 共享会话注册：`backend.app.services.tiktok_affiliate_capture.run_capture_session`
- 对外资源契约：`GET /api/affiliate-center/resources`
- TTL 配置：`AFFILIATE_CENTER_RAW_PAYLOAD_TTL_DAYS=7`

## 6. 已验证端点与观察记录

2026-08-25 已在当前登录会话中手动触发达人和所有视频的第二页。契约观察记录严格限定为：`host`、`method`、`path`、`contentType`、状态码、分页字段路径、响应字段路径和白名单 request ID。

| 资源     | method | path                                                        | discriminator                             | 分页模式         | 已验证分页字段                                 |
| -------- | ------ | ----------------------------------------------------------- | ----------------------------------------- | ---------------- | ---------------------------------------------- |
| 达人     | `POST` | `/api/v2/insights/affiliate/seller/creator/filter_list`     | `tiktok_affiliate_creator_filter_list.v1` | `page_page_size` | `has_more`、`next_page`、`total`、`total_page` |
| 所有视频 | `POST` | `/api/v1/oec/affiliate/compass/transaction/detail_list/get` | `tiktok_affiliate_video_detail_list.v1`   | `unknown`        | `total`                                        |

完整脱敏字段路径快照见 `affiliate-center-observed-contracts-2026-08-25.json`。该快照明确标记且不包含：

- query 及动态签名参数；
- 请求 headers；
- request body；
- 响应中的业务字段值。

除白名单 request ID 外，观察器只遍历响应 JSON 的键名和容器结构。响应正文不落盘，浏览器 Cookie、Authorization、签名及会话凭证不会离开当前 BrowserContext。

### 6.1 Payload discriminator

命中 method/path 后仍不能直接交给 parser，必须先通过对应 discriminator：

- 达人要求标准 envelope，以及非空 `data.segments[]`；每个 segment 必须同时具备 `filter.shop_id`、`list_control.next_pagination`、`list_control.rules`、`time_descriptor` 和非空 `timed_lists[]`。`stats[]` 允许为空；非空时每行必须包含达人身份、GMV 金额结构和订单字段。
- 所有视频要求标准 envelope，以及非空 `data.video_list_segments_v2[]`；每个 segment 必须同时具备 `time_descriptor`、`total` 和 `video_performances[]`。视频行允许为空；非空时每行必须同时具备 creator、product、video info 和关键 video metrics 结构。
- 两类 payload 不能交叉匹配；缺少任一结构锚点的相似响应一律在 parser 前拒绝，不尝试猜测或降级解析。

discriminator 只判断键、容器和必要结构，不依赖店铺 ID、达人 ID、金额等真实业务值。

### 6.2 分页模式判定

分页分类只使用已经观察到的字段名：

| 模式             | 必须出现的证据                                                                                    |
| ---------------- | ------------------------------------------------------------------------------------------------- |
| `page_page_size` | `page`、`page_size`、`page_index`、`page_num`、`next_page`、`total_page` 中至少一个明确页码族字段 |
| `offset`         | `offset`；单独出现 `limit` 不足以判定                                                             |
| `cursor`         | `cursor` 或 `next_cursor`；单独出现 `has_more` 不足以判定                                         |
| `mixed`          | 同一契约同时出现两个或以上已确认分页族                                                            |
| `unknown`        | 只有 `total`、`has_more`、`limit` 等不足以唯一判定的字段，或没有分页字段                          |

当前达人响应因真实出现 `next_page` 和 `total_page`，归类为 `page_page_size`。当前视频响应只出现 `total`，因此保持 `unknown`。本轮未读取 request body，快照明确记录 `requestPaginationObserved=false`；在获得新的字段名证据前，不得把视频预设为 page、offset 或 cursor。

### 6.3 被动捕获与 UI 受控翻页

同步器连接 BrowserContext 后保持被动，不刷新页面、不主动发请求。只有用户当前页面首次产生通过 endpoint 白名单和 payload discriminator 的响应后，才建立该资源的安全请求模板：

```text
resource + host + method + path + pagePath + triggerMode=page_control
```

模板不包含 query、headers、Cookie、request body、签名或 payload 值。响应所属 Page 通过 Playwright Frame 关系获得，Page 路径必须与资源严格匹配：

- `creators` → `/data/creator-analysis` → `.kora-pagination-item`
- `videos` → `/affiliate/assets/video-analysis` → `.core-pagination-item`

当前意图采集使用单一资源页作为登录载体。首个合法页面请求只用于在内存中取得当前会话的数据 API 模板；日期和分页只允许改写已验证的 `time_descriptor`、`list_control.pagination` 或 `page_param` 字段。后续页通过同一 Page 执行 `fetch`，不再反复刷新页面或新开标签页。

API 重放只在当前采集任务内存中保留 URL、请求体和必要业务 headers。Cookie、`sec-*`、User-Agent、Origin、Referer 等浏览器凭据或受限 headers 不复制、不记录、不持久化，由浏览器通过 `credentials=include` 提供；不实现或持久化 TikTok 的签名算法。响应仍必须经过原有 host/method/path、content-type、payload discriminator、店铺和日期窗口校验后才能入库。

首次请求、任意后续页出现 CAPTCHA、401、403 或 429 时，停止 API 重放并进入既定的验证码冷却/退避流程；人工验证稳定通过后才恢复同一个排队任务。

### 6.4 运行保护与资源独立状态

每个资源独立创建运行状态；达人进入终态不会修改视频状态，视频失败也不会终止达人。默认保护参数为：

| 参数         | 默认值                | 触发结果                            |
| ------------ | --------------------- | ----------------------------------- |
| 最大页数     | 200 页                | `partial / max_pages_exceeded`      |
| 最大运行时长 | 900 秒                | `partial / max_runtime_exceeded`    |
| 最小请求间隔 | 1 秒                  | 点击下一页前等待剩余间隔            |
| 最大连续空页 | 2 页                  | `partial / consecutive_empty_pages` |
| 重复 cursor  | 任一 SHA-256 摘要重复 | `partial / repeated_cursor`         |

原始 cursor 只在内存中参与 SHA-256 计算，状态和日志只保存 `sha256:` 摘要。资源状态至少包含：

```text
resource, status, expected_total, pages_fetched,
records_received, records_unique, duplicates,
consecutive_empty_pages, first_page_index, last_page_index,
last_cursor_hash, failure_category, terminal_reason,
started_at, finished_at
```

以下事件立即把对应资源置为终态，后续响应不再触发翻页：

| 证据                        | 状态               | failure_category               |
| --------------------------- | ------------------ | ------------------------------ |
| HTTP 401 或页面进入登录路径 | `session_required` | `session_expired`              |
| CAPTCHA URL/iframe/DOM      | `session_required` | `captcha`                      |
| HTTP 403                    | `failed`           | `http_403`                     |
| HTTP 429                    | `failed`           | `rate_limited`                 |
| content-type 改变           | `failed`           | `payload_content_type_changed` |
| discriminator 不再匹配      | `failed`           | `payload_structure_changed`    |

终态通过安全日志事件和内存 `resource_states` 暴露，不打印响应值或异常原文。后续持久化同步运行时，应原样映射该状态供 ERP 页面展示。

完整性仍遵守冻结规则：只有观察到 `has_more=false` 或空 `next_cursor`，并且从第 1 页开始、唯一记录数与 `total`（若提供）一致，才能标记 `complete`。单独观察到 UI 无下一页不能证明接口分页终止；例如当前视频响应只提供 `total`，因此停止时固定为 `partial / pagination_terminal_unverified`。

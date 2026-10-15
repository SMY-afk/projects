# 数据板块 v1 时间、金额与比例契约

## 1. 时间

- 所有 API 请求和响应时间均为带 `Z` 的 UTC ISO 8601 瞬间，例如 `2026-08-01T07:00:00Z`。
- 时间范围使用 `[from, to)`：包含 `from`，不包含 `to`。不得传入无时区的时间。
- 每个响应同时返回 `shopTimezone`（IANA 时区名，如 `America/Los_Angeles`）。前端仅用它将 UTC 时间转换为店铺当地展示时间；浏览器时区不能参与统计日边界。
- 当请求 TikTok 的按日接口时，后端根据 `shopTimezone` 将 UTC 范围转换为店铺自然日，再生成 `start_date_ge` 和 `end_date_lt`。平台返回的时间戳仍转换回 UTC 后对内输出。

```json
{
  "shopTimezone": "America/Los_Angeles",
  "range": {
    "from": "2026-08-01T07:00:00Z",
    "to": "2026-08-08T07:00:00Z"
  }
}
```

## 2. 金额

- 金额一律使用 `amountMinor + currency`，不传浮点数或格式化金额字符串。
- `amountMinor` 是最小货币单位的整数，可为负数（例如已确认的冲减）；正负语义必须由指标名称定义。
- `currency` 为三位大写 ISO 4217 代码。不同币种不可相加、比较或绘制为同一序列。
- 平台原始十进制金额在后端使用 `Decimal` 转换；前端只接收转换后的整数，不得再次以浮点数计算。

```json
{ "amountMinor": 12345, "currency": "USD" }
```

## 3. 比例和率

- `Rate` 使用 0 至 1 的小数，不使用带 `%` 的字符串。例如 `0.1234` 表示 `12.34%`。
- 服务端统一量化到小数点后 4 位；UI 仅在展示时乘以 100 并格式化到 2 位百分比。
- 比例字段必须包含指标名和分母口径；不能把点击率、转化率或退款率共用为无语义的数值。

## 4. 前后端 DTO

- 后端：`erp_api.services.data_schemas`。
- 前端：`src/features/data/types/data.types.ts`。
- 在真实 Analytics 响应完成验证前，DTO 只定义传输规范，不代表指标已可在 UI 展示。指标可用性仍以[数据指标字典](./data-metric-dictionary.md)为准。

## 5. 四类只读接口

所有接口都需要 `Authorization: Bearer <ERP access token>` 与 `data:view`，使用既有 `/api` 前缀和统一响应包络。`shopId` 必须属于当前租户；`from`、`to` 是 UTC ISO 8601 且组成 `[from, to)`；`granularity` 只能为 `day` 或 `all`。列表接口在此基础上支持 `pageToken` 和 `pageSize`，后者最大为 100。

| 接口                     | 用途           | `data` 主体             |
| ------------------------ | -------------- | ----------------------- |
| `GET /api/data/overview` | 店铺总览卡片   | `DataOverview`          |
| `GET /api/data/trends`   | 按时间桶的趋势 | `DataTrend`             |
| `GET /api/data/videos`   | 视频表现列表   | `DataPage<VideoMetric>` |
| `GET /api/data/lives`    | 直播场次列表   | `DataPage<LiveMetric>`  |

统一查询示例：

```text
GET /api/data/videos?shopId=shop_123&from=2026-08-01T07:00:00Z&to=2026-08-08T07:00:00Z&granularity=day&pageSize=20
```

`overview` 返回当前范围的汇总指标；`trends` 返回每个店铺自然日对应的 UTC 时间桶；`videos` 和 `lives` 返回内容/场次维度指标，但仍必须带相同的范围与粒度参数，避免页面之间的统计范围不一致。

```json
{
  "code": 0,
  "message": "OK",
  "data": {
    "shopId": "shop_123",
    "shopTimezone": "America/Los_Angeles",
    "range": {
      "from": "2026-08-01T07:00:00Z",
      "to": "2026-08-08T07:00:00Z"
    },
    "granularity": "day",
    "availability": "pending",
    "items": [],
    "freshness": {
      "status": "pending",
      "sourceUpdatedAt": null,
      "fetchedAt": null
    },
    "partialFailures": []
  },
  "requestId": "req_01J..."
}
```

真实 Analytics 已验证且有数据时，`availability` 才可为 `available`；尚未验证为 `pending`，平台明确不支持为 `unsupported`。这三种状态都不是数值，UI 必须展示对应说明而非默认 0。

## 6. 数据新鲜度与部分失败

每个四类接口的 `data` 都必须包含如下字段：

```text
freshness.status: fresh | stale | pending
freshness.sourceUpdatedAt: UTC ISO 8601 | null  # 平台可确认的源数据时间
freshness.fetchedAt: UTC ISO 8601 | null       # ERP 最近一次成功读取时间
partialFailures: [] | [{ scope, code, retryAfterSeconds?, requestId? }]
```

- `fresh`：本次数据满足该指标的已记录新鲜度要求。
- `stale`：可以安全展示最后一次成功快照，但 UI 必须显示“数据可能已过期”与 `fetchedAt`。
- `pending`：未完成真实探针或同步；UI 显示不可用，不得显示缓存之外的虚构数值。
- 部分失败使用 HTTP `200`：成功项可返回，失败项必须列入 `partialFailures`，不以静默省略、0 或 Mock 替代。
- 如果请求本身没有可返回的成功数据，则返回下表定义的错误，而不是伪造部分成功。

## 7. 数据模块错误语义

| HTTP | `code`                            | 含义                                       | 前端行为                                                       |
| ---: | --------------------------------- | ------------------------------------------ | -------------------------------------------------------------- |
|  400 | `DATA_QUERY_INVALID`              | `shopId`、UTC 范围、粒度或分页参数无效     | 显示参数错误，不保留旧筛选结果为新结果                         |
|  403 | `AUTH_FORBIDDEN`                  | ERP 用户缺少 `data:view`                   | 显示无权限                                                     |
|  404 | `RESOURCE_NOT_FOUND`              | 店铺不存在或不属于当前租户                 | 显示店铺不可用，不泄露其他租户信息                             |
|  409 | `TIKTOK_REAUTHORIZATION_REQUIRED` | 店铺未授权、授权失效或缺少 Analytics scope | 引导有 `shops:manage` 的用户重新授权；其他用户仅显示联系管理员 |
|  200 | `0` + `availability: no_data`     | 查询成功但该范围没有源数据                 | 显示“暂无数据”，不显示错误或 0 指标                            |
|  200 | `0` + `partialFailures`           | 部分数据源或时间桶失败                     | 展示成功项与局部失败提示                                       |
|  429 | `PLATFORM_RATE_LIMITED`           | TikTok 或 ERP 调度限流                     | 显示稍后重试；如有 `retryAfterSeconds` 则据此倒计时            |
|  502 | `PLATFORM_ERROR`                  | 平台返回错误或响应无法安全转换             | 显示平台暂不可用并提供 `requestId`                             |
|  503 | `DATA_SYNC_PENDING`               | 尚无可读快照且同步尚未完成                 | 显示“数据准备中”，不回退 Mock                                  |

`retryAfterSeconds` 仅在限流响应中返回，必须是非负整数。任何错误或 `partialFailures` 均不得包含 TikTok token、签名、授权码、`shop_cipher`、原始上游响应或买家 PII。

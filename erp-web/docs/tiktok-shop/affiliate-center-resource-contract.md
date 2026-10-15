# 联盟中心资源与查询契约

## 资源边界

| ERP 资源键 | 页面名称 | 当前数据入口                 | 领域输出                 |
| ---------- | -------- | ---------------------------- | ------------------------ |
| `creators` | 达人     | Excel，后续监听接口/官方 API | `AffiliateCreatorMetric` |
| `videos`   | 所有视频 | 后续监听接口/官方 API        | 独立视频内容与窗口指标   |

两者是并列资源。资源键必须参与查询指纹，因此相同店铺和时间窗口的达人查询与视频查询永远不会碰撞。

## 冻结查询维度

```text
shopId + windowStart + windowEnd + shopTimezone + currency + filters
```

| 字段           | 类型          | 语义                                                   |
| -------------- | ------------- | ------------------------------------------------------ |
| `shopId`       | UUID          | 单个 ERP 有效店铺；不接受数组                          |
| `windowStart`  | `YYYY-MM-DD`  | 店铺本地开始日期，包含当天                             |
| `windowEnd`    | `YYYY-MM-DD`  | 店铺本地结束日期，包含当天，不能早于开始日期           |
| `shopTimezone` | IANA timezone | 例如 `America/Los_Angeles`，禁止固定偏移量冒充店铺时区 |
| `currency`     | ISO 4217      | 三位大写代码；Excel 达人 Parser 当前仅支持 `USD`       |
| `filters`      | JSON object   | 资源特有筛选；无筛选时必须传 `{}`                      |

`filters` 会按键排序后参与查询指纹，最大 16 KB、最多嵌套五层。不得包含 token、cookie、OAuth code、secret、signature 等凭证字段。

## 时间窗口转换

页面和内部导入 API 使用店铺本地闭区间日期。上游接口若使用时间戳，则统一转换为 UTC 半开区间：

```text
[local windowStart 00:00, local (windowEnd + 1 day) 00:00)
                         ↓ IANA timezone
[UTC start, UTC end)
```

转换必须使用 IANA 时区规则，不能假设每天固定 24 小时；跨夏令时日期可能对应 23 或 25 小时。

## 规范化与查询指纹

指纹输入是以下规范 JSON：

```json
{
  "resource": "creators",
  "shopId": "51ba6400-7342-5009-a0be-7f899faae12e",
  "windowStart": "2026-07-06",
  "windowEnd": "2026-07-12",
  "shopTimezone": "America/Los_Angeles",
  "currency": "USD",
  "filters": {}
}
```

生成规则：UTF-8、对象键排序、无多余空白，再计算 SHA-256。指纹用于文件幂等、同查询 revision 归组，以及 Excel、监听接口、官方 API 三种来源的差异对账。

## Excel 到监听接口再到官方 API

三个来源只负责把原始字段转换为同一领域输入，路由和存储读取契约不随来源改变：

```text
Excel parser ───────┐
Browser API parser ─┼→ normalized resource input → PostgreSQL
Official API parser ┘
```

转换到官方 API 时：

1. 使用相同六维查询对象生成请求窗口和指纹；
2. `creators`、`videos` 分别实现 source adapter，不共用上游 payload DTO；
3. 官方返回的 cursor、request ID 和完整性状态写同步审计，不写入查询维度；
4. 官方币种按 exponent 转 minor unit；Excel 达人来源继续执行当前 USD 两位小数限制；
5. 同一查询的新来源写新 revision，先对账，确认一致后再切换默认来源。

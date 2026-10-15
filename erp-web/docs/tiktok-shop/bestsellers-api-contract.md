# TikTok Shop 畅销榜 API 契约与字段准入表

> 核验日期：2026-08-20  
> API 版本：`202511`  
> 适用模块：ERP `/bestsellers`  
> 状态：平台契约已冻结；`data.bestselling.public.read` 已重新授权并落库；四接口 `7D` 最小只读探针已通过。

## 1. 契约结论

1. 四个 API 统一使用 `date + time_slot`，不接受 ERP 自定义的任意 `from/to`。
2. `date` 是店铺注册时区中的参考日期，且包含该日；平台从该日期向前计算周期。
3. `time_slot` 只允许 `1D | 7D | 30D`。
4. 每类最多返回 Top 100，榜单范围是已授权卖家所在市场，不是当前店铺自己的经营排行榜。
5. 四个 API 均要求 seller access token、`shop_cipher` 和 Scope `data.bestselling.public.read`。
6. `currency` 只允许 `USD | LOCAL`，ERP 必须显式发送，不依赖平台默认值。
7. `gmv_range` 是平台脱敏区间，并包含随机偏移；只能原样展示，不能参与计算。
8. 四类数据节点和首条记录字段名已由 `7D` 探针确认；字段类型、嵌套结构、时间/时长单位和视频 `30D` 的准确窗口仍待专项验证。

## 2. 四个 API 总表

| 实体   | 名称                     | 方法与路径                                   | 版本     | Scope                          | 数据节点          |
| ------ | ------------------------ | -------------------------------------------- | -------- | ------------------------------ | ----------------- |
| 商品   | Get Bestselling Products | `GET /analytics/202511/products/bestselling` | `202511` | `data.bestselling.public.read` | `data.products[]` |
| 创作者 | Get Bestselling Creators | `GET /analytics/202511/creators/bestselling` | `202511` | `data.bestselling.public.read` | `data.creators[]` |
| 视频   | Get Bestselling Videos   | `GET /analytics/202511/videos/bestselling`   | `202511` | `data.bestselling.public.read` | `data.videos[]`   |
| 直播   | Get Bestselling LIVEs    | `GET /analytics/202511/lives/bestselling`    | `202511` | `data.bestselling.public.read` | `data.lives[]`    |

官方发布说明确认四个接口均返回目标市场 Top 100，按 GMV 排名。

## 3. 请求参数

### 3.1 公共 Header

| 参数                 | 必填 | 来源                    | ERP 处理                           |
| -------------------- | ---- | ----------------------- | ---------------------------------- |
| `content-type`       | 是   | 固定 `application/json` | 后端设置                           |
| `x-tts-access-token` | 是   | seller OAuth token      | 仅后端解密使用，不返回浏览器或日志 |

### 3.2 公共 Query

| 参数          | 类型   |     必填 | 允许值/格式            | ERP 处理                               |
| ------------- | ------ | -------: | ---------------------- | -------------------------------------- |
| `app_key`     | string |       是 | Partner Center App Key | 后端配置                               |
| `sign`        | string |       是 | TikTok 签名算法结果    | 复用 `TikTokTransport` 生成            |
| `timestamp`   | int    |       是 | UTC Unix 秒            | 后端生成                               |
| `shop_cipher` | string |       是 | 授权店铺 cipher        | 后端解密使用，不返回浏览器             |
| `date`        | string |       是 | `YYYY-MM-DD`           | 按店铺注册时区解释，参考日包含在窗口内 |
| `time_slot`   | string |       是 | `1D / 7D / 30D`        | 不接受其他值，不转换任意起止日期       |
| `currency`    | string | ERP 必填 | `USD / LOCAL`          | ERP 总是显式发送                       |

### 3.3 创作者专属 Query

| 参数          | 类型   | ERP 必填 | 允许值                                 | 说明                                                                               |
| ------------- | ------ | -------: | -------------------------------------- | ---------------------------------------------------------------------------------- |
| `author_type` | string |       是 | `ALL / OFFICIAL / CHANNEL / AFFILIATE` | 官方文档同时出现“Required”和“未提供时默认全部”两种表述；ERP 始终显式发送以消除歧义 |

### 3.4 ERP 禁止接受的参数

- `from`
- `to`
- `start_date_ge`
- `end_date_lt`
- 任意自定义周期，例如 `14D`、`60D`、`90D`

如果以后需要任意日期表现榜，应使用店铺 Performance API 建立另一套“本店经营榜”，不能伪装为 Bestsellers。

## 4. `date + time_slot` 时间语义

以店铺时区参考日 `2026-08-19` 为例：

| `time_slot` | ERP 展示文案               | 逻辑窗口                                 |
| ----------- | -------------------------- | ---------------------------------------- |
| `1D`        | 2026-08-19 单日            | 截止并包含 2026-08-19 的 1 日            |
| `7D`        | 截至 2026-08-19 的近 7 日  | 平台从参考日向前计算 7 日                |
| `30D`       | 截至 2026-08-19 的近 30 日 | 平台从参考日向前计算；视频语义需探针确认 |

前端控件必须是“结束日期 + 周期”，不能使用双日期 RangePicker。

### 4.1 官方文档冲突

官方发布说明称四类都支持 `1D / 7D / 30D`。创作者参考页说明 `30D` 查询 30 天；但视频参考页当前文字写成“`30D` — query data for 14 days”。因此：

- 请求枚举仍保留 `30D`。
- 视频页在探针前不得承诺一定覆盖 30 个自然日。
- 重新授权后必须对视频分别请求 `7D`、`30D`，结合响应元数据或 Seller Center 对照确认。
- 若平台未返回窗口证据且文档仍冲突，生产 UI 暂时禁用视频 `30D`。

## 5. 公共响应 Envelope

| 字段         | 类型   | 状态     | ERP 用途                                 |
| ------------ | ------ | -------- | ---------------------------------------- |
| `code`       | int    | 官方确认 | `0` 视为平台成功；其他值进入安全错误映射 |
| `message`    | string | 官方确认 | 作为上游诊断输入，不原样暴露敏感内容     |
| `request_id` | string | 官方确认 | 保存为 `platform_request_id`             |
| `data`       | object | 官方确认 | 各实体数组容器                           |

`code == 0` 但数组为空表示成功空榜，不得映射成授权失败。

## 6. 返回字段准入表

| 状态                | 含义                                   | UI 行为                                            |
| ------------------- | -------------------------------------- | -------------------------------------------------- |
| `allowed`           | 官方字段路径或样例已确认，业务语义安全 | 可进入解析器和 UI                                  |
| `probe_required`    | 当前路径、类型、单位或真实响应未确认   | 可进入受 TTL 管理的脱敏 raw payload，不进入生产 UI |
| `forbidden_derived` | 会把脱敏范围伪装成精确指标             | 不存为数值，不展示计算结果                         |

### 6.1 商品榜 `data.products[]`

| 字段路径                     | 类型     | 状态             | 展示/处理                            |
| ---------------------------- | -------- | ---------------- | ------------------------------------ |
| `product_image`              | object   | `allowed`        | 图片对象                             |
| `product_image.height`       | int64    | `allowed`        | 尺寸元数据，不单独展示               |
| `product_image.width`        | int64    | `allowed`        | 尺寸元数据，不单独展示               |
| `product_image.thumb_urls[]` | string[] | `allowed`        | 表格缩略图首选                       |
| `product_image.uri`          | string   | `allowed`        | 仅保存，不直接拼接 URL               |
| `product_image.urls[]`       | string[] | `allowed`        | 大图候选                             |
| `gmv_range`                  | string   | `allowed`        | 原样展示，不解析                     |
| `id`                         | string   | `probe_required` | 字段名已确认；类型和稳定性待专项验证 |
| `name`                       | string   | `probe_required` | 字段名已确认；类型和空值待专项验证   |
| `rank`                       | int      | `probe_required` | 字段名已确认；类型和空值待专项验证   |
| 类目、评分、价格、销量       | unknown  | `probe_required` | 必须确认路径、类型和口径             |

商品图片是 2026-05 官方更新明确新增的字段；完整响应表在当前动态参考页中未能可靠展开，其他字段以真实探针为准。

### 6.2 创作者榜 `data.creators[]`

| 字段路径          | 类型    | 状态             | 展示/处理                                    |
| ----------------- | ------- | ---------------- | -------------------------------------------- |
| `rank`            | int     | `allowed`        | 排名                                         |
| `gmv_range`       | string  | `allowed`        | 原样展示                                     |
| `open_id`         | string  | `allowed`        | 稳定识别键；UI 缩略显示并允许复制            |
| `user_name`       | string  | `allowed`        | 用户名                                       |
| `nick_name`       | string  | `allowed`        | 昵称                                         |
| `followers_count` | int64   | `allowed`        | 粉丝数                                       |
| `likes_count`     | int64   | `allowed`        | 获赞数                                       |
| 头像 URL          | unknown | `probe_required` | 当前官方样例未确认                           |
| 作者类型响应字段  | unknown | `probe_required` | 请求有 `author_type`，样例未确认是否逐项返回 |

### 6.3 视频榜 `data.videos[]`

| 字段路径                       | 类型     | 状态             | 展示/处理                                          |
| ------------------------------ | -------- | ---------------- | -------------------------------------------------- |
| `gmv_range`                    | string   | `allowed`        | 原样展示                                           |
| `views`                        | int64    | `allowed`        | 播放次数，不能称为去重观看人数                     |
| `likes`                        | int64    | `allowed`        | 点赞数                                             |
| `comments`                     | int64    | `allowed`        | 评论数                                             |
| `shares`                       | int64    | `allowed`        | 分享数                                             |
| `product_infos[]`              | object[] | `allowed`        | 关联商品列表                                       |
| `product_infos[].product_id`   | string   | `allowed`        | 关联商品 ID                                        |
| `product_infos[].product_name` | string   | `allowed`        | 关联商品名称                                       |
| `publish_time`                 | int64    | `allowed`        | Unix 秒；后端转 UTC，前端按店铺时区展示            |
| `duration`                     | int64    | `probe_required` | 字段存在，但单位需探针确认后再格式化               |
| `id`                           | string   | `probe_required` | 字段名已确认；类型和稳定性待专项验证               |
| `rank`                         | int      | `probe_required` | 字段名已确认；类型和空值待专项验证                 |
| 标题、封面、创作者对象         | unknown  | `probe_required` | 不从其他 Performance API 混入冒充 Bestsellers 响应 |

### 6.4 直播榜 `data.lives[]`

| 字段路径                 | 类型    | 状态             | 展示/处理                                  |
| ------------------------ | ------- | ---------------- | ------------------------------------------ |
| `gmv_range`              | string  | `probe_required` | 字段名已确认；值仍只可作为不可计算区间处理 |
| `id`                     | string  | `probe_required` | 字段名已确认；类型和稳定性待专项验证       |
| `rank`                   | int     | `probe_required` | 字段名已确认；类型和空值待专项验证         |
| `title`、创作者字段      | unknown | `probe_required` | 字段名已确认；类型、空值和展示语义待验证   |
| `start_time`、`duration` | unknown | `probe_required` | 字段名已确认；时间格式和时长单位待验证     |
| 观看、点赞、评论、分享   | unknown | `probe_required` | 探针确认字段和去重口径                     |
| 关联商品                 | unknown | `probe_required` | 探针确认数组结构                           |

直播完整响应字段未从当前官方动态页面可靠取得。解析器可保留未知字段，但 UI 只展示通过准入的字段。

最小只读探针证据见 `bestsellers-api-probe-2026-08-20.json`。该文件只保留状态码、request ID 和字段名，不含 token、签名、`shop_cipher` 或响应字段值。

## 7. GMV 区间处理规则

### 7.1 允许

- 将 `gmv_range` 保存为原始字符串，例如 `$97K ~ $191K`。
- 展示平台币种上下文和“脱敏区间”标签。
- 使用平台显式返回的 `rank`；若无 rank，只按数组顺序展示 ERP 序号。
- 比较同一实体在两个快照中的排名变化，并显示各自日期和周期。

### 7.2 禁止

- 用区间中点生成“估算 GMV”。
- 提取上下界后求和、平均、同比、环比、份额、ROI、GPM 或转化率。
- 将区间转换成固定 `amountMinor`。
- 跨币种比较或换算。
- 汇总四类榜单 GMV。
- 用本店订单金额替换或校准市场畅销榜的脱敏 GMV。

建议内部类型：

```ts
interface DesensitizedGmvRange {
  raw: string
  currencyContext: 'USD' | 'LOCAL'
  computable: false
}
```

`computable` 必须固定为 `false`，不得由客户端修改。

## 8. 真实探针升级门槛

重新授权后，每个 API 使用同一组安全测试条件：

```text
shop = Akeleo Fun Toys
date = 店铺时区下最近一个已完成自然日
time_slot = 7D
currency = USD
author_type = ALL（仅创作者）
```

探针只记录：

- HTTP 状态与 TikTok `code`
- `request_id`
- 顶层和单条记录字段名
- JSON 类型、null 情况和数组长度
- 是否返回 rank、稳定实体 ID、图片/封面字段
- 时间字段格式与 duration 单位
- 视频 `30D` 实际窗口证据

禁止记录 token、App Secret、sign、OAuth code/state、`shop_cipher` 或未脱敏完整响应日志。

字段从 `probe_required` 升级为 `allowed` 必须同时满足：

1. 官方说明或真实响应路径已确认。
2. 类型、单位、null 和枚举已确认。
3. 展示名称不会改变指标含义。
4. 后端解析测试和前端不可用状态测试已补充。
5. 真实模式失败不会回退 Mock。

## 9. 官方资料

- [Bestsellers Analytics Open API Launch](https://partner.tiktokshop.com/docv2/page/3dk9557y)
- [Get Bestselling Products](https://partner.tiktokshop.com/docv2/page/get-bestselling-products-202511)
- [Get Bestselling Creators](https://partner.tiktokshop.com/docv2/page/get-bestselling-creators-202511)
- [Get Bestselling Videos](https://partner.tiktokshop.com/docv2/page/get-bestselling-videos-202511)
- [Get Bestselling LIVEs](https://partner.tiktokshop.com/docv2/page/get-bestselling-lives-202511)
- [Analytics API Response Data Optimization](https://partner.tiktokshop.com/docv2/page/kpkfccsa)

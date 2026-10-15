# TikTok Shop 内容发布市场矩阵

基线日期：2026-08-21。平台开放范围可能随应用、灰度和 Beta allowlist 变化；Partner Center 当前应用显示结果优先于本表。

| 能力             | 官方市场条件                                                                                                             | 当前店铺/应用事实                                                        | Gate                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------ | ---------------------- |
| Creator OAuth    | 授权选择区必须是应用 Target Market；官方指南列出 ID、IE、MY、PH、SG、TH、UK、US、VN，并提示部分能力可能需 Beta allowlist | 店铺为 US；当前应用 Target Market 因 Partner Center 页面无法加载而未核实 | BLOCKED                |
| Creator Profile  | 需真实 Creator 或 TikTok 提供的 Test Creator，且授权区匹配应用                                                           | 未取得 Test Creator/Creator token                                        | BLOCKED                |
| Showcase         | 授权前必须完成 Selection Region；缺失会返回 `18001405`                                                                   | US 店铺已知，但 Creator Selection Region 未知                            | BLOCKED                |
| 发布挂车视频     | 受 Creator 身份、Target Market、Scope、账号状态和类目限制共同控制                                                        | 202607 契约与应用开放状态未核实                                          | BLOCKED                |
| 发布挂车图片     | 受 Creator 身份、Target Market、Scope、账号状态及应用灰度控制                                                            | 精确接口契约和应用开放状态未核实                                         | BLOCKED                |
| Creator 视频表现 | 官方页面限定 US Creator；数据 T-1，最多回看 180 天                                                                       | 店铺市场 US 符合，但缺 Creator token/身份映射                            | BLOCKED                |
| Shop 视频表现    | 202405+ Analytics APIs 面向所有 TikTok Shop 市场及本土/跨境卖家；数据 T-1                                                | US 店铺，Seller Scope 已有                                               | PASS                   |
| 图片内容独立表现 | 未找到官方独立 Photo Performance API                                                                                     | 不能以视频指标替代，也不能把缺失数据写成 0                               | UNAVAILABLE/UNVERIFIED |

## 当前市场快照

| 项目                  | 值                  |
| --------------------- | ------------------- |
| 店铺                  | Akeleo Fun Toys     |
| Market                | US                  |
| Timezone              | America/Los_Angeles |
| Shop status           | active              |
| Seller authorization  | authorized          |
| Creator authorization | absent              |

## 市场准入验收

1. 在 Partner Center 当前应用中记录 Target Market 和 Creator API Beta/allowlist 状态。
2. 使用同市场 Test Creator 完成授权，校验 `user_type=1` 和 Selection Region。
3. 分别运行 Profile、Showcase、Upload、Precheck、Post、Status 的 API Testing Tool 请求。
4. 市场不支持时标记 `UNSUPPORTED_MARKET`，不得回退 Mock 或复用其他市场 Creator token。
5. 表现数据按店铺时区展示，但按官方 T-1 可用性解释，避免把尚未产出的数据记为零。

## 官方依据

- [Creator Authorization Guide](https://partner.tiktokshop.com/docv2/page/creator-authorization-guide)
- [Get Showcase Products](https://partner.tiktokshop.com/docv2/page/get-showcase-products)
- [Get Video Performances](https://partner.tiktokshop.com/docv2/page/get-video-performances-202403)
- [Analytics API global availability](https://partner.tiktokshop.com/docv2/page/j5k1cmia)

# TikTok Shop 内容发布 Scope 矩阵

基线日期：2026-08-21。`当前状态`来自本地授权连接的脱敏检查及官方接口负向探针。

| 能力                 | 令牌主体               | 官方 Scope                                                                               | 当前状态                                               | Gate                |
| -------------------- | ---------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------ | ------------------- |
| 创作者资料           | Creator，`user_type=1` | `creator.affiliate.info` **或** `creator.video.write`                                    | 应用 `creator.video.write` 已 Active；无 Creator Token | TOKEN PENDING       |
| 查看橱窗             | Creator，`user_type=1` | `creator.showcase.read` **或** `creator.video.write`                                     | 应用 `creator.video.write` 已 Active；无 Creator Token | TOKEN PENDING       |
| 管理橱窗             | Creator，`user_type=1` | 当前应用 API Page 中确认写 Scope                                                         | 未确认                                                 | BLOCKED             |
| 上传视频/图片素材    | Creator，`user_type=1` | `creator.video.write`                                                                    | 应用 Scope Active；Token 待授权                        | TOKEN PENDING       |
| 内容预检             | Creator，`user_type=1` | `creator.video.write`                                                                    | 应用 Scope Active；Token 待授权                        | TOKEN PENDING       |
| 发布视频/图片        | Creator，`user_type=1` | `creator.video.write`                                                                    | 应用 Scope Active；Token 待授权                        | TOKEN PENDING       |
| 查询视频发布状态     | Creator，`user_type=1` | `creator.video.write`                                                                    | 应用 Scope Active；Token 待授权                        | TOKEN PENDING       |
| 创作者视频表现       | Creator，`user_type=1` | `creator.video.write`                                                                    | 应用 Scope Active；Token 待授权                        | TOKEN PENDING       |
| 店铺视频表现/概览    | Seller                 | `data.shop_analytics.public.read`                                                        | 已授权                                                 | PASS                |
| 店铺热销数据         | Seller                 | `data.bestselling.public.read`                                                           | 已授权                                                 | PASS（非发布 Gate） |
| 内容发布事件 type 17 | Creator                | 官方显示名 `Read Creator Affiliate Collaborations`；精确标识符需在当前应用 API Page 冻结 | 未授权                                                 | BLOCKED             |

## 授权判定规则

```text
token response code == 0
AND user_type == 1
AND open_id is present
AND required scope is included in granted_scopes
```

- Seller token 与 Creator token 是不同主体，Scope 文本不能跨主体复用。
- ERP 只保存后端加密后的令牌；前端、日志、探针产物均不得出现令牌、refresh token 或授权 code。
- `creator.video.write` 是发布链路的硬依赖；仅具备资料或橱窗只读 Scope 时，发布按钮必须禁用并展示缺失权限。
- Scope 申请已提交但尚未批准，仍按未授权处理。

## 本地实测

2026-08-21 使用当前已授权 Seller token 对两个 Creator 只读接口进行负向控制：

| 接口              | 结果                 |
| ----------------- | -------------------- |
| Creator Profile   | `36009005`，HTTP 401 |
| Showcase Products | `36009004`，HTTP 400 |

结果证明当前 Seller 授权不能代替 Creator 授权；探针未记录原始响应值。

## 官方依据

- [Creator Authorization Guide](https://partner.tiktokshop.com/docv2/page/creator-authorization-guide)
- [Get Creator Profile](https://partner.tiktokshop.com/docv2/page/get-creator-profile)
- [Get Showcase Products](https://partner.tiktokshop.com/docv2/page/get-showcase-products)
- [Upload Shoppable Video File](https://partner.tiktokshop.com/docv2/page/upload-shoppable-video-file-202505)
- [Get Video Performances](https://partner.tiktokshop.com/docv2/page/get-video-performances-202403)
- [Shop Video Performance API update](https://partner.tiktokshop.com/docv2/page/kpkfccsa)
- [Event type 17: Shoppable Content Posting](https://partner.tiktokshop.com/docv2/page/17-shoppable-content-posting)

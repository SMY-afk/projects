# 数据板块最小 OAuth 权限与重新授权方案

> 核验日期：2026-08-14  
> 测试店铺：`Akeleo Fun Toys`（US）  
> 本文只设计权限和授权流程，不修改当前店铺授权、公共 API 或数据库结构。

## 1. 结论

当前店铺已经具备数据板块所需的全部最小 OAuth scope：

```text
required = {
  seller.shop.info,
  seller.authorization.info,
  data.shop_analytics.public.read
}

missing = {}
```

因此：

- 当前不需要重新授权，也不需要增加 OAuth scope。
- 可以直接进入 Analytics 最小只读探针阶段。
- 当前 token 还包含商品、订单、物流和财务 scope；这些属于 ERP 其他模块，不能因为数据板块不需要就移除。
- Token 到期后的正常 refresh 不等于重新授权；只有缺少 scope、授权被撤销或 refresh token 失效时才需要卖家重新同意授权。

## 2. 数据板块最小 OAuth scope

| Scope                             | 必要性                  | 使用位置                                                                | 不具备时的结果                                         |
| --------------------------------- | ----------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------ |
| `data.shop_analytics.public.read` | 核心、必需              | 店铺、视频、直播 Analytics 全部首期接口                                 | Analytics 请求被拒绝，数据板块不可用                   |
| `seller.authorization.info`       | 授权闭环必需            | `GET /authorization/202309/shops`，确认授权店铺并取得正确 `shop_cipher` | 无法可靠确认授权店铺，尤其跨境店不能安全调用 Analytics |
| `seller.shop.info`                | 当前 OAuth 回调实现必需 | 当前配置的 `GET /seller/202309/shops` 店铺身份读取                      | 当前回调中的 `get_shop_identity()` 无法完成            |

说明：如果未来删除回调中重复的店铺身份读取，并完全以 `Get Authorized Shops` 为唯一身份来源，理论上可重新评估 `seller.shop.info` 是否还能移出“数据板块授权闭环”。在当前实现下不可移除。

## 3. 当前授权差集

当前 `shop_connections.scopes`：

| Scope                             | 数据板块是否需要 | 归属                  |
| --------------------------------- | ---------------: | --------------------- |
| `data.shop_analytics.public.read` |               是 | 数据板块              |
| `seller.authorization.info`       |               是 | 店铺授权闭环          |
| `seller.shop.info`                |               是 | 当前店铺身份读取      |
| `seller.product.basic`            |               否 | 商品模块              |
| `seller.order.info`               |               否 | 订单模块              |
| `seller.logistics`                |               否 | 订单/物流模块         |
| `seller.finance.info`             |               否 | 订单归因/财务相关能力 |

计算结果：

```json
{
  "missingScopes": [],
  "reauthorizationRequiredForDataModule": false,
  "analyticsProbeAllowed": true
}
```

## 4. ERP 内部权限清单

OAuth scope 决定 TikTok 是否允许应用读取数据；ERP permission 决定哪个 ERP 用户可以操作。两者不能混用。

| ERP permission | 首期用途                     | 建议角色                 |
| -------------- | ---------------------------- | ------------------------ |
| `data:view`    | 查看概览、视频、直播数据     | 数据分析员、运营、管理员 |
| `shops:view`   | 查看店铺名称和连接状态       | 数据分析员、运营、管理员 |
| `sync:trigger` | 手动触发 Analytics 同步      | 仅管理员/高级运营        |
| `shops:manage` | 发起授权、重新授权、断开连接 | 仅管理员                 |

普通数据查看者的最小 ERP 权限为：

```text
data:view
shops:view
```

这不会授予重新授权或手动同步权限。

## 5. 上线前的 scope preflight

后端开始任何 Analytics 同步前，必须先执行服务端检查：

```text
1. 根据 tenant_id + shop_id 查询 ShopConnection
2. 确认 auth_status == authorized
3. 确认 access token/refresh token 状态可用
4. 计算 missing_scopes = REQUIRED_SCOPES - granted_scopes
5. missing_scopes 为空 -> 允许进入 Analytics 请求
6. missing_scopes 非空 -> 停止任务，返回 reauthorization_required
```

建议内部结果结构：

```ts
interface TikTokDataAuthorizationStatus {
  shopId: string
  status: 'ready' | 'reauthorization_required' | 'disconnected' | 'expired'
  requiredScopes: string[]
  grantedScopes: string[]
  missingScopes: string[]
  canReadAnalytics: boolean
}
```

安全要求：

- `grantedScopes` 可以返回给有 `shops:view` 的用户。
- access token、refresh token、授权码、state、签名和 `shop_cipher` 不得返回浏览器。
- 缺少 scope 时不得尝试使用其他店铺 token、广告 token 或前端直连平台来绕过授权。

## 6. 将来缺少 scope 时的重新授权方案

### 6.1 触发条件

仅在以下情况发起重新授权：

1. `missing_scopes` 非空。
2. TikTok 返回明确的 scope/authorization 错误，且本地 scope 记录可能过期。
3. 店铺撤销授权或 refresh token 已不可恢复。

HTTP 429、超时、5xx、查询日期非法或没有数据都不是重新授权条件。

### 6.2 Partner Center 配置

1. 在 TikTok Shop Partner Center 中给当前 `service_id` 对应服务申请并启用缺失 scope。
2. 等待权限审批/生效。
3. 不把 scope 拼到 OAuth URL 中猜测授权；当前授权入口由 `service_id` 决定服务所请求的权限集合。
4. 配置完成后由卖家重新确认授权，新 token 才可能获得新增 scope。refresh token 不能代替用户同意完成 scope 升级。

### 6.3 后端重新授权流程

建议新增独立路由，不改变现有普通授权路由语义：

```text
POST /api/v1/shops/tiktok/{shop_id}/reauthorization-url
```

请求前置条件：

- 登录有效。
- 当前用户具有 `shops:manage`。
- `shop_id` 属于当前 `tenant_id`。
- 后端确认确实存在缺少 scope 或授权失效。

一次性 state 建议记录：

```json
{
  "userId": "uuid",
  "tenantId": "uuid",
  "shopId": "uuid",
  "platformShopId": "platform-id",
  "intent": "scope_upgrade",
  "requiredScopes": ["seller.shop.info", "seller.authorization.info", "data.shop_analytics.public.read"],
  "state": "opaque-random-value"
}
```

state 继续使用 Redis、600 秒 TTL、一次性消费。scope upgrade 回调必须要求 TikTok 返回并匹配 state，不允许使用当前兼容的“无 state pending fallback”。

### 6.4 回调校验与原子替换

回调必须按以下顺序执行：

1. 原子消费并校验 state。
2. 使用授权码换取新 token。
3. 调用 `Get Authorized Shops` 获取授权店铺和 `shop_cipher`。
4. 校验返回的 `platformShopId` 与 state 绑定的目标店铺一致。
5. 校验 `requiredScopes ⊆ token.scopes`。
6. 只有以上检查全部成功，才在单个数据库事务中替换 token、expiry、scope 和 `shop_cipher`。
7. 任一检查失败，保留旧连接和旧 token，不执行断开，不把不完整的新授权覆盖到可工作的旧授权上。
8. 写入脱敏审计记录，随后执行一次最小 Analytics 探针。

成功条件：

```text
目标店铺一致
AND missing_scopes == []
AND Analytics probe 成功
```

### 6.5 前端交互

数据页面只在后端返回 `reauthorization_required` 时显示：

```text
TikTok Shop 授权缺少数据读取权限，需要管理员重新授权。
```

- 普通用户只看到联系管理员提示。
- 有 `shops:manage` 的管理员看到“重新授权”按钮。
- UI 可以展示缺少的 scope 名称，但不得接受前端传入 `verified=true` 或自定义 scope 作为可信依据。

## 7. 现有实现与设计差距

| 位置                                 | 当前行为                                        | scope upgrade 需要的改进                                                    |
| ------------------------------------ | ----------------------------------------------- | --------------------------------------------------------------------------- |
| `tiktok_authorization.py`            | state 只绑定 user/tenant；另有无 state fallback | 绑定目标 `shopId/platformShopId/intent/requiredScopes`；升级流程强制 state  |
| `routers/tiktok.py`                  | 回调换 token 后直接 upsert                      | 写库前校验目标店铺和最小 scope；失败时保留旧 token                          |
| `shop_repository.py`                 | token upsert 会替换 `scopes`                    | 使用事务完成校验后的原子替换；refresh 响应 scope 为空时不得误清空已有 scope |
| `tiktok_schemas.py`                  | 可解析 token response 中的 scope                | 增加规范化和 required/missing scope 比较工具                                |
| `tests/test_tiktok_authorization.py` | 覆盖 state 一次性和回调 upsert                  | 增加缺 scope、错店铺、state 重放、无 state、旧 token 保留测试               |
| `route-metadata.tsx` / 数据页面      | 尚无重新授权状态 UI                             | 按 ERP permission 区分提示和按钮                                            |

以上涉及新增公共 API 路由；进入实现前应先确认接口契约。当前因为 `missing_scopes=[]`，无需立即修改授权流程即可做只读数据探针。

## 8. 验收标准

当前阶段：

- [x] 当前测试店铺授权状态为 `authorized`。
- [x] 当前店铺具备 3 个最小 scope。
- [x] `missing_scopes=[]`。
- [x] 结论为“不需要重新授权”。
- [ ] 对 5 个首期 Analytics endpoint 完成只读探针。

未来 scope upgrade 实现阶段：

- [ ] 缺少 scope 时同步任务不会调用 TikTok Analytics。
- [ ] refresh token 不会被误用为 scope 升级手段。
- [ ] 重新授权严格绑定 tenant、目标店铺和一次性 state。
- [ ] 新授权缺 scope或店铺不匹配时，旧授权保持可用。
- [ ] 新 token 仅在校验通过后原子替换。
- [ ] 日志、响应和审计中无 token、code、state、签名或 App Secret。

## 9. 相关文档

- [数据能力矩阵](./data-capability-matrix.md)
- [TikTok Get Authorized Shops](https://partner.tiktokshop.com/docv2/page/get-authorized-shops-202309)
- [TikTok Shop Analytics API Reference](https://partner.tiktokshop.com/docv2/page/get-shop-video-performance-list-202509)

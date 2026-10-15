# 库存来源与店铺能力矩阵

> 核验时间：2026-09-09 15:10（Asia/Shanghai）  
> 核验方式：ERP PostgreSQL 连接记录 + TikTok Shop 最小只读 API  
> 核验范围：全部 5 家 active TikTok Shop  
> 安全边界：未输出 access token、refresh token、shop cipher、App Secret 或原始响应

## 1. 判定标准

| 能力             | 数据库证据                                                    | 真实探针                                      | 成功判定                        |
| ---------------- | ------------------------------------------------------------- | --------------------------------------------- | ------------------------------- |
| OAuth 连接       | `shop_connections.auth_status`、token 到期状态、已保存 scopes | 不主动刷新或修改 token                        | `authorized` 且 token 当前有效  |
| Seller Warehouse | `seller.logistics`                                            | `GET /logistics/202309/warehouses`            | 平台成功返回；仓库数量可以为 0  |
| FBT 开通状态     | `seller.fbt.info`                                             | `GET /fbt/202409/merchants/onboarded_regions` | 成功且 `onboarded_regions` 非空 |
| 平台库存写回     | `seller.product.write`                                        | 本次不执行写探针                              | 仅记录 scope，不证明可安全写入  |

FBT 的判定使用官方专用 onboarded-regions 接口，不使用库存数量猜测开通状态。

## 2. 逐店结果

| 店铺            | App profile | 连接 / token       | `seller.logistics` | Seller Warehouse 实测 | `seller.fbt.info` | FBT 实测   | `seller.product.write` | Gate 0 结论                                  |
| --------------- | ----------- | ------------------ | ------------------ | --------------------- | ----------------- | ---------- | ---------------------- | -------------------------------------------- |
| Akeleo Fun Toys | legacy      | authorized / valid | 已保存             | 成功，12 条仓库记录   | 已保存            | 已开通，US | 已保存                 | Seller Warehouse 与 FBT 均可进入只读接入设计 |
| Akeleo Toys     | 301         | authorized / valid | 已保存             | 成功，26 条仓库记录   | 已保存            | 已开通，US | 已保存                 | Seller Warehouse 与 FBT 均可进入只读接入设计 |
| Akeleo-Drive    | legacy      | authorized / valid | 已保存             | 成功，7 条仓库记录    | 已保存            | 已开通，US | 已保存                 | Seller Warehouse 与 FBT 均可进入只读接入设计 |
| NEOPUP          | legacy      | authorized / valid | 已保存             | 成功，2 条仓库记录    | 已保存            | 已开通，US | 已保存                 | Seller Warehouse 与 FBT 均可进入只读接入设计 |
| fanfu toy tool  | legacy      | authorized / valid | 已保存             | 成功，15 条仓库记录   | 已保存            | 已开通，US | 已保存                 | Seller Warehouse 与 FBT 均可进入只读接入设计 |

## 3. 证据 request ID

request ID 仅用于平台排障，不包含凭证。

| 店铺            | Seller Warehouse request ID          | FBT request ID                       |
| --------------- | ------------------------------------ | ------------------------------------ |
| Akeleo Fun Toys | `202609090634089BEF724B437CF422CAC9` | `202609090634094767CC77A77B0720439A` |
| Akeleo Toys     | `202609090710105EAAD139894D102BFA3A` | `20260909071018730335D38DC84C20AD01` |
| Akeleo-Drive    | `20260909063419D82EFB2DB327691F6AA8` | `202609090634201097F0D1BF0AF9201C99` |
| NEOPUP          | `20260909063422718CDB1F6C145F1FF172` | `202609090634232EB3525ED3BE91241150` |
| fanfu toy tool  | `2026090906342487ECAD47A340E41FF581` | `20260909063426058DC24A08F52023248C` |

## 4. 汇总结论

- 活跃 TikTok 店铺：5 家；
- ERP 已授权且 token 当前有效：5/5；
- 保存 `seller.logistics`：5/5；
- Seller Warehouse 真实只读探针成功：5/5；
- 保存 `seller.fbt.info`：5/5；
- FBT 已通过真实探针确认开通：5/5；
- FBT 因缺少 scope 无法核验：0/5；
- 保存 `seller.product.write`：5/5，但本次未执行任何写调用。

## 5. 库存来源决策

| 来源                    | 首期角色                | 权威性            | 是否可写       | 备注                                                |
| ----------------------- | ----------------------- | ----------------- | -------------- | --------------------------------------------------- |
| TikTok FBT              | 平台仓库存来源          | FBT 数量权威      | 否             | 保存 sellable/reserved/unsellable/in-transit 原口径 |
| TikTok Seller Warehouse | 渠道仓与渠道库存镜像    | 平台渠道口径权威  | 否             | 仓库列表已全店可读；库存字段仍需单独样本核验        |
| ERP 自有仓              | 没有 WMS 时的自有仓总账 | ERP 流水权威      | 是，受权限控制 | 期初、入库、出库、调整必须生成不可变流水            |
| 第三方 WMS              | 后续可选自有仓来源      | 接入后由 WMS 权威 | 取决于契约     | 当前没有提供 WMS 契约，不纳入首期承诺               |
| 商品表 stock            | 展示型商品同步快照      | 非库存总账        | 否             | 不用于占用、扣减或多仓合计                          |

## 6. 未决项与下一动作

### 阻断项

无。`Akeleo Toys` 已完成 301 应用的 `seller.fbt.info` 与 `seller.product.write` 重新授权；FBT 专项探针及最终标准探针均返回 `US`，新的公网 OAuth callback 也已完成真实回调验收。

### 真实样本

已完成 `Akeleo Toys` 单店只读采样：26 个 Seller Warehouse、14 条 FBT 商品 × 仓库存记录、近 365 天 2,508 条 FBT 库存流水，并核对 7 个平台 SKU 与 ERP 商品快照的映射。

样本已覆盖可售大于 0、零库存、reserved、in-transit、unfulfillable 和 SKU 映射缺失。详见 [Akeleo Toys 真实库存样本](./inventory-real-samples-akeleo-toys.md)。

样本只用于字段和数量核对；开始批量同步前仍需冻结内部 API 与数据库 schema。

## 7. 官方依据

- [Get Warehouse List](https://partner.tiktokshop.com/docv2/page/get-warehouse-list-202309)：要求 `seller.logistics`；
- [Get FBT Merchant Onboarded Regions](https://partner.tiktokshop.com/docv2/page/get-fbt-merchant-onboarded-regions-202409)：用于确认 FBT 商家注册与开通地区，要求 `seller.fbt.info`；
- [Search FBT Inventory](https://partner.tiktokshop.com/docv2/page/search-fbt-inventory-202408)：返回仓级 sellable、reserved、unsellable 和 in-transit；
- [API Versioning](https://partner.tiktokshop.com/docv2/page/api-versioning)：实施时必须复核每个 endpoint 当前支持版本。

## 8. 可复核命令

只读取数据库 scope，不调用平台：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts\audit_inventory_gate0.py --scope-only
```

执行全部店铺最小只读探针：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts\audit_inventory_gate0.py
```

该脚本只输出店铺标识、scope 布尔值、探针状态、数量汇总和 request ID，不输出凭证或原始业务记录。

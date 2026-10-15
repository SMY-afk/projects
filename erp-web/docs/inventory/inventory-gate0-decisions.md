# 库存仓储 Gate 0 决策表

> 决策日期：2026-09-09  
> 状态：业务与技术默认决策已冻结；TikTok 只读能力核验已通过  
> 逐店证据：[库存来源与店铺能力矩阵](./inventory-source-matrix.md)

## 1. Gate 0 结论

库存仓储模块可以开始 API 契约、页面原型和数据模型设计，但暂不允许开始全店 FBT 同步或平台库存写回。

`Akeleo Toys` 已完成 301 应用的 OAuth 重新授权，保存的 scope 已包含 `seller.fbt.info` 与 `seller.product.write`；真实 FBT 开通探针已稳定返回 `US`。当前 5 家 active TikTok 店铺的 Seller Warehouse 与 FBT 只读能力均已通过 Gate 0。

## 2. 决策表

| 决策项         | 最终决策                                                                                                        | 状态   | 实施约束                                                                                        |
| -------------- | --------------------------------------------------------------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------- |
| 模块名称与入口 | 顶级模块统一命名为“库存仓储”，主路由使用 `/inventory`                                                           | 已确认 | 原“平台仓”和“仓库”不再作为两个独立顶级模块                                                      |
| 库存权威来源   | FBT/平台仓以 TikTok 返回值为准；Seller Warehouse 作为渠道库存镜像；没有外部 WMS 时，自有仓以 ERP 不可变流水为准 | 已确认 | `products.stock`、`product_skus.stock` 只能作为商品同步快照，不能作为库存总账                   |
| 首期运行模式   | 平台来源只读同步；自有仓允许受权限控制的期初、入库、出库和人工调整                                              | 已确认 | 首期不调用 TikTok Update Inventory，不申请自动写回                                              |
| 跨店共享库存   | 第一期默认不共享、不跨店合计                                                                                    | 已确认 | 每次同步、查询和库存操作必须绑定明确 `tenant_id + shop_id`；共享库存另行建模和批准              |
| SKU 主键       | 新建租户级 `inventory_items.internal_sku` 作为库存主键，渠道 SKU 通过显式映射表关联                             | 已确认 | `seller_sku` 只可作为候选；冲突、空值和名称相似不得自动映射                                     |
| 订单占用时点   | 订单已支付，且状态进入 `on_hold/awaiting_shipment/awaiting_collection` 时创建占用                               | 已确认 | `unpaid` 不占用；重复同步或 Webhook 使用幂等键，不重复占用                                      |
| 取消释放时点   | 已占用订单进入 `cancelled` 时释放尚未履约的数量                                                                 | 已确认 | 已发货数量不得因整单取消被重复释放                                                              |
| 发货扣减时点   | 自有仓在平台发货回写成功或受控人工出库确认后扣减；FBT 不由 ERP 订单事件重复扣减                                 | 已确认 | 复用平台履约 outbox 的 `succeeded` 结果；打单、生成运单不等于扣减成功                           |
| 退货回补时点   | RMA 状态为 `received` 且验收结论为 `sellable` 后回补可售库存                                                    | 已确认 | 仅退款不回补；残次进入不可售库存；需要新增验收处置字段                                          |
| 负库存策略     | 默认禁止负库存                                                                                                  | 已确认 | 库存不足返回冲突并进入异常处理；不得用负数掩盖映射或同步问题                                    |
| 平台部分同步   | `partial/failed` 不推进当前完整余额                                                                             | 已确认 | 上一次完整快照继续可查，但必须显示其截至时间和当前失败状态                                      |
| 手工调整       | 仅允许自有仓，必须填写原因并记录操作者、前后值、request ID                                                      | 已确认 | 历史流水不可编辑或删除；纠错使用反向流水                                                        |
| 历史保留       | 库存流水、人工审计和对账结论长期保留；规范化快照至少保留 730 天；原始平台响应默认保留 30 天                     | 已确认 | 到期数据只能归档或按批准的保留策略清理，不能删除审计链                                          |
| FBT 入库       | 不属于第一期                                                                                                    | 已确认 | 只读取 FBT 开通、仓库、库存和变动记录；不创建入库计划                                           |
| 平台库存写回   | 不属于第一期                                                                                                    | 已确认 | 5 家店已保存 `seller.product.write`；第二期仍需验证共享库存规则、真实写探针、outbox、幂等和回滚 |

## 3. 状态触发规则

### 3.1 自有仓订单库存

```text
unpaid
  └─ 不占用

paid + on_hold/awaiting_shipment/awaiting_collection
  └─ reserve

cancelled
  └─ release remaining reservation

platform fulfillment outbox succeeded / manual outbound confirmed
  └─ fulfill reservation + decrease on-hand

RMA received + sellable
  └─ increase on-hand

RMA received + damaged/unsellable
  └─ increase unavailable only
```

### 3.2 FBT 库存

```text
FBT API / webhook
  └─ 保存 source-reported sellable/reserved/unsellable/in-transit
      └─ 完整同步后更新当前余额
      └─ 部分或失败同步仅记录证据，不覆盖当前完整余额
```

FBT 订单由平台管理履约，ERP 不根据订单状态自行推算并再次扣减 FBT 库存。

## 4. 进入下一阶段的条件

可以立即开始：

- 内部 API 契约；
- 页面低保真原型；
- 数据结构评审；
- 5 家已确认 FBT 店铺的只读适配器测试设计；
- Seller Warehouse 全店只读适配器测试设计。

开始数据库 migration 前仍需单独批准公共 schema 变更。

`Akeleo Toys` 的 FBT 接入前置条件已完成：

1. 已通过 301 应用完成包含 `seller.fbt.info` 的 OAuth 重新授权；
2. 已重新读取并保存 `granted_scopes`；
3. 已执行 FBT onboarded-regions 最小只读探针；
4. 已连续返回非空地区列表 `US`，可标记为 `onboarded`。

## 5. 不得据此推断的内容

- 保存了 scope 不等于接口实时可用；必须同时看真实探针；
- FBT 返回空库存不等于未开通，应使用 onboarded-regions 判断；
- Seller Warehouse 数量是平台返回的仓库记录数，不等于自有物理仓数量；
- 4 家店铺已开通 FBT 不代表它们共享同一个库存池；第一期禁止跨店去重或合计；
- 当前核验没有证明 SKU 映射完整，也没有证明所有仓库都有库存。

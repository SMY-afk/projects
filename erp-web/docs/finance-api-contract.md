# Finance API 口径与一期验收契约

> 冻结日期：2026-08-21  
> 状态：一期数据层、内部 API 与财务总览页面已实现  
> 目标店铺：Akeleo Fun Toys  
> 能力证据：[`tiktok-shop/finance-capability-report.md`](./tiktok-shop/finance-capability-report.md)

## 1. 一期只读范围

一期只读取和展示以下 TikTok Shop Finance 事实：

1. Statements：每日结算单及付款状态。
2. Payments：平台付款及到账核对基础信息。
3. Transactions by Statement：结算单内的订单、调整和 reserve 类交易。
4. Transactions by Order：订单与 SKU 级收入、费用、税、物流、退款和结算明细。
5. Unsettled Transactions：平台尚未结算的预计收入、费用、调整和预计结算金额。

一期允许在 ERP 内部触发显式时间窗口的同步，但不向 TikTok 写入任何财务数据。以下能力不在一期：

- Withdrawals。
- 银行流水导入、银行连接和银行自动核对。
- 人工修改 TikTok 原始交易或结算金额。
- 商品成本、经营费用、贡献利润、总账和报税。
- 跨币种换算。

## 2. 已确认的 TikTok 端点

| 能力                      | 方法与路径                                                            | 版本结论                                       |
| ------------------------- | --------------------------------------------------------------------- | ---------------------------------------------- |
| Statements                | `GET /finance/202309/statements`                                      | 当前探针通过                                   |
| Payments                  | `GET /finance/202605/payments`                                        | 必须使用 202605；202309 已于 2026-08-15 sunset |
| Transactions by Statement | `GET /finance/202501/statements/{statementId}/statement_transactions` | 当前探针通过                                   |
| Transactions by Order     | `GET /finance/202501/orders/{orderId}/statement_transactions`         | 当前探针通过并确认 SKU 明细                    |
| Unsettled Transactions    | `GET /finance/202507/orders/unsettled`                                | 当前探针通过；结果仅为预计值                   |

所有端点要求 `seller.finance.info`。浏览器不得直接请求这些端点，统一由 `erp-api` 使用现有 `TikTokTransport` 签名和调用。

## 3. 店铺、币种与时间口径

### 3.1 首个真实店铺

| 字段          | 已确认值                               |
| ------------- | -------------------------------------- |
| ERP shop ID   | `50770999-40ce-5b84-bb01-13701932bdf1` |
| 店铺          | Akeleo Fun Toys                        |
| 市场          | US                                     |
| 店铺时区      | `America/Los_Angeles`                  |
| 连接状态      | `authorized`                           |
| Finance scope | `seller.finance.info` 已授予           |

店铺展示名称可变；同步和唯一性必须继续使用租户内 ERP shop ID、平台 shop identity 和 shop cipher，不以名称作为身份。

### 3.2 币种

一期首个店铺只核算 `USD`：

- Statements、Unsettled Transactions 和 Order Transactions 的真实探针均返回 USD。
- 当前 `shops.currency` 仍为空，不能把数据库空值解释成 USD。
- Finance 同步必须从每条平台记录读取币种并持久化。
- 不同币种永不合计；出现非 USD 时按独立币种分组并触发数据质量提示。
- 所有金额使用最小货币单位整数和 ISO 4217 币种，不使用 `float`。

### 3.3 时间

- 数据库存储与内部 API 统一使用 UTC。
- 查询范围统一为左闭右开 `[from, to)`。
- Statements 按平台 `statement_time` 的 UTC 日界线获取。
- 订单和经营报表按店铺时区 `America/Los_Angeles` 生成边界，再转换为 UTC 查询。
- 前端显示店铺当地时间，但不得修改原始 UTC 值。

首个 30 天验收窗口固定为：

```text
Finance source window:
from = 2026-07-22T00:00:00Z
to   = 2026-08-21T00:00:00Z

Shop-local business window:
from = 2026-07-22T00:00:00-07:00
to   = 2026-08-21T00:00:00-07:00
```

Finance 源数据验收以 UTC 窗口为准；店铺经营报表以店铺当地完整日为准。两个窗口用途不同，不能在同一聚合中混用。

## 4. 最终值与估算值优先级

同一业务金额项只采用一个事实来源：

1. `SETTLED` 的 Order/Statement Transactions：最终结算事实，最高优先级。
2. Statements：结算单级最终汇总，用于核对交易合计。
3. Payments：现金付款状态，用于判断已付款/处理中，不替代收入或利润事实。
4. Unsettled Transactions：平台预计值，必须返回 `estimated=true`。
5. 现有 orders 金额和联盟预计佣金：Finance 数据缺失时的辅助估算，必须标记来源。
6. 无可靠来源：返回 `null/unavailable`，不得填充为看似精确的 `0`。

当一条未结算交易后续出现在结算单中时：

- 已结算版本成为当前事实。
- 未结算版本不再参与当前合计。
- 同步审计仍保留来源变化和时间，不物理伪造历史。

## 5. 30 天验收规则

完整同步实现后，先且只执行第 3.3 节的 30 天窗口。通过以下检查后，才能申请更早窗口：

1. 所有列表端点完整翻页，分页游标无循环、无遗漏。
2. 同一窗口重复同步不增加重复 statement、payment 或 transaction。
3. 每张 statement 的 transaction 结算合计与 statement 结算金额一致；任何非零差异都记录并解释。
4. Statement Transactions 中的订单型记录可以关联到现有订单；adjustment/reserve 不强制伪关联订单。
5. Order Transactions 的 SKU 明细可解析，并能关联时关联现有订单行；无法关联时保留平台 SKU 标识和质量状态。
6. `PAID`、`PROCESSING`、`FAILED` 等状态原样映射到显式内部状态，不把处理中视为已到账。
7. 未结算数据在页面、API 和导出中均带预计标识。
8. 所有金额按 USD 最小货币单位精确转换；发现其他币种时停止混合聚合。
9. 错误日志、同步记录和响应不含 token、签名、shop cipher、完整银行账号或平台原始敏感数据。
10. 用户完成 Seller Center 抽样核对并批准后，才允许执行更早历史窗口。

## 6. 已实现的 ERP 内部 API

以下端点已于 2026-08-21 在后端注册并通过真实库验收：

```text
GET  /api/finance/overview?shopId=&from=&to=&currency=&isEstimated=
GET  /api/finance/statements?page=&pageSize=&shopId=&status=&paymentStatus=&from=&to=&currency=
GET  /api/finance/statements/{statementId}
GET  /api/finance/transactions?page=&pageSize=&shopId=&statementId=&orderId=&type=&status=&isEstimated=&keyword=&from=&to=&currency=
GET  /api/finance/transactions/{transactionId}
GET  /api/finance/payments?page=&pageSize=&shopId=&status=&from=&to=&currency=
GET  /api/finance/reconciliation?shopId=&from=&to=&currency=&status=
GET  /api/finance/orders/{orderId}/summary
GET  /api/finance/export?resource=&shopId=&from=&to=&currency=
POST /api/finance/sync
```

实现约定：

- 读取与导出要求 `finance:view`；同步同时要求 `finance:view` 和 `sync:trigger`。
- `overview.items` 按币种拆分，绝不跨币种相加；列表统一返回 `items/total/page/pageSize`。
- `overview.isEstimated=true/false` 分别只聚合估算/最终交易；不传时允许混合口径并返回显式 `basis`。每个币种项的 `trend` 按 UTC 自然日返回收入、退款、费用和结算金额。
- 时间筛选为 `from` 含、`to` 不含；有值时必须带时区。金额均为整数最小货币单位。
- 交易恒等式为 `revenue + shipping + fee + adjustment = settlement`；`refund` 是 revenue 的审计拆分项，不重复相加。
- CSV 支持 `statements/transactions/payments`，复用对应列表 SQL 过滤，数据库游标分批读取，默认最多 100000 行，并防护公式注入。
- payment 与 statement 只使用可验证关联；平台未返回 statement ID 时显示孤立付款或币种差异，不按时间或金额猜测匹配。
- `backfill` 必须显式提供 `shopId/from/to`；`incremental` 可使用已提交游标计算受控滚动窗口，也可显式提供窗口。

## 7. Gate 0 结论

| 项目              | 结果                                   |
| ----------------- | -------------------------------------- |
| 一期只读范围      | 已确认                                 |
| 首店              | Akeleo Fun Toys 已确认                 |
| 币种              | USD 已由真实 Finance 响应确认          |
| 时间口径          | UTC 存储/源同步 + 店铺当地日展示已确认 |
| 最终/预计优先级   | 已确认                                 |
| Finance scope     | `seller.finance.info` 已确认           |
| 五类 Finance 端点 | 真实只读探针全部通过                   |
| 30 天窗口         | 已冻结，完整同步与对账待一期实现       |

Gate 0 已通过。下一步可以进入 Finance DTO/客户端实现；数据库 migration 和公共内部 API 仍需按计划在实施前取得批准。

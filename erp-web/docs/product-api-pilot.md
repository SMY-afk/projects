# 商品模块 API 到页面联调试点

商品模块已完成一条可复制的闭环，后续订单、库存等模块沿用同样分层。

## 契约（v1）

`GET /products` 和 `GET /products/{productId}`，请求头携带 `X-API-Contract-Version: v1`。

请求参数：

```text
page: number      // 从 1 开始
pageSize: number  // 默认 10，后端限制最大值
keyword?: string  // 匹配 name/code
status?: string   // 状态 code
```

响应 `data`：

```json
{ "items": [], "total": 0, "page": 1, "pageSize": 10 }
```

## 前端闭环

- `types/product.types.ts`：请求参数和分页响应类型。
- `api/product.api.ts`：HTTP 与 Mock 共用列表/详情类型；`VITE_USE_MOCK=false` 时仅使用 HTTP 实现，不自动回退 Mock。
- `queries/product.queries.ts`：参数进入 `productQueryKeys.list(params)`，详情使用包含 `productId` 的独立 key，避免筛选、分页和详情串缓存。
- `pages/product-list-page.tsx`：维护分页、关键词和状态，统一处理 loading/error/retry。
- `pages/product-detail-page.tsx`：按 `productId` 查询真实详情并展示 SKU，处理 loading、404、403、error/retry。
- `components/product-list.tsx` 与 `ErpListPage`：服务端分页回调、搜索和筛选回调；权限码为 `products:view`、`products:delete`。
- 测试最小闭环：查询 Hook 成功/失败、路由权限、页面状态和必要的 Playwright 商品入口。

## 联调步骤

1. 将 `VITE_USE_MOCK=false`，配置 staging API 地址和 `VITE_API_CONTRACT_VERSION=v1`。
2. 使用有/无 `products:view` 权限的账号验证路由与导航。
3. 验证第一页、切换页码/页大小、关键词、状态筛选和空结果；确认请求参数与响应 `page/total` 一致。
4. 验证商品详情、SKU 明细、404、403、error/retry，以及返回列表后保留筛选和分页状态。
5. 用网络面板确认商品模块只请求 ERP `/api/products`；错误响应可被统一 `HttpError` 解析，且页面不展示 Mock 数据。
6. 通过后端确认清单逐项签字，再复制目录和契约模式到下一个模块。

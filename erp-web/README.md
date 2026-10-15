# ERP Web

基于 Vite、React 和 TypeScript 的 ERP 前端。认证、Dashboard、商品、订单和数据板块均具备真实 `erp-api` 接口实现；Mock 只用于显式离线开发。库存及部分扩展模块继续显示占位页。

唯一后端是同级目录 [`../erp-api`](../erp-api/README.md)。浏览器只访问 ERP 内部 `/api`，TikTok Shop 密钥、店铺 Token、数据库和 Redis 均由后端持有。

## 技术栈

- React 19 + TypeScript
- Vite 8
- React Router
- Ant Design
- TanStack Query（服务端状态）
- Axios（HTTP 客户端）
- ECharts、Day.js

## 本地启动

要求：Node.js 20 或更高版本，npm 10 或更高版本。

```bash
npm install
npm run dev
```

开发服务器默认运行在 Vite 输出的本地地址。仪表盘可通过 `/` 或 `/dashboard` 访问。

## 常用命令

```bash
# 启动开发服务器
npm run dev

# 执行 ESLint 检查
npm run lint

# 执行格式、ESLint、Vitest 和生产构建
npm run quality

# 在真实 erp-api 和隔离测试租户上执行完整发布检查
npm run release:check

# TypeScript 类型检查并构建生产包
npm run build

# 本地预览生产构建
npm run preview
```

## 环境变量

复制 `.env.example` 为 `.env.development.local`，再填写本地接口地址：

```bash
Copy-Item .env.example .env.development.local
```

| 变量                | 说明                | 示例                        |
| ------------------- | ------------------- | --------------------------- |
| `VITE_API_BASE_URL` | 后端 API 的基础地址 | `http://localhost:8080/api` |

关闭 `VITE_USE_MOCK` 后，各业务模块只有在对应变量明确为 `false` 时才请求真实 API。仓库中的 `.env.example` 是分阶段本地默认值；CI/发布检查会显式将认证和订单切到真实模式：

```dotenv
VITE_USE_MOCK=false
VITE_AUTH_USE_MOCK=true
VITE_PRODUCTS_USE_MOCK=false
VITE_ORDERS_USE_MOCK=true
VITE_DASHBOARD_USE_MOCK=false
VITE_INVENTORY_USE_MOCK=true
VITE_DATA_USE_MOCK=false
```

本地全真实认证和订单联调可将 `VITE_AUTH_USE_MOCK=false`、`VITE_ORDERS_USE_MOCK=false`。Playwright 不读取或硬编码真实账号密码，而由测试前置脚本在独立测试租户创建短期会话和固定订单，结束后清理。

只有以 `VITE_` 开头的变量会暴露给浏览器。请勿将密钥、数据库密码或私有 Token 放入任何 Vite 环境文件。

## 目录说明

```text
src/
  app/              # 应用级 Provider、Query Client 与全局初始化
  assets/           # 图片、字体等静态资源
  features/         # Dashboard、商品、订单、数据等领域模块
  layouts/          # 登录后布局、顶部栏和页签
  pages/            # 登录及通用路由页面
  router/           # 路由表与路由守卫
  services/         # Axios、认证、Mock 切换和观测
  shared/           # 通用组件、类型、常量和工具函数
  App.tsx           # 根路由出口，不放业务页面
  main.tsx          # React 应用启动入口
```

## 命名与代码约定

### 文件与目录

- 目录名和非组件文件使用 `kebab-case`，例如 `dashboard-page.tsx`、`query-client.ts`。
- React 组件导出名使用 `PascalCase`，例如 `DashboardPage`、`OrderTable`。
- 仅当一个文件只导出一个主组件时，组件文件也可以使用 `PascalCase`，例如 `OrderTable.tsx`；页面、Hook、工具与配置文件仍优先采用 `kebab-case`。
- Hook 以 `use` 开头，例如 `use-order-list.ts` 中导出 `useOrderList`。
- 测试文件与被测文件同名，附加 `.test` 或 `.spec`，例如 `client.test.ts`。

### 业务领域分层

业务相关的接口、类型、查询 Hook 和组件必须按领域放入 `features`，而不是按技术类型散落在全局目录：

```text
src/features/orders/
  order.api.ts          # 订单接口请求
  order.types.ts        # 订单领域类型
  order.queries.ts      # TanStack Query Hooks 与查询键
  order-table.tsx       # 订单领域组件
```

- 跨领域的 HTTP 实现放在 `services/http`。
- 可被任意模块复用的类型、组件、常量放在 `shared`。
- `pages` 只负责路由页面编排；复杂业务逻辑应沉入 `features`。

### TypeScript

- 接口、类型、枚举使用 `PascalCase`，例如 `Order`、`PageResult`、`OrderStatus`。
- API 类型以业务对象命名；请求和响应后缀清晰表达用途，例如 `OrderListParams`、`CreateOrderPayload`。
- 不使用 `any`；无法确定的第三方数据应使用 `unknown` 后再收窄类型。
- TypeScript 模块可使用 `@/` 指向 `src`，例如 `import { AppProviders } from '@/app/app-providers'`；样式与同目录私有文件可保留相对路径。

## 编码与格式

- 所有文本源文件必须为 UTF-8。
- 使用 2 个空格缩进、LF 换行，并在文件末尾保留换行。
- 提交前运行 `npm run quality`；发布前在 PostgreSQL、Redis 和 `erp-api` 就绪后运行 `npm run release:check`。

## 当前路由

| 路径                                | 页面                 | 当前状态                                        |
| ----------------------------------- | -------------------- | ----------------------------------------------- |
| `/login`                            | 登录                 | Mock/真实 API 可切换                            |
| `/dashboard`                        | 运营仪表盘           | 真实 API 已接入                                 |
| `/products`、`/products/:productId` | 商品列表/详情        | 真实 API 已接入                                 |
| `/orders`、`/orders/:orderId`       | 订单列表/详情        | 真实 API 已接入，发布 E2E 使用固定测试 DTO      |
| `/data`                             | 视频、直播和同步健康 | 真实 API，按 `placeholder/test/single/all` 灰度 |
| `/warehouse` 等                     | 扩展模块             | 明确占位，不读取假数据                          |

## 方案文档状态

`docs/*plan.md` 保留为历史决策和验收边界，不再作为当前目录或完成度的唯一事实来源。当前运行状态以本 README、[`../erp-api/README.md`](../erp-api/README.md) 和 [`docs/tiktok-shop/data-development-status.md`](docs/tiktok-shop/data-development-status.md) 为准。

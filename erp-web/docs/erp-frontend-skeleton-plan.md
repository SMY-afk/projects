# ERP 前端项目骨架建设计划书

> 状态：已完成并归档（更新于 2026-08-19）。本文描述的是建设前基线，目录、路由、认证、质量门禁和业务模块均已演进；当前结构以 `erp-web/README.md` 为准。

## 1. 项目识别与当前完成度

### 1.1 当前项目定位

这是一个基于 **Vite + React 19 + TypeScript** 的 ERP Web 前端原型。现有页面以运营仪表盘为主题，使用 Ant Design 图标和自定义 CSS 完成了静态视觉展示。

### 1.2 当前已有能力

- 构建与开发：Vite、TypeScript、ESLint 已可用。
- UI 基础：Ant Design、`@ant-design/icons`、ECharts、Day.js 已安装。
- 前端路由：已安装 `react-router`，当前仅有 `/` 与占位的 `/dashboard`。
- 服务端状态依赖：`@tanstack/react-query` 与 Axios 已安装，但未初始化或使用。
- 原型页面：`src/App.tsx` 包含一个硬编码的仪表盘视觉稿。

### 1.3 距离“ERP 前端项目骨架”的主要缺口

1. 没有明确的目录分层和模块边界，所有界面集中在 `App.tsx`。
2. 没有可复用的应用壳（侧边导航、顶栏、内容区、面包屑、页签）。
3. 没有受控路由、路由元数据、懒加载和 404 页面。
4. Axios 和 TanStack Query 尚未配置；没有 API 类型、错误处理或请求鉴权策略。
5. 没有登录态、用户信息、权限模型和菜单过滤机制。
6. 没有业务领域模型、Mock 数据策略与列表页通用能力。
7. 未建立环境变量、质量检查、测试和交付约定。

---

## 2. 建设目标与建议范围

本轮骨架建设的目标不是完成所有 ERP 功能，而是建立可持续扩展的基础：

- 能登录（可先 Mock），根据权限进入系统；
- 有统一布局、导航、路由、主题和全局反馈；
- 新增一个业务模块时具备固定模板（页面、API、类型、查询 Hook）；
- 数据请求、缓存、错误、鉴权与分页有统一约定；
- 先落地“仪表盘、商品、订单、库存、系统设置”五个模块的入口与占位页。

建议暂不在骨架阶段实现复杂的工作流、实时通信、报表拖拽、国际化或多租户隔离；应在后端接口和业务规则明确后单独规划。

---

## 3. 分阶段执行步骤

## 阶段 0：整理现有原型并确定技术约定

### 要做什么

1. 将当前 `App.tsx` 的静态仪表盘内容迁移为独立的仪表盘页面，保留现有视觉成果。
2. 修复源文件中的乱码文本，统一源文件保存编码为 UTF-8。
3. 确定命名约定：组件使用 PascalCase，目录与普通文件使用 kebab-case，接口和类型以业务领域划分。
4. 将 Vite 模板 README 替换为项目 README，记录启动、构建、环境变量和目录说明。

### 涉及文件

- 修改：`src/App.tsx`、`src/App.css`、`src/brand.css`、`README.md`
- 新增：`src/pages/dashboard/dashboard-page.tsx`、`src/pages/dashboard/dashboard-page.css`
- 新增：`.editorconfig`（建议）

### 依赖和数据结构

- 无新增运行时依赖。
- 将页面内硬编码指标抽为最小展示类型：

```ts
interface DashboardMetric {
  label: string
  value: string | number
  comparison?: string
  changeRate?: number
}
```

### 验收标准

- 页面视觉不回退；首页能正常渲染；文本显示正常；`npm run lint` 和 `npm run build` 通过。

## 阶段 1：建立目录结构与应用入口

### 要做什么

1. 将根组件改为只承载 Provider 与路由出口，移除业务页面内容。
2. 建立 `app`、`layouts`、`pages`、`features`、`services`、`shared` 六层目录。
3. 建立统一的 `AppProviders`，集中挂载 Query、Ant Design ConfigProvider、通知组件等全局能力。
4. 建立别名 `@/`，减少跨目录相对路径。

### 涉及文件

- 修改：`src/main.tsx`、`src/App.tsx`、`vite.config.ts`、`tsconfig.app.json`
- 新增：`src/app/app-providers.tsx`、`src/app/query-client.ts`
- 新增：`src/layouts/basic-layout/basic-layout.tsx`
- 新增：`src/shared/types/common.ts`、`src/shared/utils/index.ts`

### 依赖和数据结构

- 使用已安装的 `@tanstack/react-query` 和 `antd`。
- 推荐的目录关系：

```text
src/
  app/          # 全局 Provider、配置、应用启动
  layouts/      # 登录后页面框架
  pages/        # 路由页面，仅负责页面组合
  features/     # 按业务域拆分的可复用业务能力
  services/     # HTTP 客户端与业务 API
  shared/       # 通用组件、常量、类型、工具函数
```

- 建议通用分页结构：

```ts
interface PageParams {
  page: number
  pageSize: number
}
interface PageResult<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}
```

### 验收标准

- `main.tsx` 中只有启动、Provider 与路由；页面内容不再堆在根组件；可通过 `@/` 引用模块。

## 阶段 2：搭建 ERP 应用壳与设计基础

### 要做什么

1. 使用 Ant Design Layout/Menu 建立顶栏、侧边栏、内容区、面包屑和可选页签栏。
2. 建立菜单与路由元数据的单一来源，避免导航与路由各自维护。
3. 配置 Ant Design 主题 Token（主色、圆角、布局色、字号），将目前的定制样式逐步收敛。
4. 提供全局加载、空状态、错误状态和无权限页面。

### 涉及文件

- 新增：`src/layouts/basic-layout/sidebar.tsx`、`src/layouts/basic-layout/header.tsx`
- 新增：`src/layouts/basic-layout/breadcrumbs.tsx`、`src/layouts/basic-layout/basic-layout.module.css`
- 新增：`src/app/theme.ts`、`src/shared/components/page-container/page-container.tsx`
- 新增：`src/pages/error/not-found-page.tsx`、`src/pages/error/forbidden-page.tsx`

### 依赖和数据结构

- 依赖：已安装的 `antd` 与 `@ant-design/icons`。
- 菜单/路由元数据建议：

```ts
interface AppRoute {
  path: string
  label: string
  icon?: React.ReactNode
  permission?: string
  children?: AppRoute[]
}
```

### 验收标准

- 从任意业务页可通过菜单切换模块；刷新当前 URL 后页面正确恢复；404、403 和加载状态有统一呈现。

## 阶段 3：完善路由、登录态与权限模型

### 要做什么

1. 定义公开路由、受保护路由与权限守卫。
2. 新建登录页，先使用 Mock 登录流程；后续只替换 API 实现。
3. 登录成功后获取用户信息、角色和权限点；由权限过滤菜单和页面访问。
4. 将 Token 存储策略、退出登录、401 自动跳转写成统一规范。

### 涉及文件

- 修改：`src/router/index.tsx`
- 新增：`src/router/route-guard.tsx`、`src/router/routes.tsx`
- 新增：`src/pages/auth/login-page.tsx`
- 新增：`src/features/auth/auth-store.ts`、`src/features/auth/auth.types.ts`
- 新增：`src/services/auth/auth.api.ts`

### 依赖和数据结构

- 优先使用 React Context 管理小规模会话状态；如后续跨页面客户端状态复杂，再引入 Zustand，骨架阶段不必预装。
- 会话数据建议：

```ts
interface CurrentUser {
  id: string
  name: string
  avatarUrl?: string
  roles: string[]
  permissions: string[]
}

interface AuthSession {
  accessToken: string
  refreshToken?: string
  user: CurrentUser
}
```

### 验收标准

- 未登录访问业务路径会进入登录页；无权限访问显示 403；权限变化可反映在菜单中。

## 阶段 4：配置 Axios、TanStack Query 与接口契约

### 要做什么

1. 创建唯一 Axios 实例，配置 `baseURL`、超时、请求/响应拦截器和错误标准化。
2. 创建 QueryClient，设定全局缓存时间、重试规则和窗口聚焦刷新策略。
3. 规范服务端响应解包、接口错误类型、请求取消和文件上传下载。
4. 让每个业务 API 配套 TypeScript 类型和 Query/Mutation Hook；页面不直接调用 Axios。
5. 增加 `.env.development`、`.env.production`，API 地址不写死在代码中。

### 涉及文件

- 新增：`src/services/http/client.ts`、`src/services/http/errors.ts`
- 新增：`src/services/http/response.ts`、`src/services/http/query-keys.ts`
- 新增：`src/features/dashboard/dashboard.api.ts`、`src/features/dashboard/dashboard.queries.ts`
- 新增：`.env.example`、`.env.development`（真实地址仅由本地环境维护）
- 修改：`src/app/query-client.ts`、`src/app/app-providers.tsx`

### 依赖和数据结构

- 使用已安装的 `axios`、`@tanstack/react-query`。
- 后端应确认统一响应协议；建议前端按以下模型适配：

```ts
interface ApiResponse<T> {
  code: number
  message: string
  data: T
  traceId?: string
}

interface ApiError {
  code: string | number
  message: string
  details?: Record<string, string[]>
  traceId?: string
}
```

### 验收标准

- 任一页面可通过 Hook 加载数据；加载、接口失败和重新请求有统一行为；Token 自动附带；401 可退出或刷新会话。

## 阶段 5：建立业务模块模板并落地首批模块

### 要做什么

1. 创建模块模板：`types`、`api`、`queries`、`components`、`pages` 五部分。
2. 将现有视觉稿接入仪表盘模块，初期可由 Mock 数据驱动。
3. 建立商品、订单、库存、系统设置的入口、列表页骨架和详情页路由。
4. 抽取 ERP 通用列表能力：筛选栏、分页表格、批量操作区、详情抽屉和操作权限控制。

### 涉及文件

- 新增：`src/features/dashboard/*`、`src/pages/dashboard/dashboard-page.tsx`
- 新增：`src/features/products/*`、`src/pages/products/product-list-page.tsx`
- 新增：`src/features/orders/*`、`src/pages/orders/order-list-page.tsx`
- 新增：`src/features/inventory/*`、`src/pages/inventory/inventory-list-page.tsx`
- 新增：`src/pages/settings/settings-page.tsx`
- 新增：`src/shared/components/data-table/*`、`src/shared/components/search-form/*`

### 依赖和数据结构

- 基础组件仍使用 Ant Design Table、Form、Drawer、Pagination。
- 第一批领域结构建议：

```ts
interface Product {
  id: string
  sku: string
  name: string
  status: 'active' | 'inactive'
  stock: number
  updatedAt: string
}

interface Order {
  id: string
  orderNo: string
  status: 'pending' | 'paid' | 'shipped' | 'completed' | 'cancelled'
  customerName: string
  totalAmount: number
  currency: string
  createdAt: string
}

interface InventoryItem {
  id: string
  sku: string
  warehouseId: string
  availableQuantity: number
  reservedQuantity: number
  inTransitQuantity: number
}
```

### 验收标准

- 五个模块均有可访问入口；列表页拥有筛选、加载、空状态、分页和错误处理；更换真实接口无需修改页面结构。

## 阶段 6：Mock、开发联调与质量保障

### 要做什么

1. 在后端未就绪时建立可切换的 Mock 层，覆盖登录、仪表盘、商品、订单和库存列表。
2. 配置开发环境 API 代理，解决本地联调的跨域问题。
3. 加强 ESLint 类型检查，补充格式化工具与提交前检查。
4. 为 HTTP 客户端、权限守卫、关键查询 Hook 编写单元测试；为登录与订单列表保留端到端测试入口。
5. 建立错误上报、性能指标和发布环境变量的接入位（具体服务由团队选择）。

### 涉及文件

- 修改：`vite.config.ts`、`eslint.config.js`、`package.json`
- 新增：`src/mocks/*`、`src/test/*`、`src/services/http/client.test.ts`
- 新增：`vitest.config.ts`（选用 Vitest 时）
- 新增：`.env.test`

### 依赖和数据结构

- 建议新增：`msw`（API Mock）、`vitest`、`@testing-library/react`、`@testing-library/user-event`。
- 可选新增：`@tanstack/react-query-devtools`，仅开发环境挂载。
- Mock 数据使用与业务接口相同的 TypeScript 类型，避免两套数据模型漂移。

### 验收标准

- 后端不可用时，开发者可启用 Mock 完整走通主流程；`lint`、类型检查、构建、核心测试可在 CI 中运行。

## 阶段 7：交付规范与后续迭代机制

### 要做什么

1. 定义环境变量清单、接口契约版本、分支策略和发布流程。
2. 编写“新增 ERP 模块”开发指南，包括路由、权限、API、查询 Hook、页面与测试的最小清单。
3. 与后端确认接口错误码、分页、金额与时区格式、权限返回格式、文件上传下载和字典枚举接口。
4. 以商品或订单模块为试点完成一次从 API 契约到页面联调的闭环，再复制到后续模块。

### 涉及文件

- 新增：`docs/architecture.md`、`docs/api-conventions.md`、`docs/new-module-guide.md`
- 修改：`README.md`、`.env.example`

### 依赖和数据结构

- 无必需新增依赖。
- 需要后端提供或共同确认：字典项、用户权限、分页响应、错误码、时间与金额精度规则。

### 验收标准

- 新成员可按照文档新增一个列表模块；前后端对响应协议、字段命名和错误处理达成一致。

---

## 4. 推荐实施顺序与依赖关系

```text
阶段 0（整理原型）
  -> 阶段 1（目录与应用入口）
    -> 阶段 2（应用壳与路由元数据）
      -> 阶段 3（登录与权限）
      -> 阶段 4（HTTP 与服务端状态）
        -> 阶段 5（业务模块模板）
          -> 阶段 6（Mock、联调与测试）
            -> 阶段 7（文档与交付）
```

阶段 3 和阶段 4 可并行推进，但必须在阶段 5 前完成。若后端接口尚未确定，阶段 4 先实现客户端、响应适配和 Mock，再在接口评审后补齐实际业务 API。

---

## 5. 当前最值得优先执行的最小闭环

建议第一轮按以下顺序完成：

1. 阶段 0：将当前仪表盘从根组件迁出并修复乱码。
2. 阶段 1 与 2：完成目录、Provider、应用壳和受控路由。
3. 阶段 4：配置 Axios + TanStack Query，并用 Mock 驱动仪表盘。
4. 阶段 3：接入登录/权限的 Mock 流程。
5. 阶段 5：先完成“订单列表”作为标准业务模块样板。

完成这五项后，项目即具备 ERP 前端骨架：可导航、可鉴权、可请求、可缓存、可按同一模式扩展业务模块。

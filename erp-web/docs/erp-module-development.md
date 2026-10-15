# 新增 ERP 模块开发指南

一个模块必须形成“路由、权限、API、查询 Hook、页面、测试”最小闭环。推荐目录：

```text
src/features/<module>/
  api/<module>.api.ts
  types/<module>.types.ts
  queries/<module>.queries.ts
  queries/<module>.queries.test.tsx
  pages/<module>-list-page.tsx
  pages/<module>-detail-page.tsx
  components/<module>-list.tsx
```

## 最小清单

1. **类型与契约**：定义实体、列表/详情响应和查询参数；写清方法、路径、权限码、错误码；页面不得直接调用 Axios。
2. **API/Mock**：在 `api/` 同时提供 HTTP 与 Mock 实现，通过 `isMockEnabled` 导出统一 API；Mock 覆盖正常、空列表和错误数据形状。
3. **查询 Hook**：在 `queries/` 定义稳定的 `moduleQueryKeys`（至少 `all`、`list`），用 `useQuery`/`useMutation` 封装 API；筛选、分页、详情参数必须进入 query key。
4. **路由**：在 `src/router/route-metadata.tsx` 注册列表/详情路由，填写 `key`、`path`、`element`、`permissions`；列表导航需要 `showInTopNav: true`。
5. **权限**：使用 `<module>:view/create/edit/delete` 命名；路由由 `RequireAuth`、`RequirePermission` 保护，按钮仍需做操作级权限控制。
6. **页面**：列表页只编排查询状态，覆盖 loading（`PageLoading`）、error/retry（`PageError`）、empty 和正常数据；列表组件负责列、筛选、搜索、详情入口，优先复用 `ErpListPage`。
7. **测试**：Hook 测试成功映射、query key 和失败态；路由测试未登录到 `/login`、无权限到 `/403`、有权限可渲染；页面测试 loading/error/empty/正常数据；关键路径补 `tests/e2e/<module>.spec.ts`。

## 交付检查表

- [ ] 类型、API/Mock、query key 和 Hook
- [ ] 路由、导航和权限码
- [ ] loading、error、empty、正常数据状态
- [ ] Hook、权限、页面及必要 E2E 测试
- [ ] 契约版本和环境变量说明
- [ ] PR 描述包含截图、权限影响、API 变更和回滚方式

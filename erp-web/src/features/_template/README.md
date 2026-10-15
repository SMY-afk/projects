# 业务模块模板

复制此目录并以领域名称替换 `_template`。

```text
feature-name/
  types/        # 领域实体、请求与响应类型
  api/          # 类型化 API 调用
  queries/      # Query Key 和 Query/Mutation Hook
  components/   # 可复用业务组件
  pages/        # 路由页面编排，不直接调用 HTTP 客户端
```

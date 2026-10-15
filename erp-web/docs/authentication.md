# 认证与授权规范

## 登录与会话

1. 登录接口只返回短期 `accessToken`；登录成功后，前端立即调用“当前用户”接口获取用户信息、角色和权限点。
2. `accessToken` 是唯一允许写入浏览器存储的认证数据，使用 `sessionStorage` 保存；关闭浏览器标签页后自动失效。用户信息、角色和权限点不做持久化，每次启动应用都重新请求。
3. 所有 HTTP 请求由 `src/services/http-client.ts` 统一注入 `Authorization: Bearer <accessToken>`。

## 退出与失效

1. 主动退出调用认证服务的 `logout`，无论请求结果如何都清除本地 Token 和内存中的用户状态。
2. HTTP 客户端收到 401 时，统一清除 Token 并广播 `auth:unauthorized`；认证上下文清空用户状态，受保护路由自动跳转 `/login`。
3. 登录守卫会保存用户原始访问地址，重新登录成功后返回该地址。

## 授权

1. 路由在 `route-metadata.tsx` 声明所需权限点；`RequirePermission` 负责页面访问校验。
2. 菜单复用同一份路由权限元数据进行过滤，避免菜单与页面授权规则不一致。

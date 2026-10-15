# ERP 源码

此仓库保存经过敏感信息排除和配置脱敏的源码快照，包含前端、后端、数据库模型、迁移脚本及测试。

## 目录

- `erp-web/`：React、TypeScript、Vite 前端。
- `erp-api/src/erp_api/`：FastAPI API、认证、权限、业务服务和任务处理。
- `erp-api/migrations/`：数据库表结构迁移与必要的系统权限初始化。
- `erp-api/backend/`、`erp-api/app/`、`backend/`：采集、解析及辅助模块。
- `erp-api/scripts/`：运行与维护工具；使用前需配置自己的资源标识和凭据。

## 发布范围

真实 `.env`、API 密钥、数据库数据、运营导出、备份、运行日志、Cookie、登录会话及 HubStudio 实例配置均不包含在此快照中。源码内出现的实际租户、店铺、飞书资源等标识已替换为示例值；部署前必须配置自己的有效资源。

环境变量模板只用于说明配置名称。请在本地建立忽略的环境文件，或通过部署平台的密钥管理设施注入凭据。不要把飞书、TikTok、AI API 或数据库凭据放进 `VITE_*` 变量。

## 认证实现

当前 ERP 登录使用用户名和密码，后端通过 PBKDF2-SHA256 校验密码，在 Redis 保存随机 Bearer 会话令牌。前端只在 `sessionStorage` 保存访问令牌，通过当前用户接口获取角色与权限。默认会话空闲超时为 7200 秒，成功校验会话时续期；退出会撤销服务器会话。

TikTok OAuth 的店铺令牌是另一套凭据，使用 AES-256-GCM 加密保存。内部采集与导出接口使用独立的服务令牌。详细实现见 `erp-api/src/erp_api/routers/auth.py`、`erp-api/src/erp_api/services/auth.py` 和 `erp-web/src/auth/`。

`erp-web/docs/` 包含不同阶段的设计文档；当前行为以源码及对应测试为准。

## 验证范围

发布准备执行 Python 源码语法检查、密钥模式扫描、已知本地凭据匹配检查及禁止文件类型检查。运行系统需要单独安装依赖、配置 PostgreSQL/Redis 和外部平台授权。

本次原始工作区的前端认证相关测试通过 24 项，后端权限依赖测试通过 30 项。后端登录与 TikTok 授权路由测试因原始本地 Python 环境缺失 `asyncpg.connection` 未能完成；这不代表生产运行验证。

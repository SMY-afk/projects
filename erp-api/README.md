# ERP API

ERP 唯一后端服务，负责内部 FastAPI、PostgreSQL 持久化、Redis 短期状态、ARQ 同步任务，以及 TikTok Shop OAuth、数据同步和 Webhook 处理。`erp-web` 只调用本服务的内部 `/api`，不得持有平台密钥或直接请求 TikTok Shop。

## 项目边界

- 唯一后端目录：`D:\codex\projects\erp-api`；
- 应用入口：`src/erp_api/main.py`，本地统一使用
  `.\.venv\Scripts\python.exe -m erp_api` 启动；
- 数据库变更仅通过 `migrations/` 中的 Alembic migration；
- `D:\codex\projects\backend` 是已审计的早期原型残片，不是可运行服务；
- `backend/` 和 `app/parsers/` 是本项目内部的 Seller Center 抓取辅助命名空间，仍有回归测试引用，不是第二个后端，也不得未经迁移直接删除。

残片逐文件比对及删除申请范围见 [`../BACKEND_RESIDUE_AUDIT_2026-08-19.md`](../BACKEND_RESIDUE_AUDIT_2026-08-19.md)。

## 数据库迁移

已配置 SQLAlchemy 异步 engine、请求级 tenant session 和 Alembic 异步迁移框架。当前 migration 已覆盖身份权限、店铺连接、商品/SKU、订单/履约/收件信息、联盟证据、订单归因、Analytics 快照、同步运行和质量告警。库存模块继续留白，不创建库存表或伪造数据。

```powershell
# 应用已确认的迁移
.\.venv\Scripts\python.exe -m alembic upgrade head

# 仅在数据模型和 schema 变更获得确认后执行
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe schema change"
```

## 已包含

- FastAPI 应用与 `/api/health`、`/healthz`、`/readyz` 健康检查；
- Pydantic Settings 配置边界；
- 受控 CORS、请求 ID、统一错误响应与 JSON 结构化日志；
- PostgreSQL 与 Redis 的异步连通性探针；
- 服务端 CAPTCHA、Redis 短期会话、角色权限和租户隔离；
- TikTok Shop OAuth、连接管理、签名传输、Webhook、限流和安全错误映射；
- 商品、订单、联盟证据、订单归因和 Dashboard 的内部 API；
- Analytics 快照、视频/直播数据、同步状态、质量告警与灰度读取；
- ARQ 商品、订单和 Analytics 同步任务；
- Docker Compose 本地 PostgreSQL、Redis 与 API 编排。

## 飞书定时任务与事件回调

- 样品表的人工字段变更由 `POST /api/v1/webhooks/feishu/sample-applications` 接收 `drive.file.bitable_record_changed_v1`；回调验证签名、Verification Token 和 Base/Table 身份，支持加密事件体。飞书开放平台需订阅该事件并配置回调 URL，运行环境需设置 `FEISHU_EVENT_VERIFICATION_TOKEN` 和 `FEISHU_EVENT_ENCRYPT_KEY`。未配置时事件入口不会处理业务事件。
- 开启 `FEISHU_SAMPLE_REVERSE_POLL_ENABLED` 后，样品表全量回读是独立兜底任务，默认每 60 分钟一次，由 `FEISHU_SAMPLE_REVERSE_POLL_INTERVAL_MINUTES` 调整。五分钟一次的 TikTok 活跃样品同步不再触发飞书全表扫描。回调未启用时，人工编辑需等到下一个成功的回读周期。
- 分配汇总每 60 秒检查 Redis 变更版本；分配记录写入或对应飞书事件会触发下一轮同步，无变更时直到 Compose 设置的 900 秒兜底周期才读取飞书。汇总数值未变化时不批量写回飞书。AI 邀约镜像仍按小时校对，其保护判断直接读取源表。

## 目录

```text
src/erp_api/     # 唯一可安装应用包：routers、services、models、workers
migrations/      # Alembic migration
tests/           # API、服务、模型、仓储和契约回归
scripts/         # 初始化、安全检查和受控运维脚本
app/parsers/     # 待迁入 src/erp_api 的抓取解析辅助代码
backend/         # 待迁入 src/erp_api 的 Seller Center 抓取辅助代码
runtime/         # 本地日志和截图，已忽略，不属于源码
```

## 环境与密钥

开发、测试、生产使用互不提交的环境文件；仅提交不含真实值的 `*.example` 模板。

```powershell
# 开发环境：首次执行
Copy-Item .env.development.example .env.development

# 测试环境：需要独立服务时执行
Copy-Item .env.test.example .env.test
$env:APP_ENV = "test"
```

应用根据进程的 `APP_ENV` 选择 `.env.development` 或 `.env.test`。生产环境必须由部署平台的 Secret Manager 或 CI 受保护变量注入 `DATABASE_URL`、`REDIS_URL` 和 TikTok 密钥；禁止创建或上传 `.env.production`。

`.env.example` 只列变量名和示例占位符，不包含可用凭据。`TIKTOK_APP_SECRET`、
`TIKTOK_TOKEN_ENCRYPTION_KEY`、数据库密码及任何未来可能引入的 JWT 密钥只能存在于
后端运行环境或密钥管理服务中，绝不能使用 `VITE_*` 前缀。当前认证使用 Redis 中的
随机会话令牌，不使用 JWT，因此不配置无效的 JWT 密钥变量。

提交前安装 Git 钩子（当前目录必须已初始化为 Git 仓库）：

```powershell
.\scripts\install-git-hooks.ps1
```

钩子会拒绝暂存 `.env*` 文件和高置信度凭据模式；CI 应执行：

```powershell
.\.venv\Scripts\python.exe scripts\check_no_secrets.py
```

## 本地运行

需要 Python 3.12+ 和 Docker Desktop。本地 Python 命令不得依赖已激活的 shell，统一显式调用
项目 `.venv`；Docker 镜像使用容器内独立的 `/opt/venv`。

```powershell
Copy-Item .env.development.example .env.development
# 编辑 .env.development，至少替换 POSTGRES_PASSWORD 与 DATABASE_URL 中的同一密码
docker compose --env-file .env.development up --build
```

服务启动后可访问：

- `http://localhost:8080/healthz`
- `http://localhost:8080/api/health`
- `http://localhost:8080/readyz`
- `http://localhost:8080/docs`

仅运行 API（数据库和 Redis 已由其他方式启动）时：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\start-api.ps1

# 另一个终端启动 ARQ Worker
.\scripts\start-worker.ps1

.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

## 质量与发布检查

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.venv\Scripts\python.exe -m compileall -q src migrations scripts app backend
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe scripts\check_no_secrets.py --all
```

`runtime/` 和 `*.log` 只保存本地运行产物，已加入 `.gitignore`。测试或命令失败时不得用 Mock 或旧残片静默兜底。

## 初始化管理员

数据库迁移完成后，执行幂等引导脚本创建默认租户、全部权限、管理员角色和管理员账号：

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_admin.py
```

未提供 `INITIAL_ADMIN_PASSWORD` 时，脚本生成强随机密码并保存到 Git 已忽略的
`secrets/local-admin-credentials.txt`，终端不会输出密码。重复执行不会重复创建记录；需要
显式重置已有管理员密码时，先通过受保护的环境变量提供新密码，再使用
`--reset-password`。

`CORS_ORIGINS` 使用逗号分隔的精确来源列表，例如
`http://localhost:5173,https://dev.example.com`。启用凭据时禁止配置 `*`。

## 临时 HTTPS 回调

Cloudflare Tunnel 仅转发 API 服务，不转发前端开发服务器：

```powershell
cloudflared tunnel --url http://localhost:8080
```

临时地址重启后会变化，只用于一次性联调。连续开发应使用命名 Tunnel 与团队控制的开发子域名，并将 TikTok Shop 回调配置为：

```text
https://<dev-domain>/api/v1/shops/tiktok/callback
https://<dev-domain>/api/v1/webhooks/tiktok
```

在 OAuth `state`、令牌交换和 Webhook 签名校验完成前，不要将这些占位路由配置到生产店铺。

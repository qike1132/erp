# 滨发协同系统（binfa-erp）

滨发协同系统是一套面向内网部署的生产 ERP，覆盖采购、客户订单、库存、出货计划、生产、板房、审批、备份和系统管理。项目包含 FastAPI 后端、Vue 3 PC/移动端前端、PostgreSQL 数据库与 Redis/ARQ 异步任务。

## 架构概览

```text
Browser / Capacitor
        │
        ▼
Nginx :3000 ── /api、/ws、/static 反代 ──▶ FastAPI :5002
                                             ├── PostgreSQL 18
                                             └── Redis（缓存、限流、事件、ARQ）
```

- 后端：`fastapi_app/`，分为 endpoints、schemas、services、shared_models、tasks、core。
- 前端：`frontend-vite/`，Vue 3 + TypeScript + Vite，PC 与移动端路由按设备自适应。
- 数据库迁移：`migrations/versions/`，必须使用 Alembic 管理结构变更。
- 运维与部署：`README_DEPLOY.txt`、`docs/runbooks/`。

## 快速开始

1. 安装后端依赖：

   ```powershell
   python -m pip install -r requirements/dev.txt
   ```

2. 准备环境变量：

   ```powershell
   Copy-Item .env.example .env
   ```

   必填项包括 `SECRET_KEY`、数据库凭据；生产环境还要求 Redis 凭据和强密钥校验。

3. 初始化数据库：

   ```powershell
   python -m alembic -c migrations/alembic.ini upgrade head
   ```

4. 启动开发环境：

   ```powershell
   python start.py --dev
   ```

   开发入口为 `http://localhost:3000`，后端 API 为 `http://localhost:5002/api/v1`。非生产环境可访问 `http://localhost:5002/api/docs`。

   > 端口口径：`python start.py --dev` 会把 `--port 3000` 追加给 `npm run dev`（`start.py:111`），
   > 覆盖 `package.json` 里 dev 脚本的 `--port 5173`；`vite.config.ts:144` 的 `server.port` 同样是 3000。
   > 只有绕开 `start.py` 直接裸跑 `npm run dev` 时才会落在 5173。

## 常用命令

### 后端

```powershell
python -m pytest                              # 全量测试
python -m pytest fastapi_app/tests/test_auth.py # 单文件测试
ruff check fastapi_app tests utils
python scripts/quality_gate.py --verbose
python -m mypy --config-file mypy.ini
```

### 前端

在 `frontend-vite/` 下执行：

```powershell
npm ci
npm run dev
npm run test
npm run lint
npm run build
npm run check:api
npm run check:routes
```

## 部署

生产部署为 Windows 原生内网部署，不由 CI 直接部署：

- Nginx 对外提供 `:3000`，并反代 `/api`、`/ws`、`/static`。
- FastAPI 生产默认绑定 `127.0.0.1:5002`。
- 五个 Windows 服务由 NSSM 托管：`erp-web`（nginx 静态）、`erp-prod`（uvicorn API）、`erp-arq`（ARQ worker）、`erp-redis`（缓存 6379）、`erp-redis-broker`（broker 6380）。真源为 `server_manager/constants.py:40` 的 `_SVC_ALL`，与 `README_DEPLOY.txt:20-21` 口径一致。
- 服务启停必须使用 `server_manager.py` 提供的管理器，具体见 `docs/runbooks/service-lifecycle.md`。

## 文档导航

| 主题 | 位置 |
| --- | --- |
| 后端结构与规范 | `fastapi_app/README.md` |
| 部署说明 | `README_DEPLOY.txt` |
| 变更历史 | `CHANGELOG.md` |
| 分支与提交约定 | `docs/decisions/branch-convention.md` |
| 事务边界 | `docs/TRANSACTION_BOUNDARY_GUIDE.md` |
| 架构分析 | `docs/analysis/` |
| 上传资产治理 | `docs/decisions/upload-asset-storage.md` |
| 多 SKU 与采购 DTO 规格 | `docs/decisions/multi-sku-and-purchase-dto-spec.md` |
| 前端首屏体积评估 | `docs/decisions/frontend-primevue-bundle.md` |

## 安全边界

- 真实配置只在 `.env`，不要把生产值提交到版本库。
- 备份加密密钥、JWT 私钥、监控 token 等必须由部署环境注入或受本机 ACL 保护。
- 生产环境自动关闭 OpenAPI 文档，并启用强密钥、CORS、TrustedHost、CSRF 与安全响应头。
- 图片上传使用文件魔数校验；Web Vitals 上报有批次与 IP 限流。
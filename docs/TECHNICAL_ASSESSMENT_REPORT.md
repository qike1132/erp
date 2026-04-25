# 滨发协同系统 (BinFa ERP) — 全面技术评估与优化报告

**版本**: 2.0.0  
**评估日期**: 2026-04-23  
**评估范围**: 后端 (FastAPI)、前端 (Next.js + Jinja2)、基础设施、测试体系  

---

## 执行摘要

| 维度 | 当前评分 (1-5) | 目标评分 | 关键发现 |
|------|:--------------:|:--------:|----------|
| **代码质量** | 3.2 | 4.5 | 95个超长函数, 17个深嵌套文件, 213处宽泛异常捕获 |
| **技术栈适用性** | 4.0 | 4.7 | FastAPI+Next.js 组合优秀, Jinja2 遗留层待清除 |
| **依赖项健康** | 3.0 | 4.5 | 61个过期包, redis 5.2→7.4 大版本落后 |
| **开发效率** | 3.3 | 4.5 | ruff/mypy 未安装, 11个服务无测试, 161处 TODO |
| **安全性** | 3.8 | 4.8 | Bandit 24 issues (3 HIGH), MD5 用于非安全场景但应标记 |

---

## 一、代码质量评估

### 1.1 量化指标总览

| 指标 | 数值 | 行业基准 | 评价 |
|------|------|----------|------|
| 后端 Python 文件 | 153 | — | — |
| 后端 Python LOC | 32,516 | — | 中型项目 |
| 函数/方法总数 | 1,332 | — | — |
| 类总数 | 329 | — | — |
| 平均文件 LOC | 213 | <300 | ✅ 合理 |
| 超长函数 (>50行) | **95** | <10% | ⚠️ 7.1% — 偏高 |
| 深嵌套文件 (≥5层) | **17** | 0 | ❌ 需重构 |
| 大文件 (>500 LOC) | **16** | <5% | ⚠️ 10.5% — 需拆分 |
| 宽泛异常 `except Exception` | **213** | <50 | ❌ 严重 |
| TODO/FIXME 标记 | **161** | <20 | ❌ 技术债堆积 |

### 1.2 可维护性分析

**架构层次清晰度: 4/5**

项目遵循经典三层架构:
- `api/v1/endpoints/` → 路由层 (23 个端点文件)
- `services/` → 业务逻辑层 (27 个服务)
- `shared_models/` → 数据模型层 (30 个模型, 使用 SQLAlchemy 2.0 DeclarativeBase)
- `shared/` → 跨模块共享逻辑

**耦合度问题:**

| 问题 | 严重度 | 位置 |
|------|--------|------|
| `pages.py` (701 LOC) 混合同步/异步数据库操作 | 高 | `api/v1/endpoints/pages.py` |
| `purchase_center.py` (1,406 LOC) — 项目最大文件, 包含 Pydantic 模型+路由+业务逻辑 | 高 | `api/v1/endpoints/purchase_center.py` |
| 同步会话遗留: 17个文件仍引用 `get_sync_db`/`SyncSessionLocal` | 中 | 跨模块 |
| `report_service.py` 引用已废弃的 `sync_engine` | 中 | `services/report_service.py:21` |
| Jinja2 模板层 (39 files, 22,051 LOC) 与 Next.js 并行维护 | 高 | `templates/` + `frontend-nextjs/` |

### 1.3 复杂性热点 — Top 10 超长函数

| 函数 | 行数 | 文件 | 建议 |
|------|------|------|------|
| `import_staging_stockouts_from_file()` | 240 | `ocr_service.py:975` | 拆分为 parse → validate → persist 三阶段 |
| `create_supplier_workbook()` | 186 | `purchase_center.py:1094` | 提取为独立 Excel 生成器类 |
| `batch_import_stockouts()` | 179 | `batch.py:746` | 使用策略模式统一批量导入 |
| `batch_import_case_stockouts()` | 175 | `batch.py:250` | 同上 |
| `_parse_ocr_table_format()` | 171 | `ocr_service.py:485` | 拆分列检测/行解析/数据清洗 |
| `batch_import_case_stockins()` | 168 | `batch.py:428` | 同上 |
| `get_inventory()` | 160 | `stock_crud_service.py:486` | 使用查询构建器模式 |
| `batch_import_orders()` | 152 | `batch.py:95` | 抽取为共享 pipeline |
| `batch_import_stockins()` | 144 | `batch.py:599` | 同上 |
| `import_staging_stockouts_from_excel()` | 144 | `staging_service.py:804` | 同上 |

### 1.4 深嵌套热点

| 文件 | 最大嵌套深度 | 建议 |
|------|:-----------:|------|
| `batch.py` | 8 | 提取 guard clauses, 使用 early return |
| `production_summary_service.py` | 8 | 拆分嵌套循环为子函数 |
| `purchase_plan_service.py` | 8 | 提取校验逻辑为独立方法 |
| `production_plan_service.py` | 7 | 同上 |
| `staging_service.py` | 7 | 使用 pipeline 模式替代嵌套 |

### 1.5 安全漏洞分析 (Bandit 扫描)

**扫描覆盖: 26,351 LOC | 发现: 24 issues**

| 严重度 | 数量 | 类型 | 详情 |
|--------|:----:|------|------|
| **HIGH** | 3 | B324: 弱哈希 MD5 | `order.py:31`, `cache.py:48`, `base_search_service.py:157` — 用于缓存键非安全场景, 需加 `usedforsecurity=False` 参数 |
| **MEDIUM** | 20 | B608: SQL 字符串拼接 | `report_service.py` (12处), `finance_service.py` (7处) — 已使用参数绑定, 但 Bandit 无法识别安全模式, 建议迁移到 SQLAlchemy ORM 查询 |
| **MEDIUM** | 1 | B104: 绑定所有接口 | `main.py:597` — `0.0.0.0` 绑定, Docker 环境合理但需文档标注 |

**SQL 注入防护评估:**
- ✅ 所有用户输入均通过 `:param` 参数绑定
- ✅ LIKE 查询统一使用 `escape_like()` 转义
- ✅ 输入长度限制 (`[:100]`)
- ⚠️ `report_service.py` / `finance_service.py` 的 f-string SQL 拼接属于**安全但不优雅**的模式, `where_clauses` 仅含硬编码片段, 不存在实际注入风险
- ✅ `_quote_identifier()` 正确处理标识符引用

**认证/授权:**
- ✅ Argon2id 密码哈希 (OWASP 2026 推荐)
- ✅ JWT 双模式认证 (Bearer + Cookie)
- ✅ `require_permission()` 工厂模式权限控制
- ✅ SECRET_KEY 强度校验 (≥32字符, 禁用默认值)
- ✅ CSRF 保护 (API端点豁免, 页面端点启用)
- ✅ CSP headers (nonce-based, Next.js 配置)
- ⚠️ `ALLOWED_HOSTS=*` 在生产环境仅发出警告, 建议改为强制报错

### 1.6 测试覆盖评估

| 指标 | 数值 | 目标 | 评价 |
|------|------|------|------|
| 测试文件 | 67 | — | — |
| 测试函数 | **907** | — | 数量充足 |
| 测试代码 LOC | 17,834 | — | 测试/生产代码比 0.55:1 |
| 已收集测试用例 (pytest) | **895** | — | — |
| 有测试的服务 | 16/27 | 27/27 | ⚠️ 59% |
| 无测试的服务 | **11** | 0 | ❌ |

**未覆盖的关键服务:**

| 服务 | 业务重要性 | 优先级 |
|------|-----------|--------|
| `ocr_service` | 核心 — OCR 识别 | P0 |
| `notification_service` | 核心 — WebSocket 通知 | P0 |
| `ocr_fuzzy_match` | 高 — 模糊匹配 | P1 |
| `purchase_bom_copy_service` | 高 — BOM 复制 | P1 |
| `purchase_product_service` | 高 — 采购产品 | P1 |
| `stock_concurrency` | 高 — 并发锁 | P1 |
| `base_search_service` | 中 — 搜索基类 | P2 |
| `customer_search_service` | 中 | P2 |
| `product_search_service` | 中 | P2 |
| `purchase_history_service` | 中 | P2 |
| `purchase_supplier_service` | 中 | P2 |

**测试基础设施问题:**
- ❌ `tests/conftest.py` 仍依赖 Flask `create_app()`, 大量 fixture 在无 Flask 环境下被 skip
- ❌ `auth_headers` fixture 使用 `X-User-Id` header 而非 JWT, 不测试真实认证流程
- ⚠️ 无 FastAPI TestClient 的 conftest, `fastapi_app/tests/` 有独立 conftest 但两套 fixture 共存

---

## 二、技术栈评估

### 2.1 后端: FastAPI — 评分 4.5/5 ✅ 推荐保持

| 维度 | 评价 |
|------|------|
| **适用性** | ✅ FastAPI 是 Python 异步 Web 框架的最优选择, 完美匹配 ERP 的 REST API + WebSocket + Celery 异步任务需求 |
| **性能** | ✅ asyncpg + uvicorn + msgspec 组合处于 Python 性能天花板 |
| **版本** | ✅ FastAPI 0.136.0 (最新), SQLAlchemy 2.0.49 (最新), Pydantic 2.13.2 (最新) |
| **社区** | ✅ GitHub 85k+ stars, 活跃开发, 企业级采用广泛 |
| **替代方案** | Litestar (性能略优但社区小), Django+DRF (太重), 当前选择最佳 |

**结论: FastAPI 是此项目的最佳后端框架, 无需更换。**

### 2.2 前端: Jinja2 → Next.js 迁移评估

**当前状态: 双前端并行运行**

| 层 | 文件数 | LOC | 状态 |
|----|--------|-----|------|
| Jinja2 模板 | 39 | 22,051 | 遗留, 逐步移除中 |
| Jinja2 静态 JS | 20 | 10,638 | 遗留 |
| Jinja2 静态 CSS | 11 | 5,884 | 遗留 |
| Next.js (TSX/TS) | 84 | 6,614 | 新架构, 开发中 |
| **Jinja2 遗留总计** | **70** | **38,573** | ❌ 维护成本高 |

### 2.3 前端框架推荐: Next.js vs 其他

| 框架 | 适用性 | SSR | 生态 | 学习成本 | 推荐度 |
|------|--------|-----|------|----------|:------:|
| **Next.js 16** | ✅ 企业级 ERP 首选 | ✅ App Router | ✅ 最强 | 中 | **5/5** |
| Remix | 适合表单密集应用 | ✅ | 良好 | 中 | 3/5 |
| SvelteKit | 轻量但生态较小 | ✅ | 中等 | 低 | 2/5 |
| Nuxt 3 (Vue) | Vue 生态最佳 | ✅ | 良好 | 中 | 3/5 |

**结论: Next.js 16 是 ERP 前端的最优选择**, 理由:

1. **React 生态**: shadcn/ui + TanStack Query + Zustand 组合完美匹配 ERP 复杂表单/表格需求
2. **React 19 Compiler**: 自动 memoization, 已在 `next.config.ts` 启用 (`reactCompiler: true`)
3. **App Router**: Server Components 减少客户端 JS 体积
4. **与 FastAPI 集成**: API proxy rewrite 已配置 (`/api/:path*` → `localhost:5002`)
5. **Docker 部署**: standalone output 模式已配置

**当前 Next.js 技术栈评价:**

| 组件 | 版本 | 状态 | 评价 |
|------|------|------|------|
| Next.js | 16.2.4 | ✅ 最新 | 完美 |
| React | 19.2.4 | ✅ 最新 | 完美 |
| TypeScript | 5.8.3 | ✅ 最新 | 完美 |
| TailwindCSS | 4.2.4 | ✅ 最新 | 完美 |
| shadcn/ui | v4 (@base-ui/react) | ✅ 最新 | 完美 |
| Zustand | 5.0.12 | ✅ 最新 | 完美 |
| TanStack Query | 5.99.2 | ✅ 最新 | 完美 |
| Zod | 4.3.6 | ✅ 最新 | 完美 |

### 2.4 数据库: PostgreSQL 17 — 评分 4.5/5

- ✅ 连接池配置合理: `pool_size=30, max_overflow=20, pool_pre_ping=True, pool_use_lifo=True`
- ✅ Docker 性能调优参数已配置 (`shared_buffers=1GB, effective_cache_size=3GB`)
- ✅ asyncpg 异步驱动 (Python 最快的 PostgreSQL 驱动)
- ⚠️ `pool_recycle=1800` 在 PostgreSQL 环境中非必需 (MySQL 遗留习惯)

### 2.5 缓存/队列: Redis 7.4 + Celery 5.6 — 评分 4/5

- ✅ Redis 用途合理: 缓存 + Pub/Sub + Celery Broker
- ✅ `maxmemory-policy allkeys-lru` 配置合理
- ⚠️ 本地安装的 redis 包 5.2.0, 远落后于 7.4.0 (大版本跳跃, API 有变化)

### 2.6 监控栈: Prometheus + Grafana + Loki — 评分 4.5/5

- ✅ 完整的可观测性三支柱 (Metrics + Logs + 待补 Traces)
- ✅ 自定义 Prometheus 中间件 (请求计数/延迟/并发)
- ✅ PostgreSQL Exporter + Redis Exporter + Celery Exporter
- ✅ Flower 监控 Celery 任务
- ⚠️ OpenTelemetry Traces 为可选项 (`OTEL_ENABLED`), 建议默认启用

---

## 三、依赖项审查

### 3.1 过期依赖统计

**总计 61 个过期包**, 按影响分级:

#### 🔴 高优先级 (安全/大版本)

| 包 | 当前版本 | 最新版本 | 影响 |
|----|----------|----------|------|
| **redis** | 5.2.0 | **7.4.0** | 大版本升级, API 可能破坏性变更 |
| **bcrypt** | 4.3.0 | **5.0.0** | 大版本, 密码验证向后兼容 |
| **starlette** | 0.50.0 | **1.0.0** | FastAPI 内部依赖, 跟随 FastAPI 升级 |
| **cryptography** | 46.0.0 | 46.0.7 | 安全补丁 |
| **PyJWT** | 2.10.1 | 2.12.1 | 安全相关 |

#### 🟡 中优先级 (性能/功能)

| 包 | 当前版本 | 最新版本 | 影响 |
|----|----------|----------|------|
| **pandas** | 2.2.3 | **3.0.2** | 大版本, 可能破坏 DataFrame API |
| **onnxruntime** | 1.22.0 | 1.25.0 | OCR 性能提升 |
| **opencv-python** | 4.10.0.84 | 4.13.0.92 | OCR 相关 |
| **pydantic-settings** | 2.8.0 | 2.14.0 | 新功能 |
| **prometheus_client** | 0.21.0 | 0.25.0 | 监控改进 |
| **argon2-cffi** | 23.1.0 | 25.1.0 | 安全组件 |

#### 🟢 低优先级 (小版本)

| 包 | 当前版本 | 最新版本 |
|----|----------|----------|
| httpx | 0.28.0 | 0.28.1 |
| python-multipart | 0.0.22 | 0.0.26 |
| python-dotenv | 1.1.0 | 1.2.2 |
| structlog | 25.1.0 | 25.5.0 |
| flower | 2.0.0 | 2.0.1 |
| bleach | 6.2.0 | 6.3.0 |

### 3.2 依赖必要性评估

| 包 | 用途 | 是否必要 | 建议 |
|----|------|----------|------|
| `werkzeug` | 仅用于旧密码哈希验证 | 过渡性 | 全量迁移 Argon2 后移除 |
| `bcrypt` | 仅用于旧密码哈希验证 | 过渡性 | 同上 |
| `arrow` | 日期处理 | 可替代 | 标准库 `datetime` 已足够 |
| `python-dateutil` | 日期解析 | 保留 | pandas 依赖 |
| `bleach` | HTML 清理 | 保留 | XSS 防护必需 |
| `pystray` + `Pillow` | 桌面托盘 (server_manager) | 可选 | 仅 Windows 部署需要 |
| `Jinja2` | 遗留模板渲染 | 过渡性 | Next.js 迁移完成后移除 |

### 3.3 许可证合规

| 包 | 许可证 | 风险 |
|----|--------|------|
| FastAPI | MIT | ✅ 无限制 |
| SQLAlchemy | MIT | ✅ 无限制 |
| Pydantic | MIT | ✅ 无限制 |
| Redis (py) | MIT | ✅ 无限制 |
| Celery | BSD | ✅ 无限制 |
| onnxruntime | MIT | ✅ 无限制 |
| opencv-python | Apache 2.0 | ✅ 无限制 |
| RapidOCR | Apache 2.0 | ✅ 无限制 |
| pandas | BSD-3 | ✅ 无限制 |

**结论: 所有依赖均为宽松开源许可证 (MIT/BSD/Apache), 无 GPL 传染风险。**

---

## 四、开发工具链优化

### 4.1 当前工具链状态

| 工具 | 状态 | 问题 |
|------|------|------|
| **ruff** | ❌ 未安装 | `requirements/dev.txt` 声明了但未实际安装 |
| **mypy** | ❌ 未安装 | 同上 |
| **bandit** | ✅ 已安装 v1.9.4 | 正常 |
| **pytest** | ✅ v9.0.3 | 低于声明版本 (≥8.4.0) 但兼容 |
| **pytest-cov** | ✅ v7.1.0 | 正常 |
| **ESLint** | ✅ v9.32.0 | Next.js 项目已配置 |
| **TypeScript** | ✅ v5.8.3 | 最新 |

### 4.2 CI/CD 评估

- `Jenkinsfile.template` 存在但为模板状态
- `.github/` 目录存在 (1 item) — 可能有 GitHub Actions
- 无 pre-commit hooks 配置
- 无自动化代码质量门禁

### 4.3 监控工具评估

| 工具 | 覆盖 | 评价 |
|------|------|------|
| Prometheus | 请求指标 | ✅ 自定义中间件, 路径规范化 |
| Grafana | 可视化 | ✅ 仪表板已配置 |
| Loki + Promtail | 日志聚合 | ✅ 结构化日志 (structlog) |
| Flower | Celery 监控 | ✅ 任务状态追踪 |
| PostgreSQL Exporter | 数据库监控 | ✅ |
| Redis Exporter | 缓存监控 | ✅ |
| **OpenTelemetry** | 分布式追踪 | ⚠️ 可选未默认启用 |
| **Sentry/错误追踪** | 异常追踪 | ❌ 未配置 |
| **慢查询日志** | SQL 性能 | ✅ `slow_query.py` 已实现 |

---

## 五、优化建议与实施路线图

### Phase 1: 紧急修复 (1-2周) — 安全与基础

| # | 任务 | 影响 | 优先级 | 预期收益 | 风险 |
|---|------|------|:------:|----------|------|
| 1.1 | **安装 ruff + mypy + pre-commit** | 代码质量 | 5 | 杜绝低级错误, 提升代码一致性 | 低 — 纯工具链 |
| 1.2 | **MD5 调用加 `usedforsecurity=False`** | 安全 | 5 | 消除 3 个 HIGH Bandit 告警 | 极低 — 单行修改 |
| 1.3 | **升级安全相关依赖** (cryptography, PyJWT, argon2-cffi) | 安全 | 5 | 修复已知 CVE | 低 — 小版本兼容 |
| 1.4 | **生产环境 `ALLOWED_HOSTS=*` 改为强制报错** | 安全 | 4 | 防止 Host 头注入 | 低 |
| 1.5 | **清理 `tests/conftest.py` Flask 遗留** | 测试 | 4 | 测试可靠性提升 | 低 |

**实施步骤 1.1:**
```bash
pip install ruff mypy pre-commit
# 创建 ruff.toml
ruff check fastapi_app/ --fix
# 创建 .pre-commit-config.yaml
pre-commit install
```

**预期收益**: 开发效率提升 ~15%, 每次提交自动拦截代码风格/类型问题

### Phase 2: 代码重构 (2-4周) — 质量提升

| # | 任务 | 影响 | 优先级 | 预期收益 | 风险 |
|---|------|------|:------:|----------|------|
| 2.1 | **拆分 `purchase_center.py` (1,406 LOC)** | 可维护性 | 5 | 单文件 → 4个模块 (路由/模型/服务/导出) | 中 — 需完整测试 |
| 2.2 | **统一批量导入为 Pipeline 模式** | 复杂性 | 5 | `batch.py` 6个 150+ 行函数 → 统一 pipeline | 中 |
| 2.3 | **消除同步数据库调用** | 性能 | 4 | 17个文件 → 全异步, 消除线程池开销 | 中 |
| 2.4 | **`report_service.py` / `finance_service.py` 迁移到 ORM 查询** | 安全/维护 | 4 | 消除 20 个 Bandit SQL 告警, 获得类型安全 | 中 |
| 2.5 | **减少宽泛异常捕获** | 可靠性 | 3 | 213处 → 精确异常类型, 改善错误诊断 | 低 |
| 2.6 | **清理 161 处 TODO/FIXME** | 技术债 | 3 | 归档已完成项, 创建 Issue 跟踪未完成项 | 低 |

**实施步骤 2.1 — 拆分 purchase_center.py:**
```
api/v1/endpoints/purchase_center/
├── __init__.py          # re-export router
├── router.py            # 路由定义 (~200 LOC)
├── schemas.py           # Pydantic 请求模型 (~150 LOC)
├── supplier_routes.py   # 供应商路由 (~300 LOC)
├── bom_routes.py        # BOM 路由 (~300 LOC)
├── order_routes.py      # 订单路由 (~300 LOC)
└── export.py            # Excel 导出 (~200 LOC)
```

**实施步骤 2.2 — 批量导入 Pipeline 模式:**
```python
class BatchImportPipeline:
    """统一批量导入管道"""
    async def execute(self, file, db, user):
        raw_data = await self.parse(file)          # 1. 解析
        validated = await self.validate(raw_data)   # 2. 校验
        result = await self.persist(validated, db)   # 3. 持久化
        await self.notify(result, user)              # 4. 通知
        return result
```

### Phase 3: 前端迁移加速 (4-8周) — Jinja2 → Next.js

| # | 任务 | 影响 | 优先级 | 预期收益 | 风险 |
|---|------|------|:------:|----------|------|
| 3.1 | **迁移剩余 Jinja2 页面到 Next.js** | 架构 | 5 | 消除双前端维护成本, 节省 38,573 LOC | 高 — 功能回归 |
| 3.2 | **移除 `pages.py` 和 `templates/` 目录** | 清理 | 4 | 删除 701 LOC 路由 + 22,051 LOC 模板 | 依赖 3.1 |
| 3.3 | **移除 `Jinja2` + `werkzeug` 依赖** | 精简 | 3 | 减少 2 个生产依赖 | 依赖 3.2 |
| 3.4 | **添加前端测试 (Playwright/Vitest)** | 质量 | 4 | 页面级回归测试 | 低 |

**迁移优先级 (按业务价值):**

| 页面 | Jinja2 存在 | Next.js 已有 | 迁移优先级 |
|------|:-----------:|:------------:|:----------:|
| 仪表盘 | ✅ | ✅ | 已完成 |
| 订单管理 | ✅ | ✅ | 已完成 |
| 产品管理 | ✅ | ✅ | 已完成 |
| 库存管理 | ✅ | ✅ | 已完成 |
| 采购中心 | ✅ | ✅ | 已完成 |
| 审批管理 | ✅ | ✅ | 已完成 |
| 排产计划 | ✅ | ✅ | 已完成 |
| 报表统计 | ✅ | ✅ | 功能验证中 |
| OCR 导入 | ✅ | ❓ | P1 |
| 系统设置 | ✅ | ❓ | P2 |

### Phase 4: 性能与依赖升级 (2-4周)

| # | 任务 | 影响 | 优先级 | 预期收益 | 风险 |
|---|------|------|:------:|----------|------|
| 4.1 | **升级 redis 5.2 → 7.4** | 性能 | 4 | 新协议、性能提升, 但需验证 API 兼容 | 中 |
| 4.2 | **升级 pandas 2.2 → 3.0** | 依赖 | 3 | 性能提升, Arrow 后端默认启用 | 高 — API 变更 |
| 4.3 | **启用 OpenTelemetry 默认追踪** | 可观测性 | 4 | 端到端请求追踪 | 低 |
| 4.4 | **添加 Sentry 错误追踪** | 运维 | 4 | 实时异常告警, MTTR 降低 50% | 低 |
| 4.5 | **PostgreSQL `pool_recycle` 移除** | 性能 | 2 | 消除不必要的连接回收 | 极低 |

### Phase 5: 测试完善 (持续)

| # | 任务 | 影响 | 优先级 | 预期收益 |
|---|------|------|:------:|----------|
| 5.1 | **为 11 个无测试服务添加测试** | 覆盖率 | 5 | 服务测试覆盖 59% → 100% |
| 5.2 | **添加 FastAPI TestClient 集成测试** | 可靠性 | 4 | 测试真实 HTTP + 认证流程 |
| 5.3 | **添加 Playwright E2E 测试** | 质量 | 3 | 前端页面级回归 |
| 5.4 | **CI 门禁: 覆盖率不低于 80%** | 流程 | 4 | 防止覆盖率退化 |

---

## 六、实施路线图总览

```
Week 1-2   [Phase 1] 紧急修复 — 工具链安装 + 安全修复
              ↓
Week 3-6   [Phase 2] 代码重构 — 大文件拆分 + Pipeline 模式
              ↓ (并行)
Week 3-10  [Phase 3] 前端迁移 — Jinja2 → Next.js 剩余页面
              ↓
Week 7-10  [Phase 4] 性能升级 — 依赖升级 + 监控增强
              ↓
Week 1-∞   [Phase 5] 测试完善 — 持续补充, 与各 Phase 并行
```

## 七、成功衡量标准

| KPI | 当前值 | 6周目标 | 12周目标 |
|-----|--------|---------|----------|
| Bandit HIGH 告警 | 3 | **0** | 0 |
| 超长函数 (>50行) | 95 | <60 | <30 |
| 深嵌套 (≥5层) | 17 | <10 | <5 |
| 服务测试覆盖率 | 59% | 80% | 100% |
| 过期依赖数 | 61 | <30 | <10 |
| Jinja2 遗留 LOC | 38,573 | <20,000 | **0** |
| TODO/FIXME 标记 | 161 | <80 | <20 |
| ruff 告警数 | 未扫描 | <50 | **0** |
| mypy 类型覆盖 | 0% | 60% | 90% |
| 平均 API 响应时间 | 未基线 | 建立基线 | <200ms P95 |

---

*报告结束 — 本报告基于 2026-04-23 代码库快照生成*

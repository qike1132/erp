# AGENTS.md —— 滨发协同系统（binfa-erp）项目契约

> 这是本仓库**唯一**的协作契约。动手前先读完本文件。
> `.windsurfrules`、`GEMINI.md`、`.github/copilot-instructions.md` 只是指向本文件的指针，内容以本文件为准。

## 0. 最重要的一条

**这台机器既是生产主机，也是运维主机。** 没有独立的测试/预发环境 —— 你在这里执行的任何命令都直接影响在用业务。改动要小步、可回滚，提交前先跑质量门禁。

## 1. 项目是什么

内网部署的**生产** ERP（滨发协同系统），覆盖采购、客户订单、库存、出货计划、生产、板房、审批、备份、系统管理。

## 2. 技术栈与目录职责

| 路径 | 职责 |
|---|---|
| `fastapi_app/` | 后端：FastAPI + PostgreSQL + Redis/ARQ |
| `fastapi_app/api/v1/router.py` | 以**绝对导入**挂载各端点模块（零孤儿，勿凭"没被引用"就删模块） |
| `fastapi_app/core/` | 配置、日志、ARQ 应用与回调、`prod_runner.py`（生产启动监督器） |
| `fastapi_app/services/` | 业务服务层，`backup/` 含备份、加密、恢复、清理 |
| `frontend-vite/` | 前端：Vue 3 + TypeScript + Vite 7（**需 Node >= 22**） |
| `migrations/versions/` | Alembic 迁移（**必须保持单一 head**） |
| `server_manager.py` + `server_manager/` | NSSM 服务管理（PyInstaller 入口，唯一生产启停通道） |
| `scripts/` | 运维与质量脚本（`quality_gate.py`、`scan_secrets.py` 等） |
| `tests/`、`fastapi_app/tests/` | 回归测试，`pytest.ini` 的 `testpaths` **同时**包含两者 |
| `docs/` | 文档与决策记录；`deliverables/` 是历史交付物归档，**不要**当作现行真相 |
| `backups/`、`logs/` | 运行期数据，不入库 |
| `_ops/credentials/` | 凭据存放处，已被 `.gitignore` 覆盖，**永不入库** |

## 3. 端口与运行拓扑（生产）

```
浏览器 → nginx :3000  (config/nginx-windows.conf, root = frontend-vite/dist)
        → uvicorn 127.0.0.1:5002  (仅绑回环；API 不直接暴露给局域网)
        → PostgreSQL :5432 / Redis :6379
后台任务 → ARQ worker（独立进程，不是 API 的子进程）
```

- 生产由 **5 个 NSSM 服务**托管：`erp-web`、`erp-prod`、`erp-arq`、`erp-redis`、`erp-redis-broker`。
- `erp-prod` 的命令是 `python -m fastapi_app.core.prod_runner --no-arq`；**ARQ 由 `erp-arq` 单独托管**，因此 `logs/prod_runner.json` 里 `arq.status = "external"` 是**正常设计**，不是故障。
- 健康状态以 `logs/prod_runner.json` 为准（原子写入）：需 `ready: true` 且 `frontend_ok: true`。
- 生效的 nginx 配置是 **`config/nginx-windows.conf`**；`config/nginx.conf` 里的 `root /app/...` 在 Windows 上永不生效，是死配置。
- **唯一启动入口是 `python start.py`**（`run.py` 已被取代）。手工起 `uvicorn`/`vite dev` 会与生产抢端口。

## 4. 质量门禁与提交

```bash
python scripts/quality_gate.py    # 基线棘轮门禁：违规数【超过】scripts/gate_baseline.json 才失败
ruff check .                      # lint（配置 ruff.toml）
mypy                              # 类型（配置 mypy.ini）
pytest -q                         # 回归（testpaths = tests + fastapi_app/tests）
cd frontend-vite
npm run type-check                # vue-tsc --noEmit
npm test                          # vitest run
npm run lint                      # eslint src/ --ext .ts,.vue
npm run check:api                 # API 对齐检查
npm run check:routes              # 路由对齐检查
```

- `quality_gate.py` 读 `pyproject.toml` 的 `[tool.code-quality]`：`max_function_length=80`、`max_vue_component_length=400`、`max_file_size=1600`。**只拦新增违规**；清理存量后可用 `--update-baseline` 收紧基线。
- 提交钩子：`core.hooksPath = .githooks`。`.githooks/pre-commit` 分四层 —— ①危险路径 ②密钥内容扫描（**总是跑**）③Python 字面量收窄 ④`.pre-commit-config.yaml`（`ruff --fix`、`ruff-format`、local `quality-gate`）。
- 本机**未安装 `pre-commit`**，第 ④ 层会降级：仅当暂存含 `.py`/`.vue` 时直接跑 `quality_gate.py`。要恢复完整门禁：`pip install pre-commit`。
- `.githooks/commit-msg`（第 5 层）：**剥掉第三方 AI 工具的署名尾行**（`🤖 Generated with <tool>` / `Co-Authored-By: <tool> <...>`，工具列表见该文件）。背景：Codebuff 曾把署名写进 12 个提交（2026-08-11 起），与 §7 的 AI 痕迹治理意图相悖；就地剥离而非拒绝，避免阻断任何工具的工作流。**故意不剥 Claude 的署名**（本仓明确使用 Claude Code）。
- 密钥扫描误报的**正确**处置是在命中行尾加 `secret-scan:allow <理由>`（或上一行加 `secret-scan:allow-next-line`）；`.githooks/allowlist.txt` 是逐文件豁免，**新增条目必须在提交信息里说明理由**。
- 提交信息写**为什么**，不只写改了什么。一个提交只做一件事。提交前用 `git status --porcelain` 确认没有卷进 AI 痕迹或运行期数据。
- 迁移：**禁止对生产库运行 `alembic revision --autogenerate`**（生产有历史漂移，会生成一批 `DROP INDEX`/`DROP TABLE`/`DROP COLUMN` 破坏性 DDL）。需生成迁移时先在**临时空库** `upgrade head`，改模型后再对空库 autogenerate，判据同 CI（空库 `upgrade head` + `check`）。`migrations/versions/` 下新增的破坏性 DDL 会被 `fastapi_app/tests/test_migration_autogenerate_safety.py` 拦下。详见 `migrations/README`。

## 5. 红线（会打挂生产，别做）

1. **不要删除**根 `utils/`（`fastapi_app/main.py` 直接 `from utils.redis_cache import ...`）、`fastapi_app/utils/`（十多个 service 依赖）、`server_manager.py` + `server_manager/`。
2. **不要**把 `config/pgbouncer/userlist.txt` 或任何 `_ops/credentials/**` 加回版本库。
3. **不要**让 uvicorn 绑 `0.0.0.0`（会绕过 nginx、并把 `/metrics` 暴露给同网段）。
4. **不要**在开启加密时让 `.env` 的 `BACKUP_ENCRYPTION_PASSWORD` 为空：`BACKUP_ENCRYPTION_ENABLED=true` 且密码为空，`STRICT_CONFIG_CHECK=true` 下**拒绝启动**，否则**静默降级为不加密备份**。备份加密**默认关闭**（`BACKUP_ENCRYPTION_ENABLED` 缺省 `false`，2026-10-09 起）；要加密必须显式置 `true` 并配好密码。`BACKUP_ENCRYPTION_ENABLED=false` 是加密**总开关**，关闭时 API/前端传来的 `encrypt=true` 一律被忽略。
5. **不要**修改或删除 `frontend-vite/vite.config.js` —— 它是 `vue-tsc -b` 编译 `vite.config.ts` 的**设计产物**，且有回归测试（`fastapi_app/tests/test_qa_prod_stack_regression.py`）断言二者一致。
6. **不要**改 `core.hooksPath`（指到 husky 目录会废掉 `.githooks` 的密钥扫描）。
7. Alembic 迁移只做结构/数据变更，不夹带业务逻辑；保持单 head。**不得对生产库跑 autogenerate**（见 §4）。

## 6. 分析代码的方法（本项目踩过的坑）

- **解析 Python 结构（导入关系、迁移依赖图、`__init__.py` 聚合）必须用 `ast`**，不要用正则或 shell 文本匹配。曾因此得出"15 个迁移 head""48 个端点模块未接线"两个纯解析伪影，真相是**单 head、零孤儿**。
- 判断死代码要按**全仓导入**判断，不能只看是否被 `router.py` 直接引用（`backup/`、`purchase_center/` 通过 `__init__.py` 聚合）。
- `deliverables/`、`*.md` 报告里的结论可能**已过期**（例：某报告称 `utils.redis_cache` 不存在），以代码为准。
- 本机 shell 是 **Windows PowerShell 5.1**（不是 pwsh 7）：`-Encoding utf8` 会写 BOM、没有 `Get-Content -AsByteStream`；把内联 `if(){...}else{...}` 塞进字符串插值会触发 `MissingEndParenthesisInExpression` 并让**整段脚本一行都不执行**（分步、先赋值再输出）。
- git-bash（`C:\Program Files\Git\bin\bash.exe`）里 `python` 常常不在 PATH，钩子靠绝对路径兜底。

## 7. AI 工具痕迹治理

仓库根目录曾被 15+ 个 AI 编程工具的痕迹目录污染。以下已在 `.gitignore` 中忽略，**不要提交**：
`.agent/ .claude/ .cursor/ .graphflow/ .graphflow-cache/ graphflow-out/ .trae/ .qoder/ .workbuddy/ .reasonix/ .superpowers/ .codebuddy/ .freebuff/ .lean-ctx/ .resultverify/ .codeartsdoer/ .zcode/ .zcodeignore dsh-web-dump-config.txt`

其中 `.zcodeignore` 是从 `.gitignore` 自动同步的派生文件（自述如此），入库会制造第二个真相源，故同样忽略（2026-10-05）。

`AGENTS.md`（本文件）、`.windsurfrules`、`GEMINI.md`、`.github/copilot-instructions.md` **刻意不忽略**，因为它们是协作契约。

## 8. 可选工具

GraphFlow MCP（`graphflow_*` 工具）可用作上下文压缩/规划辅助，**它只是工具，不定义本项目约定**。若使用，`rootDir` 传本仓库绝对路径；`graphflow_context` 返回的是提示，不是项目事实。

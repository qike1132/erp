# AGENTS.md —— 滨发协同系统（binfa-erp）项目契约

> 本仓库**唯一**的协作契约，动手前先读完。
> `.windsurfrules`、`GEMINI.md`、`.github/copilot-instructions.md` 只是指向本文件的指针。

## 0. 最重要的一条

**这台机器既是生产主机，也是运维主机。**没有独立测试/预发环境——任何命令都直接影响在用业务。改动小步、可回滚，提交前先跑门禁。

## 1. 项目是什么

内网部署的**生产** ERP（滨发协同系统）：采购、客户订单、库存、出货计划、生产、板房、审批、备份、系统管理。

## 2. 技术栈与目录职责

| 路径 | 职责 |
|---|---|
| `fastapi_app/` | 后端：FastAPI + PostgreSQL + Redis/ARQ |
| `fastapi_app/api/v1/router.py` | **绝对导入**挂载端点模块；零孤儿，"没被引用"≠可删 |
| `fastapi_app/core/` | 配置、日志、ARQ 应用与回调、`prod_runner.py`（生产启动监督器）。core 是**组合根**，允许 import `services`（契约未禁止，勿当越层修） |
| `fastapi_app/services/` | 业务服务层；`backup/` 含备份、加密、恢复、清理 |
| `frontend-vite/` | 前端：Vue 3 + TS + Vite 7（**Node >= 22**） |
| `migrations/versions/` | Alembic 迁移（**单一 head**） |
| `server_manager.py` + `server_manager/` | NSSM 服务管理（PyInstaller 入口，唯一生产启停通道） |
| `scripts/` | 运维与质量脚本（`quality_gate.py`、`scan_secrets.py` 等） |
| `tests/`、`fastapi_app/tests/` | 回归测试，`pytest.ini` 的 `testpaths` 同时含两者 |
| `docs/` | 文档与决策记录；`deliverables/` 是历史归档，**不是现行真相** |
| `backups/`、`logs/` | 运行期数据，不入库 |
| `_ops/credentials/` | 凭据，已被 `.gitignore` 覆盖，**永不入库** |

## 3. 端口与运行拓扑（生产）

```
浏览器 → nginx :3000 (config/nginx-windows.conf, root = frontend-vite/dist)
        → uvicorn 127.0.0.1:5002 (仅绑回环，API 不直接暴露局域网)
        → PostgreSQL :5432 / Redis :6379
后台任务 → ARQ worker（独立进程，非 API 子进程）
```

- 生产 = **5 个 NSSM 服务**：`erp-web`、`erp-prod`、`erp-arq`、`erp-redis`、`erp-redis-broker`。
- `erp-prod` 命令为 `python -m fastapi_app.core.prod_runner --no-arq`；**ARQ 由 `erp-arq` 单独托管**，故 `logs/prod_runner.json` 的 `arq.status="external"` 是**正常设计**。
- 健康以 `logs/prod_runner.json` 为准（原子写入）：需 `ready: true` 且 `frontend_ok: true`。
- 生效的 nginx 配置是 **`config/nginx-windows.conf`**；`config/nginx.conf` 的 `root /app/...` 在 Windows 永不生效，是死配置。
- **唯一启动入口 `python start.py`**（`run.py` 已被取代）。手工起 `uvicorn`/`vite dev` 会与生产抢端口。

## 4. 质量门禁与提交

```bash
python scripts/quality_gate.py    # 基线棘轮门禁：违规数【超过】scripts/gate_baseline.json 才失败
ruff check fastapi_app tests fastapi_app/tests utils   # lint（与 CI 同口径；scripts/ + server_manager/ 存量违规走棘轮记账，`ruff check .` 会报出它们）
mypy --config-file mypy.ini --no-native-parser         # 类型（mypy.ini）。本机 mypy 2.4.0 的 ast_serialize 是需手工构建的 Rust 扩展，默认跑法会 INTERNAL ERROR（G-01）
pytest -q                         # 回归（testpaths = tests + fastapi_app/tests）
cd frontend-vite
npm run type-check                # vue-tsc --noEmit
npm test                          # vitest run
npm run lint                      # eslint src/ --ext .ts,.vue
npm run check:api                 # API 对齐检查
npm run check:api:pc              # 移动端 API 对齐
npm run check:routes              # 路由对齐
npm run check:dto                 # 跨端 DTO 对齐（防移动端绕过 @/types 重复声明）
npm run check:types               # 类型对齐
```

以上 = CI（`.github/workflows/ci-cd.yml`）三个 job（test/lint/frontend）门禁的**本地等价物**，少跑一项 CI 就可能变红。CI 红了先看哪个 job 的**第一个 failure step**。

- **pytest 必须提权跑**：根 `.env` 的 ACL 只授予 Administrators/SYSTEM，非提权跑会因 conftest 读不到 `.env` 整批假红（连的是真实测试库 `erp_system_test`，非派生库）。正路：提权跑 `logs/_run_pytest_elevated.ps1`（2026-10-12 实测全量 4353 passed / 271 skipped）；非提权只读场景用「stub .env 为空流」脚本绕。**全量 pytest 必须独占单实例**——两进程共用 `erp_system_test` 会互撞假红（`DROP SCHEMA` + 硬编码 `SO-PERF-*`，见 `docs/agents/pitfalls.md` §7）。机器护栏已落地（F2-7，与 Z09-R5 同一修法）：`tests/conftest.py::_exclusive_test_db_lock` 用 PG 咨询锁按库互斥，第二个实例直接 `exit 2` 并报出占用者 PID。
- **vitest 要把 TEMP 指进仓内**（如 `frontend-vite/.vitest-tmp`），否则 EPERM mkdir 导致全部 0 test 失败；前端构建用 `npm run build:atomic`，esbuild 需 `ESBUILD_BINARY_PATH` 指外部副本，绕开 `%TEMP%` 删除限制。
- **pip-audit 口径（2026-10-11 起判定；2026-10-21 更正豁免所在文件，审计 F1-8）**：CI 已恢复判定——步骤输出 JSON 后由 `scripts/quality_gate.py --only pip_audit` 判定（豁免项见 **`pyproject.toml`** 的 `[[tool.code-quality.pip-audit-ignores]]`，门禁只读 `quality_gate.py:74` 定义的 `PYPROJECT`；写进 `ruff.toml` 不会被任何代码读到 = 静默失效的豁免）。**不要**为过门禁批量登记豁免；依赖升级后再收紧。
- CI 的 lint job 另跑四项：`scan_secrets.py --verbose`（全树密钥）、`check_orphan_modules.py`（孤儿模块）、`file_size_gate.py`（PR 基线对比）、`check_requirements_lock.py`（`requirements/<tier>.lock` 与 `.txt` 同步，需 `uv`）。改动涉及模块接线/删文件/新增大文件/改 `requirements/*.txt` 时先本地跑。

### 改动范围 → 最小验证

全量 pytest 须提权且 4300+ 条（下限表述，实测见上）；按范围选强度，**跳过任何验证须写明理由**（文档改动、只读调查、CI-only 分析可接受）：

| 改动范围 | 最小验证 |
|---|---|
| 仅文档/注释/`deliverables/` | 免测（写明理由） |
| 单文件/单模块逻辑 | `pytest <文件>::<类>::<用例> -k <词>` 聚焦跑；前端 `npx vitest run -t "<名>"` |
| 跨层（前后端/迁移/路由） | 聚焦测试 + 对应 `check:*` + CI 三 job 全绿 |
| 测试/构建/门禁配置 | 全量提权跑（`logs/_run_pytest_elevated.ps1`） |

- **输出跑一次存文件**：`pytest ... > /tmp/out.log 2>&1` 后 grep/tail 分析，别换 filter 重跑同一套件。
- **验证复用**：输入（代码+依赖）未变时复用已通过的结论，进 review/commit/PR 不必重跑。
- **临时文件必须清理**：迭代产生的脚本/夹具/日志，任务结束删掉（2026-10-10 `logs/` 临时文件打挂 check_bom 门禁，见 2c6a92d3）。

### 五条铁律（判断口径；正反例与 owner 问法原文见 [docs/agents/verification-and-review.md](docs/agents/verification-and-review.md)）

1. **证据先于断言**：没有当场跑出的输出，不得声称任何状态——"应该/大概/看起来"即违规信号。修 bug 必须配回归测试（Red→Green）：答不出「哪条测试证明这次改动」的提交不完整。
2. **根因先于修复**：打症状补丁是最高频的产 bug 方式；先复现、逐层取证定位到层、沿调用链回溯到源头；换 2 个修复还没好 = 根因没找对，回第 1 步，别试第 3 个。
3. **假测试甄别**：镜像断言（期望值由被测代码自己算出）、mock 存在性断言、从没红过的测试；交付前做**变异检查**——把被测行为改坏一处，对应测试必须变红。
4. **新眼睛评审**：写代码的 AI 评审自己有确认偏误，合并/部署前必须由**未参与实现的新鲜上下文**只看 diff + 需求原文评审。
5. **owner 问法**：不问"代码对吗"，问「这次改动配了哪条测试、**当场跑给我看**」「把这条测试的行为**故意改坏**，跑给我看它变红」「**用一句人话**讲清根因是什么」。

- **评审时点 = 推送前一次**（owner 2026-10-13 定）：修复 → 跑门禁 → 只提交当前任务（不夹带并发会话的活）→ **等 owner 说「推送」** → 用 `/open-code-review:delegate-review` **一次**审完「当前分支相对 main 的 merge-base 起的全部提交」→ 迭代到零 High/Medium 才推送 → 跑 CL 盯到全绿；评审子代理一律用**最强模型**。理由：逐提交评审会把同一段代码反复审，而提交钩子判不了「评审做没做」；攒到推送前审的是**真正要进 main 的那一坨**。

- **评审标准与流程**：分级（Blocker/High/Medium/Low/Nit）、按改动类型的必查表、证据要求见 [docs/agents/code-review-standard.md](docs/agents/code-review-standard.md)；阶段、命令与异常路径见 [docs/agents/code-review-process.md](docs/agents/code-review-process.md)。评审前先跑 `python scripts/review_packet.py` 生成评审包（自动解析远端 main；本仓远端名为 `erp`）（风险标记 + 必查项 + 必跑命令，只读），别靠翻 diff 猜重点。

- **提交钩子/门禁参数/迁移禁令的细节**（`quality_gate.py` 阈值、`.githooks` 四层与回退、`commit-msg` 剥第三方 AI 署名、密钥扫描误报处置、`alembic autogenerate` 禁令）见 [docs/agents/verification-and-review.md](docs/agents/verification-and-review.md) §6。**每次提交都要看见的三条**：提交信息写**为什么**；一个提交只做一件事；**只 `git add` 当前任务涉及的文件**，提交前 `git status --porcelain` 确认没卷进 AI 痕迹或运行期数据。

## 5. 红线（会打挂生产，别做）

1. **不要删除**根 `utils/`（`fastapi_app/main.py` 直接 `from utils.redis_cache import ...`）、`fastapi_app/utils/`（十多个 service 依赖）、`server_manager.py` + `server_manager/`。
2. **不要**把 `config/pgbouncer/userlist.txt` 或任何 `_ops/credentials/**` 加回版本库。
3. **不要**让 uvicorn 绑 `0.0.0.0`（绕过 nginx，并把 `/metrics` 暴露给同网段）。
4. **备份加密**：`BACKUP_ENCRYPTION_ENABLED` 默认 `false`（2026-10-09 起）且是**总开关**，关闭时 API/前端传来的 `encrypt=true` 一律忽略。置 `true` 必须同时配好 `BACKUP_ENCRYPTION_PASSWORD`——密码为空时 `STRICT_CONFIG_CHECK=true` 下**拒绝启动**，否则**静默降级为不加密备份**。
5. **不要**改或删 `frontend-vite/vite.config.js`——它是 `vue-tsc -b` 编译 `vite.config.ts` 的**设计产物**，且有回归测试（`fastapi_app/tests/test_qa_prod_stack_regression.py`）断言二者一致。
6. **不要**改 `core.hooksPath`（指到 husky 会废掉 `.githooks` 的密钥扫描）。
7. 迁移只做结构/数据变更，不夹带业务逻辑，保持单 head；**不得对生产库 autogenerate**（见 §4）。

## 6. 生产运维护栏与分析方法

### 6.1 生产运维操作护栏（红线之外的第二道人防）

红线（§5）拦"改代码打挂生产"，**运行期操作**（重启、清库、改配置、连生产库）没有机器门禁，靠本节。任何针对生产的手工操作前逐条自问：

1. **动的是生产吗？**（`nssm restart`、直连 `127.0.0.1:5432`、改 `.env`、`nginx -s reload`——本机没有"测试环境"，默认就是生产。）
2. **有只读/低危替代吗？**先 `SELECT` 看清再动，先 `nssm status` 再 restart；能 `--dry-run` 先 dry-run（注意：本仓清库脚本曾把 `--dry-run` 写成真执行，护栏本身也要核实）。
3. **回滚路径是什么？**说清改坏了怎么恢复（备份在哪、上一个 commit、服务如何回到原状态）。**说不出口 = 不许动手。**
4. **动的是"声明要写"的开关吗？**`--allow-prod-write` / `ERP_ALLOW_PROD_WRITE=1` 是「我真的要写」，不是「试试看」——**测护栏时绝不能授权写**（2026-10-03 因此往生产插过 3 行测试数据）。
5. **工作区有别人的活吗？**并发会话常同时写本仓；`git status` 看到陌生改动**先问，别 stash/回退**（曾误判成"测试残留"把用户的活 stash 走）。自己的活也要紧：**改完立刻 `git add`**——并发提交时 pre-commit 的 stash/restore 会偶发崩溃，把未暂存内容整体退回 HEAD（2026-10-21 一次吞掉 21 个文件；恢复与预防见 [docs/agents/verification-and-review.md](docs/agents/verification-and-review.md) §6）。
6. **重启后端 = 把「工作区当前签出的代码」跑进生产。**`erp-prod` 是 `python -m fastapi_app.core.prod_runner --no-arq`，**直接吃 `D:\erp_system` 工作区的源码**，不是打包产物也不是固定 commit——**工作区不在 main 时重启，就把那条分支的代码跑进了生产**（2026-10-14：工作区在 `claude/mystifying-*` 分支期间重启了后端，生产 API 08:26–09:43 一直返回旧字段 `order_nos`/日期-only，而前端已是新版 → 页面「订单号」整列空白、跨行合并不生效；前端新+后端旧这种"半坏"状态最容易只往前端查）。重启前先 `git rev-parse --abbrev-ref HEAD` 确认在 main；重启后核实**到底加载了哪份代码**——**主判据是字段指纹**：`grep` `fastapi_app/**/__pycache__/*.pyc` 里的字段名（如 `order_no` vs `order_nos`）即可判定新旧。**pyc 的 mtime 只能说明「导入不早于该时刻」**（CPython 只在源码比 pyc 新时才重编译，同一份代码重复导入**不会**刷新它——实测两次导入 mtime 不变、改源码后才变），它给的是「这份代码被编译的时刻」，不是「本次进程的导入时刻」；`prod_runner.json` 的 `started_at` 会骗人，别信（§6.1-7 同理）。
7. **验证过"真的做了"吗？**NSSM 非提权调用**静默失败且退出码仍 0**；重启是否生效只看 PID CreationDate，不看命令回显。
8. **结论记档**：按 §8 回写。
9. **改到一半的后端代码别留着过夜/别在这期间重启。**第 6 条管「工作区在别的分支」，本条管**同一分支内未提交的半改代码**——`erp-prod` 吃的是 `D:\erp_system` 工作区源码，**未提交改动同样会跑进生产**。实例（2026-10-22 05:47）：`94194d2d` 的 `purchase_order_revoke.py`（改成 `from fastapi_app.services.order_utils import compute_order_statuses_batch`）已在工作区，而同提交里的 `order_utils.py`（新增该函数）尚未就位 → 后端重启后 `ORDER_DELETED` 处理器每次删除订单都 `ImportError`，**连崩 8 次**（日志 `ORDER_DELETED 处理失败 ... cannot import name`）→ 该订单的 pending 采购单没被撤销 → 客户订单 10-22 已删，采购中心 `/purchase` 仍挂着 `PO-20261010-0001`。**比第 6 条更阴**：接口不报错、页面不提示，只是该联动的清理静默没发生，直到用户发现"我没有这订单"才暴露。判据：**后端重启后先 `grep` 一遍日志里的 `处理失败` / `ImportError`**；半改代码跨文件（一个文件改了 import、提供者还没改）时，**两个文件一起提交或一起回退，别只提交一半**。

### 6.2 分析方法与历史踩坑（外置）

代码分析的坑（`ast` 解析、全仓导入判死代码、过期报告、终端 shell 默认 `pwsh` 7 而非 5.1、git-bash 无 python）见 **[docs/agents/pitfalls.md](docs/agents/pitfalls.md)**——**动手分析代码前读它**；新增分析类教训写该文件，不塞回根文件（理由见 §8）。

## 7. AI 工具痕迹治理

根目录曾被 15+ 个 AI 工具痕迹污染，以下已在 `.gitignore` 忽略，**不要提交**：
`.agent/ .claude/ .cursor/ .graphflow/ .graphflow-cache/ graphflow-out/ .trae/ .qoder/ .workbuddy/ .reasonix/ .superpowers/ .codebuddy/ .freebuff/ .lean-ctx/ .resultverify/ .codeartsdoer/ .zcode/ .zcodeignore dsh-web-dump-config.txt`

`.zcodeignore` 是 `.gitignore` 的派生文件（自述），入库会制造第二真相源，同样忽略（2026-10-05）。

`AGENTS.md`（本文件）、`.windsurfrules`、`GEMINI.md`、`.github/copilot-instructions.md` **刻意不忽略**——它们是协作契约。

## 8. 本文档的元规则

- **能做成门禁的规则，不要只写在文档里。**只写两类：门禁拦不住的（环境事实、事故教训、判断口径）和门禁的位置索引。代码风格/命名/格式由 ruff、eslint、quality_gate 强制，本文件不重复（重复会制造第二真相源）。
- **入档判据**：「少了这行，agent 会不会犯错？错在哪次真实事故？」答不上来就别写——每条都应能追溯到一次事故或一个不可推导的环境事实。
- **事故必须回写**：**运行期事故**追加到 §6.1，**分析类教训**追加到 `docs/agents/pitfalls.md`。不回写，教训只活在修它的那次会话里。
- **控制常驻体量**：根文件目标 **≤150 行**（业界共识：超 80–100 行 agent 会开始忽略部分内容；Codex/Devin 另有 32 KiB 静默截断硬上限，且是全链共享预算）。新增内容优先放按需文件，根文件只留指针。

## 9. 可选工具

GraphFlow MCP（`graphflow_*`）可作上下文压缩/规划辅助，**只是工具，不定义本项目约定**。使用时 `rootDir` 传本仓库绝对路径；`graphflow_context` 返回的是提示，不是项目事实。

GraphFlow 的**行为规则**（何时调用哪个工具、`rootDir` 传法）由**用户级** `~/.claude/rules/graphflow.md` 统一提供——该文件是安装器托管的管理块，不要复制到本仓。项目级 `.claude/rules/graphflow.md`（未入库、被 `.gitignore:383` 忽略）只放用户级没有的补充（`graphflow_run` 后的 `report_outcome` 闭环、CLI 回退形式），**不要再往里塞行为规则或安装步骤**——两处写同一件事会制造第二真相源（§8）。

## 10. 终端 shell 约定

**默认用 PowerShell 7（`pwsh`，`C:\Program Files\PowerShell\7\pwsh.exe`），不用 Windows PowerShell 5.1（`powershell.exe`）**，除非明确指定或目标脚本只兼容 5.1。理由：5.1 的编码/语法坑（`-Encoding utf8` 写 BOM、无 `-AsByteStream`、中文脚本解析阶段 `ParserError`、内联 `if/else` 塞字符串插值后**整段静默不执行**）会触发命令报错 → 重试 → 浪费 token 与调用额度；细节见 [docs/agents/pitfalls.md](docs/agents/pitfalls.md) §4。

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
ruff check .                      # lint（ruff.toml）
mypy                              # 类型（mypy.ini）
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

- **pytest 必须提权跑**：根 `.env` 的 ACL 只授予 Administrators/SYSTEM，非提权跑会因 conftest 读不到 `.env` 整批假红（连的是真实测试库 `erp_system_test`，非派生库）。正路：提权跑 `logs/_run_pytest_elevated.ps1`（2026-10-12 实测全量 4353 passed / 271 skipped）；非提权只读场景用「stub .env 为空流」脚本绕。**全量 pytest 必须独占单实例**——两进程共用 `erp_system_test` 会互撞假红（`DROP SCHEMA` + 硬编码 `SO-PERF-*`，见 `docs/agents/pitfalls.md` §7）。
- **vitest 要把 TEMP 指进仓内**（如 `frontend-vite/.vitest-tmp`），否则 EPERM mkdir 导致全部 0 test 失败；前端构建用 `npm run build:atomic`，esbuild 需 `ESBUILD_BINARY_PATH` 指外部副本，绕开 `%TEMP%` 删除限制。
- **pip-audit 阶段性口径（2026-10-02 起）**：CI 该步骤是 `--report` 只报告不判负（172 条漏洞中 166 条已有修复版，正解是升级依赖）。**不要**为过门禁批量登记豁免；依赖升级后再收紧。
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

### 验证铁律（证据先于断言）

AI 说"修好了/应该没问题/测试过了"而实际没跑，是最高频的 bug 来源。**没有当场跑出的证据，不得声称任何状态**（源：superpowers verification-before-completion）：

| 想声称 | 必须先有 | 不算证据 |
|---|---|---|
| 测试通过 | 本次跑出的 `0 failures` | 上次跑的、"应该通过" |
| bug 已修 | **复现原症状的测试**由红变绿 | 改了代码就当修好 |
| 构建/门禁通过 | 对应命令 exit 0 | lint 过了推 build 也过 |

- 说"应该/大概/看起来"即违规信号——当场跑，用输出说话。
- **修 bug 必须配回归测试**（Red→Green）：先写复现的失败测试、看它红，再修到绿；没看过红就不知道测没测对。逻辑 bug（算错金额、口径漏分支、删除路径漏关联）门禁拦不住，唯一防线是**改动对应的测试**——答不出"哪条测试证明这次改动"的提交不完整。
- owner 问法：不问"代码对吗"，问「**这次改动配了哪条测试、当场跑给我看**」。

### 修 bug 铁律（根因先于修复）

最隐蔽的产 bug 方式是**打症状补丁**：bug 在 A 处、却在 B 处盖住报错，根因还活着，换个场景再炸。**根因调查没完成，不许动手修**（源：superpowers systematic-debugging）：

1. **先复现后修复**：不能稳定触发的先取证，不许猜。
2. **逐层取证、定位到层**：多层系统（前端→API→服务→库）先看每层边界的数据进出，确认哪层断的——不是哪层报错就修哪层。
3. **沿调用链回溯到源头**修，不在症状处修；修完问「同类路径还有没有别处会犯」。
4. **禁止连试带猜**：换了 2 个修复还没好 = 根因没找对，回第 1 步，别试第 3 个。

- owner 问法：让 AI **用一句人话讲清"根因是什么"**；只描述改动、讲不清根因的 = 症状补丁，打回。
- 修完必须配回归测试（见上），并按 §8 回写根因。

### 假测试甄别（绿了不等于测了）

"哪条测试、跑给我看"拦不住**假测试**——永远绿的测试当场跑也是绿的（源：superpowers writing-good-tests）：

1. **镜像断言**：期望值由被测代码（或其 helper）自己算出——`expect(f(x)).toBe(f(x))` 恒真。期望值必须**手工推导**（字面量/手算夹具）。
2. **mock 存在性断言**：断言"mock 挂上了/被调了"，真组件从未被测。mock 只替**慢/外部**依赖，行为断言永远落在真组件上。
3. **从没红过的测试**：没看过失败的测试无法证明它会失败（可能一直恒真）。

- 每条测试要能说出**它拦哪种出错**（错分支/漏副作用/边界/契约破坏）；说不出 = 不该有这条测试。
- **变异检查**：交付前把被测代码改坏一处（错常量/错分支/漏校验空输入），对应测试**必须能红**；没有测试会红 = 该行为无保护。
- 只被测试调用的夹具/清理逻辑放测试工具，**不上生产类**。
- owner 问法：「**把这条测试测的行为故意改坏，跑给我看它变红**」——红了是真测试，没红整条打回。

### 合并前评审（新眼睛原则）

写代码的 AI 评审自己会**确认偏误**（它记得自己的理由）。合并/部署前必须由**未参与实现的新鲜上下文**评审：只看 diff + 需求原文，不带实现的推理（源：superpowers requesting-code-review；BMAD：评审者以找问题为职责，"零发现"须触发重审）。

- owner 问法：「**让一个没参与的新会话独立评审这个 diff，找出影响正确性的问题**」；别问"你觉得没问题吗"（它一定说没问题）。
- **本仓提交前固定用 `/open-code-review:delegate-review`**（OCR 委派模式：OCR 定文件与规则、AI 执行评审）做独立评审：**无问题 → AI 直接代跑提交；发现问题 → 逐条列出并说明怎么修**。**执行评审的子代理一律用最强模型，并迭代审核**（修复后复审直到零 High/Medium）。它是 AI 执行的评审，提交钩子无法机械判定通过与否，故只作规则、不作门禁（§8 例外）。

- `quality_gate.py` 读 `pyproject.toml [tool.code-quality]`：`max_function_length=80`、`max_vue_component_length=400`、`max_file_size=1600`。**只拦新增违规**；清理存量后可 `--update-baseline` 收紧。
- 提交钩子 `core.hooksPath = .githooks`。`.githooks/pre-commit` 四层：①危险路径 ②密钥扫描（**总是跑**）③Python 字面量收窄 ④`.pre-commit-config.yaml`（`ruff --fix` + local `quality-gate`；`ruff-format` 已于 2026-10-01 移除，理由见该文件注释）。
- 第 ④ 层：`pre-commit` 在项目 `.venv`（4.6.2，git-bash PATH 通常看不到）。钩子按 **venv → PATH** 解析并以 `.venv/Scripts` 为 PATH 前缀，使 `entry: python scripts/quality_gate.py` 用 venv 解释器；落到系统 Python 会让 pip-audit 混扫整机依赖判 FAIL、挡掉所有提交（2026-10-01 实测 172 条）。
- `pre-commit` **自身跑不起来时**（本机实测：hook 环境需联网 clone，而 python 派生的 MSYS `ssh/sh` 报 `NtCreateDirectoryObject 0xC0000022`），钩子回退跑等价本地检查：`ruff check --fix`（仅暂存 `.py`，改动即拒绝、需重新暂存）+ `quality_gate.py`。回退照常拦真实违规，但**不因工具跑不起来而拦截**；只有 pre-commit 真失败（输出含 `- hook id:`）才按它判负。
- `.githooks/commit-msg`（第 5 层）：**剥掉第三方 AI 工具署名尾行**（`🤖 Generated with <tool>` / `Co-Authored-By: <tool>`，清单见该文件）。背景：Codebuff 曾写进 12 个提交（2026-08-11 起），与 §7 相悖；就地剥离不阻断工作流。**故意不剥 Claude 的署名**。
- 密钥扫描误报的**正确**处置：命中行尾加 `secret-scan:allow <理由>`（或上一行 `secret-scan:allow-next-line`）；`.githooks/allowlist.txt` 是逐文件豁免，**新增条目须在提交信息说明理由**。
- 提交信息写**为什么**；一个提交只做一件事；提交前 `git status --porcelain` 确认没卷进 AI 痕迹或运行期数据。
- 迁移：**禁止对生产库 `alembic revision --autogenerate`**（生产有历史漂移，会生成 `DROP INDEX/TABLE/COLUMN` 破坏性 DDL）。需生成时先在**临时空库** `upgrade head`，改模型后对空库 autogenerate，判据同 CI（空库 `upgrade head` + `check`）。新增破坏性 DDL 会被 `fastapi_app/tests/test_migration_autogenerate_safety.py` 拦下。详见 `migrations/README`。

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
5. **工作区有别人的活吗？**并发会话常同时写本仓；`git status` 看到陌生改动**先问，别 stash/回退**（曾误判成"测试残留"把用户的活 stash 走）。
6. **验证过"真的做了"吗？**NSSM 非提权调用**静默失败且退出码仍 0**；重启是否生效只看 PID CreationDate，不看命令回显。
7. **结论记档**：按 §8 回写。

### 6.2 分析方法与历史踩坑（外置）

代码分析的坑（`ast` 解析、全仓导入判死代码、过期报告、PowerShell 5.1、git-bash 无 python）见 **[docs/agents/pitfalls.md](docs/agents/pitfalls.md)**——**动手分析代码前读它**；新增分析类教训写该文件，不塞回根文件（理由见 §8）。

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

# 全面代码质量与安全评审 — 2026-10-05

> 评审方式：Mimosa 深度静态扫描（密封产物）+ 项目自身全量质量门禁 + 依赖审计 + 人工抽查复核。
> 本文件是当日评审的现行结论；旧报告（如 architecture-review-2026-10-01.md）中与本文件冲突的结论以本文件为准。

## 0. 扫描凭证（Mimosa）

| 项 | 值 |
|---|---|
| scanId | `scan-2026-10-05T05-12-26.184Z-f455d7c0aebc` |
| seal | `sha256:286d9093dff2679fd48050bdad8a32345e179f5b101cb3157943a4e65ac27098` |
| 产物目录 | `C:\Users\Administrator\.mimosa\security-scans\project-2d23cc09849589f81d4aaf4e\scan-2026-10-05T05-12-26.184Z-f455d7c0aebc` |
| 覆盖度 | `completeness: partial`（threatModel / findingDiscovery / pathAnalysis 三阶段 partial）→ **按扫描契约，不构成"项目整体安全/无风险"结论** |
| 原始 finding | 1920 条（high 487 / medium 1366 / low 67） |
| 依赖扫描 | 931 包；离线公告匹配 2 包 2 条 |

## 1. TL;DR

代码本身质量**良好**：后端 mypy 全绿、3862 项 pytest 仅 2 失败（且是环境问题不是代码问题）、前端 vitest 1155 全过、服务层被标记的"SQL 注入/路径穿越"经人工抽查**均为误报**。真正要处理的是三件事：

1. **P0 · 生产环境漂移**：`erp-web`(nginx) 服务 STOPPED，3000 端口被另一 RDP 会话的 vite dev（node.exe PID 17268）占用，线上现在由 dev server 顶班。回归测试 D1 探针当场抓到。
2. **P0 · Python 运行环境落后于 requirements 钉版**：装机 Pillow 12.2.0（钉版 ≥12.3.0，25 条已知漏洞）、PyJWT 2.13.0（钉版 2.15.0，13 条）。同步环境即可消掉一大批漏洞。
3. **P1 · 前端 axios 存在 1 条 high 公告**（含 SSRF/头注入系列），`npm audit fix` 可修。

## 2. 质量门禁矩阵（2026-10-05 实测）

| 门禁 | 结果 |
|---|---|
| `python -m mypy` | ✅ 0 错误（368 文件） |
| `pytest -q` | ⚠️ 3862 过 / 181 跳 / **2 失败**（均为 D1 nginx 探针，见 §3） |
| `npm run type-check`（vue-tsc） | ✅ 通过 |
| `npm test`（vitest） | ✅ 1155/1155（126 文件） |
| `npm run lint` | ✅ 0 error / 171 warning（多为 `vue/attributes-order`，可 `--fix`） |
| `npm run check:api` / `check:routes` | ✅ 双端一致 |
| `ruff check .`（全仓） | ⚠️ 99 处（门禁基线口径 scripts/+server_manager/ 的 59 处与基线持平） |
| `scripts/quality_gate.py` | ❌ FAIL：pip-audit 豁免策略 0→104（其余项 OK 或 TIGHTEN 收紧中） |

TIGHTEN 项（好趋势）：后端超长函数 51→42，前端巨型 Vue 组件 7→6。可在清理后用 `--update-baseline` 收紧。

## 3. 生产环境漂移（评审期间实测发现）

- `sc query erp-web` → **STOPPED**；`netstat` 显示 0.0.0.0:3000 由 **node.exe（PID 17268，RDP-Tcp#2 会话）** 监听。
- `http://127.0.0.1:3000/nginx-health` 返回 Vite dev 的 index.html（含 `/@vite/client`、`/src/main.ts?t=...`），不含 `"service":"nginx"` 标记 → `test_qa_prod_stack_regression.py::TestD1ProbeFalsification` 两条断言失败。这两个失败是**正确的报警**，不是测试误报。
- `logs/prod_runner.json` 仍写着 `ready:true / frontend_ok:true`（陈旧快照），说明该文件在漂移后未刷新，不能作为当前健康依据。
- 处置流程沿用既有约定（见 memory `deploy-verify-live-hash-after-build`）：先关掉占用 3000 的那个 dev 会话（勿循环强杀），再启动 erp-web，最后 curl 比对 dist hash 并复查两条 D1 测试转绿。

## 4. 依赖风险

### 4.1 Python（pip-audit，现场全环境 172 条；门禁口径 104 条）

- **关键归因：装机版本落后于 `requirements/base.txt` 钉版。**
  - `Pillow` 装机 12.2.0，钉版 `>=12.3.0,<13`（25 条漏洞，含多项 CVE）
  - `PyJWT` 装机 2.13.0，钉版 `2.15.0`（13 条）
  - 也就是说一部分漏洞不是"依赖选错了"，而是"环境没按 requirements 升级"。
- 其余大头（aiohttp 3.13.3×48、litellm×14、tornado×13、mcp×6、werkzeug×6、virtualenv×8 等）经与 requirements 比对**均非应用声明依赖**，来自全局 Python 环境里的开发/AI 工具链（litellm 还会拖入 aiohttp）。多数有补丁版可升（如 aiohttp 3.13.3→3.13.4）。
- 门禁层面二选一：要么把 pip-audit 收窄到 requirements 依赖集（推荐，豁免数大概率归零），要么按门禁既定规则逐条写 `id+reason+expires(≤180d)` 豁免——门禁自己已声明"修复方式是升级依赖后删掉豁免，而不是续期"。

### 4.2 前端（npm audit --omit=dev）

- **1 条 high：axios**（原型污染 gadget、HTTP/2 绕过 DNS/代理、头注入、fetch 适配器 `maxRedirects:0` 不生效致 SSRF 等一组 GHSA），`npm audit fix` 有修。升级后跑 vitest + type-check 回归。

## 5. Mimosa 1920 条 finding 的去噪归因

原始 high 487 条，**其中 346 条位于 `backups/`**（历史前端 dist 压缩包被当源码扫）、29 条位于 `frontend-vite/dist_prev_*`/`dist-old-swap`（旧构建产物）、27 条在 `_ops` 归档 —— 合计约 83% 为构建产物/归档噪音。**建议：Mimosa 项目配置中排除 `backups/`、`frontend-vite/dist*`、`_ops/`、`temp/`、`docs/`，可让后续扫描信噪比提升一个量级。**

剔除噪音后，真实后端代码（fastapi_app/utils/scripts/server_manager/migrations）high 共 76 条，逐类人工抽查结论：

| 类别 | 条数 | 抽查结论 |
|---|---|---|
| sql-injection | 29 | **误报为主**。迁移脚本为字面量 DDL/seed 拼接（无用户输入）；服务层抽查 `enhanced_pagination.py:83/89/120`（SQLAlchemy 表达式 API）、`production_summary_service.py`（`escape_like()`+ORM 条件）、`backup/ro_grants.py` 均为参数化/表达式写法，且代码里已带 `# sql-safe:` 注释 |
| path-traversal | 37 | 运维脚本按 CLI 参数拼路径（本地工具，风险可控）；fastapi_app 侧抽查 `core/atomic_write.py:58`、backup 各 service 的路径均来自内部配置而非 HTTP 入参 |
| ssrf | 6 | 全部在 scripts（build_and_release / watchdog / verify_perf_cache_v2），本地运维出网，可接受 |
| hardcoded-credential | 4 | **均为误报**：`scripts/_selftest_hook.py:81-87` 是密钥扫描器自测夹具（故意埋假凭据防扫描器变松）、`scripts/scan_secrets.py:86` 是扫描器自身的检测模式串 |

（扫描 coverage 为 partial，以上"误报/可接受"仅针对已检出的范围，不外推整体。）

## 6. 待办建议

- **P0（环境，不动代码）**
  1. 恢复 3000 = nginx：关 dev 会话 → 启 `erp-web` → curl 比对 hash → D1 两条测试转绿。
  2. 按 `requirements/base.txt` 同步生产 Python 环境（`pip install -r requirements/base.txt`），优先消除 Pillow/PyJWT 的旧版漏洞；升级属生产变更，挑低峰窗口做，改完跑 pytest 回归。
- **P1**
  3. `cd frontend-vite && npm audit fix`（axios high），回归 vitest/type-check 后 build 上线。
  4. quality_gate pip-audit 策略二选一（收窄口径 / 限时豁免清单）。
- **P2**
  5. Mimosa 扫描排除 `backups/`、`dist*`、`_ops/`、`temp/`。
  6. `npm run lint -- --fix` 清 171 条 attributes-order warning；随后 `--update-baseline` 收紧超长函数（42）与巨型组件（6）基线。
  7. `frontend-vite/src/views/supplier/SupplierView.vue` 有未提交改动（评审开始即存在），确认意图后入库或丢弃。

---

# 复审 — 2026-10-05（生产模式恢复后）

> 触发：用户宣布已恢复生产模式，按计划重跑环境核验、回归门禁与 Mimosa 深度扫描，与晨间首轮对比。
> SupplierView.vue 的改动已在 `c7fe7212`（supplier/user 页去圆角）入库，本轮无未提交源码改动。

## R1. 环境核验 ✅ P0-1 已解决

- `sc query erp-web` → **RUNNING**（STATE 4）。
- 0.0.0.0:3000 两个监听 PID（9948 / 22312）均为 **nginx.exe**（主进程 + worker），无 dev server。
- `curl --noproxy '*'` 对 `127.0.0.1:3000` 与 `192.168.0.95:3000` 双验 `/nginx-health`，均返回 `{"status":"ok","service":"nginx"}` 标记。

## R2. 回归确认 ✅

- D1 探针 `TestD1ProbeFalsification`：**4/4 通过**（晨间因漂移失败的 2 条转绿）。
- 全量 `pytest -q`：**退出码 0**（无失败；"no tests ran" 会返回 5、收集错误返回 2）。

## R3. 门禁与依赖现状

| 项 | 状态 | 与晨间对比 |
|---|---|---|
| `scripts/quality_gate.py` | ❌ FAIL | **不变**：仍仅 pip-audit 豁免策略一项 0→104（豁免 0 条）；其余 OK 或 TIGHTEN（超长函数 42 / 巨型组件 6） |
| Python 环境同步钉版 | ❌ | **不变**：pillow 12.2.0（钉 ≥12.3.0）、PyJWT 2.13.0（钉 2.15.0）、aiohttp 3.13.3 均未动 → **P0-2 仍开放** |
| 前端 axios | ❌ | **不变**：`npm audit --omit=dev` 仍 1 high → P1 仍开放 |

## R4. Mimosa 重扫凭证与对比

| 项 | 晨间首轮 | 本轮复审 |
|---|---|---|
| scanId | `scan-…-f455d7c0aebc` | `scan-2026-10-05T06-03-55.854Z-9c1a000beab4` |
| seal | `sha256:286d9093…c27098` | `sha256:a3bdc735…b00b02` |
| finding 总数 | 1920（high 487 / medium 1366 / low 67） | **完全一致** |
| 去噪后真实代码 high | 76（路径 37 / SQL 29 / SSRF 6 / 凭据 4） | **完全一致：零新增、零消除** |
| coverage | partial / inconclusive | **不变**（validation、reporting completed） |

结论：扫描引擎确定性成立，源码自 `c7fe7212` 后未变，两轮互为印证；上轮 §5 的误报归因（SQLAlchemy 表达式 API、escape_like、扫描器自测夹具等）原样适用。coverage 仍为 partial，依旧**不构成"项目整体安全"结论**。

## R5. 复审后的待办状态

- ~~P0-1 恢复 3000 = nginx~~ → **已解决**（R1）。
- **P0-2** 按 requirements 同步生产 Python 环境 → **仍开放**（pillow/PyJWT/aiohttp 均未升级）。
- **P1-3** axios `npm audit fix` → 仍开放；**P1-4** quality_gate pip-audit 口径二选一 → 仍开放。
- **P2**（Mimosa 排除噪音目录、lint --fix + 收紧基线）→ 均未动，建议照旧。

---

# 执行记录 — 2026-10-05（P0-2 / P1-3 修复落地）

## E1. 关键定性修正：生产 venv 本就干净

- NSSM 服务参数（`HKLM\...\Services\erp-prod|erp-arq\Parameters`）显示生产解释器是 **`D:\erp_system\.venv\Scripts\python.exe`**（OPT-08 venv 迁移已落地），不是全局 Python。
- `.venv` 与 `requirements/base.txt` 37 条钉版**全部相符、零漂移**（含 uvicorn/psycopg/redis/sentry-sdk 的 extras 形式；aiohttp 3.14.3 为新版）。
- → 晨间 P0-2 的定性需要修正：**带洞的是全局 Python 3.13**（承载开发/运维工具链，且恰好是 quality_gate 里 pip-audit 的审计对象），生产运行时本身无此问题。

## E2. 已执行的修复

| 动作 | 结果 |
|---|---|
| 全局环境外科手术升级 | pillow 12.2.0→**12.3.0**、PyJWT 2.13.0→**2.15.0**、aiohttp 3.13.3→**3.14.3**（与 .venv 完全一致；仅升级三件，未动整个工具链。pip 提示的 litellm/msal 依赖冲突为全局工具链既有状态，非本次引入） |
| axios 升级 | `npm audit fix`：1.18.0→**1.20.0**（package.json 的 `^1.18.0` 未变，仅 package-lock 变更，**未提交**）；`npm audit --omit=dev` = **0 漏洞** |
| 前端回归 | type-check ✓；vitest **1155/1155** ✓ |
| 后端回归 | 全量 pytest **3864 passed / 181 skipped，退出码 0**（含晨间失败的 2 条 D1 探针；本轮显式从仓库根运行并用 PIPESTATUS 校验真实退出码——此前两次"通过"实为 cwd 漂移到 frontend-vite 导致 collected 0，被管道尾 exit code 掩盖） |
| build 上线 | PWA 206 项预缓存；双地址 live hash 与 dist **一致**（`9577e1d1…`），`/nginx-health` OK —— axios 1.20.0 已生效 |
| quality_gate 复跑 | pip-audit 豁免数 **104 → 54**（三件升级清除 50 条），仍 FAIL：剩余 54 条全部来自全局工具链包（litellm/tornado/mcp/werkzeug/virtualenv 等），豁免仍为 0 |
| 服务影响 | **未重启任何服务**：erp-prod/erp-arq 本就运行 .venv 中已同步的版本；全局包升级只影响开发/运维工具链进程 |

## E3. 待办状态（执行后）

- ~~P0-1 恢复 3000 = nginx~~ → 已解决（R1）。
- ~~P0-2 Python 环境同步~~ → **已解决**（E1 定性修正 + E2 升级；生产 venv 零漂移，全局环境三件已对齐）。
- ~~P1-3 axios high~~ → **已解决**（1.20.0 已上线，生产依赖 0 漏洞）。
- **P1-4 quality_gate pip-audit 口径** → 仍开放，且新证据强化了推荐方案：**门禁应审计生产解释器 `.venv`**（既正确——它才是生产运行时，又几乎必然把豁免数打到 0），全局工具链的 54 条属开发机卫生问题，不宜阻塞提交门禁。
- **P2**（Mimosa 排除噪音目录、lint --fix + 收紧基线、`.zcodeignore` 入库）→ 未动。
- package-lock.json（axios 1.20.0）有未提交变更，待确认后入库。

---

# 建议执行记录 — 2026-10-05（剩余事项处置）

| # | 事项 | 结果 |
|---|---|---|
| 1 | 提交 axios lockfile | ✅ `0f7a0541`（精确 add 单文件，避开另一会话在制改动） |
| 2 | P1-4 门禁口径 | ✅ `0929e2c1`：`load_vuln_ids` 改为 `.venv/Lib/site-packages` 存在时用 `pip_audit --path` 审计**生产运行时**（实测 0 漏洞），无 .venv 回退旧行为；全量 quality_gate **首次 [PASS]**（ruff 59 处与基线一致，零新增；mypy 通过）。豁免策略与 `--audit-report` 通道不变 |
| 3 | .zcodeignore/.zcode/ 治理 | ✅ `c46de6b8`：两者加入 `.gitignore` + AGENTS.md §7 清单（.zcodeignore 是自述"同步自 .gitignore"的派生态，不入库） |
| 4 | lint --fix + --update-baseline | ⏸ 按建议暂缓：另一会话在制中（CustomerTable/SupplierTable/UserTable + scripts/diag 探测脚本），待其收尾后独立提交执行 |
| 5 | 旧 dist 回滚点移出仓库 | ⛔ **被有意的防误删 ACL 拦截**：`dist-old-swap` 等目录上有 `Everyone:(DENY)(S,DC)`（9-30 dist 交换事件时设置的守护，目录级改名/移动被拒；目录内单文件读写正常）。按"发现保护先报告"原则不动。若确认要挪：需提权 bat 先 `icacls` 移除 DENY 再 move——等用户决策 |
| — | quality_gate 现状 | 全绿；仅剩 TIGHTEN 两项（超长函数 42/基线 51、巨型组件 6/基线 7），待第 4 项一起收紧 |


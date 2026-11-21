# 审计执行复盘（2026-11-21，retro 输入）

> 对象：本轮全量审计+修复的执行过程（fix/audit-full-20261121，25 commits）。
> 产出两类：可固化为门禁/脚本的 → 列入「固化清单」；门禁拦不住的判断口径 → 本文档记录。

## 1. 做对了什么（保持）

1. **分区审计 + 亲验**：14 个只读子代理分区 + 主会话逐条亲验 H/M，抓出 1 条误报（saveBom 并发——子代理漏读 3 行外的守卫）。「新眼睛」双向适用：审代码的人也要被验。
2. **阶段 2 探针先于定级**：`show timezone` 一条 SQL 促成 2 条 H→M 降级——分级口径回归「什么条件下会错」，避免虚惊。
3. **真 Red 纪律**：每个修复单元 stash 修复跑 Red 再 pop 跑 Green（或前置校准），共 15+ 轮；抓出 3 次「错因巧合的假 Red」（如 core 路径产品查询返回空）。
4. **门禁反向把关**：quality_gate 棘轮 3 次拦下修复自身引入的函数超长——逼出 3 次更好的拆分（流式 helper、_json_contains_trusted、walrus）。

## 2. 执行中的坑（对策）

| 坑 | 现象 | 对策（已沉淀/待沉淀） |
|---|---|---|
| 提权 pytest 三层引号 | git-bash→pwsh→Start-Process 引号失真 | 统一走 `elevated_cmd.ps1 -RepoCmd`（已验证） |
| conftest 双树 | 根 tests/ 与 fastapi_app/tests/ 夹具不通（async_db_session/app_on_test_db/auth_headers） | 集成型测试放根 tests/；纯单元放 fastapi_app/tests/——**新写测试前先想清楚用哪个夹具**（本次 2 次挪文件） |
| 编号内核独立短事务 | 测试直接调 service 会「数据库引擎未初始化」 | 挂 `app_on_test_db` 夹具（重定向 URL）+ `ensure_engine_for_current_loop()` |
| mock 编排脆弱 | 新增一次 execute 就 StopIteration | **测试断言「行为」而非「execute 次数」**；确需编排的（A-M19 类）在注释里写清每段对应 |
| 行号锁定断言 | stats.py 插 2 行 → 三个测试红 | 改用 AST 定位或锚定上下文行（本次两次追平行号，固化清单 §3） |
| 子代理配额中断 | 两个清扫代理 140+ 调用后被打断，留下半成品 | 中断后先 AST 全量验证 + ruff + 聚焦测试，**再决定续做或收口**（本次续接成功） |
| .env 非提权拒读 | import 链读 .env 的脚本非提权跑不了 | 一律走提权通道；只读探针写进提权脚本 |

## 3. 固化清单（可做成门禁/脚本的）

| # | 提案 | 形态 | 优先级 |
|---|---|---|---|
| 1 | **pydantic 无界列表检查**：`list[X]` 字段无 max_length 即报（本次 M-18 门禁盲区） | quality_gate 新 gate（AST） | 高 |
| 1b | **schema 改动三件套门禁**：改 `schemas/*.py` 后 openapi.json/api.d.ts/buster 三者不同步即拦——本次同一教训**两轮复发**（评审 M-1 漏重导、14695302 改默认值又漏），本地 check:types 读过期快照互相印证失效，只有 CI 全指纹比对能拦。做成 pre-commit：`git diff --name-only | grep schemas/` 时跑三件套校验 | pre-commit hook | 高 |
| 2 | **naive datetime 比 timestamptz 检查**：`column >= datetime(y,m,d)` 形态扫描（M-41 族根因） | quality_gate 新 gate（AST，列型映射表） | 中（误报需调） |
| 3 | **行号锁定断言检测**：测试断言含 `file.py:NNN` 字面量时提示改 AST 锚定 | 提示性检查（不阻断） | 低 |
| 4 | **前端孤儿模块门禁**：check_orphan_modules 只扫 Python；前端死组件/死 composable 零消费不报（本次 4 处） | 前端 check 脚本（knip 或自写 import 图） | 中 |
| 5 | **mock 编排健康度**：`side_effect=[...]` 长度 ≥5 的测试标记「编排脆弱」提示 | 提示性检查 | 低 |
| 6 | 提权测试助手统一入口 | 已存在（elevated_cmd.ps1 + _run_pytest_elevated.ps1），写进 AGENTS §4 或 pitfalls | 高（纯文档） |

## 4. 判断口径（门禁拦不住，记录在此）

1. **两条路径语义可以不同**：Excel 导入「小数一律拒绝」（H-1）vs OCR「小数四舍五入」（暂存行有人工确认）——不要为了「统一口径」强行拉齐，先问触发场景是否有兜底。
2. **响应字段可以变多**：修安全/可追溯缺口（L-14 幂等重放带 order_no）时，响应多字段是行为改进，前端按字段读取不受影响——测试期望更新不算「破坏契约」。
3. **测试编排更新≠测试弱化**：为行为精进而改 mock/期望（如 factory 透传、reset 链）必须逐条核对「新期望对应新行为」——本次 13 处全部对应真实修复。
4. **「注释化处理」是合法产出**：等 owner 裁定的取舍（stats 工厂口径、base64 密码等）标记进报告，不算未完成。
5. **基线只下调**：semantic_guards 46→45 是修复记账；上调仍需 owner 书面同意（code-review-standard §7）。

## 5. 数字

- 审计：14 分区代理，5 H（撤 1 误报）、42 M、31 L、26 N + 假测试 6 + 性能 12 点。
- 修复：25 commits；2H + 29M（含 2 条 H 降级）+ 假测试 6 + L×20+/N×10+（后端第一波）+ 前端清扫（进行中）+ 15 处回归修复。
- 测试：全量 6494 passed 基线（第一轮 18 failed 全部归因并修复，第二轮验证中）。
- 门禁：全程回基线；bandit 20→19、语义门禁 46→45（双收紧）。
- 未竟：前端 L/N 26 条（代理进行中）；report 导出第二套过滤合并（结构改造，超定点边界，已注释化）。

# 上线前全检报告：main / 0dfb5d77

**日期**：2026-10-25  
**检查对象**：`main@0dfb5d7706049d67689c336f7445d755e9345403`  
**代码评审增量**：PR #13，`d3fe6812c105..0dfb5d77`  
**检查方式**：独立代码审查、OWASP Top 10 + STRIDE 安全审计、QA/CI/发布检查、主理人交叉复核  
**最终裁决**：**No-Go，不应按当前版本上线**

---

## 1. 执行摘要

当前精确 HEAD 的远端 CI、CodeQL、后端测试、前端测试和构建均通过，但人工语义审查与部署完整性审查发现阻断问题。机器门禁全绿不能抵消以下事实：

1. **重启链路可能把“旧进程仍在运行”报告为成功**，调用方随后用不绑定版本的健康检查确认上线，存在旧代码被当作新版本发布的假成功。
2. **finished-stock 多条读写链路缺少工厂数据范围约束**，静态调用链支持跨工厂越权风险；该问题不是 PR #13 新引入，但仍属于当前发布版本的风险。
3. 另有 5 项 Medium，涉及 DLQ 状态假健康、上传边界误拒、DLQ 告警延迟、外发异常未脱敏及 XLSX 资源预算不足。按仓库评审标准，未修复且未获批准延期的 Medium 同样不能静默放行。

### 去重后的最终问题计数

| Blocker | High | Medium | Low | 结论 |
|---:|---:|---:|---:|---|
| 1 | 1 | 5 | 0 | No-Go |

计数口径：

- 代码审查独立结论：B0 / H1 / M4 / L0。
- 安全审计独立结论：B1 / H1 / M3 / L0，另有说明性备注。
- 两角色重复报告的 Redis/DLQ unknown 问题只计一次。
- H-2 checkpoint 回归测试未覆盖目标分支，作为 B1 的验证缺口折叠，不独立计数。
- M-D `BACKUP_RETENTION_COUNT` 无执行点经当前代码复核为假阳性，已排除。
- “同 PID 重启假成功”在代码审查中为 High、安全审计中为 Blocker；总账采用较保守的 Blocker，保留此分级差异供责任人复核。

---

## 2. 范围、基线与安全边界

### 2.1 发布范围

- 检查时 `HEAD == erp/main == 0dfb5d7706049d67689c336f7445d755e9345403`。
- PR #13：44 个文件，有效 `+766/-106`，10 个提交。
- 因当前工作区已在 `main`，评审使用显式范围 `d3fe6812..0dfb5d77`，没有采用会产生空 diff 的 `main...HEAD`。
- 增量主要覆盖：抵扣流水净量过滤、业务时间格式化、ARQ 失败告警和 DLQ 日检、导入体积限制、后端重启脚本、mypy 门禁及空测试清理。

### 2.2 本轮严格遵守的边界

本轮只读检查，未修改业务源码、测试或生产配置，并且：

- 未重启或停止生产服务。
- 未写生产数据库，未调用写入型生产 API。
- 未使用 `ERP_ALLOW_PROD_WRITE` / `--allow-prod-write`。
- 未执行 `alembic upgrade` / `autogenerate`。
- 未覆盖 nginx 正在使用的 `frontend-vite/dist`。
- 未读取或输出 `.env`、`_ops/credentials` 等凭据。
- 未为了让测试变绿而修改代码、测试或环境。

---

## 3. 阻断与高优先级发现

### B1：同 PID 重启可被外层脚本报告为成功，旧代码可能冒充新版本

**统一分级**：Blocker  
**来源**：代码审查 High；安全审计 Blocker  
**主要位置**：

- `server_manager/service_ops.py:742-762`
- `scripts/restart_backend.py:99-115`
- `tests/test_sm_restart_stop_start.py:290-320`
- `fastapi_app/tests/test_write_guard_wiring.py:145-161`

**证据链**：

1. `wait_service_running()` 检测到重启后的 PID 与 `prev_pid` 相同，会记录“本次重启未生效”，但仍执行 `return True, state, pid`（`service_ops.py:756-760`）。
2. `restart_backend.py:104` 丢弃返回的 PID，并且没有消费承载 WARNING 的 `SimpleQueue`；后续只根据 `ok` 和 `/api/health` 判定。
3. `/api/health` 不绑定目标 commit、进程 PID 或进程启动时间。若旧进程一直健康，`restart_backend.py:115` 可返回 0。
4. 既有测试 `test_sm_restart_stop_start.py:304-306` 明确锁定同 PID 时 `ok is True`，证明这不是单纯理论分支。
5. H-2 测试虽然声称保护 `gate=None` 的 checkpoint 分支，但 `state_fn=lambda _name: 'RUNNING'` 会在 `wait_service()` 首次状态检查时直接返回，走不到后续 checkpoint；因此该回归测试没有覆盖其声明目标。

**生产影响**：发布自动化可能显示成功，实际运行的仍是旧代码；后续基于健康状态的验收、灰度和回滚判断都会被污染。

**必须修复**：

- 将“服务终态运行”与“本次重启已生效”拆成不同的结构化结果；同 PID 不得作为重启成功返回。
- 外层脚本必须消费并传播 WARNING/失败原因，不得丢弃 PID 和队列消息。
- 发布验收增加可验证的版本指纹，至少同时核对目标 commit 和进程身份/启动时间；健康 200 本身不够。
- 修复 checkpoint 测试，使状态序列真正经过等待循环，并覆盖 `gate=None`。

**必须补的回归测试**：

- 同 PID + 旧进程健康：脚本必须非零退出，不得显示发布成功。
- PID 改变 + 新版本健康：才允许成功。
- stop 失败、start 失败、健康超时分别失败。
- `gate=None` 且首次非目标态、随后目标态：实际进入 checkpoint 分支且不抛 `AttributeError`。

### H1：finished-stock 读写链缺少工厂范围，存在跨工厂 BOLA/IDOR 风险

**分级**：High  
**归属**：存量问题；PR #13 对该端点仅做响应模型/mypy 调整，没有引入或修复授权范围  
**主要位置**：

- `fastapi_app/api/v1/endpoints/finished_stock.py`
- `fastapi_app/services/finished_stock_service.py:80-82,125-128,153`
- `fastapi_app/services/finished_stock_service.py:315-343,435-443`
- `fastapi_app/services/finished_stock_service.py:555-639`
- `fastapi_app/shared/factory_scope.py:85-143,163-194`

**证据链**：

- summary、batches、export、remark 端点做权限检查，但未从当前用户派生 factory 并传入 service。
- service 的汇总、批次查询、导出和 remark 写删没有 factory 条件。
- `_get_all_customers()` 调用 `_stock_customers(db, None)`，仍未限制工厂。
- 项目已有 `assert_product_factory_scoped()`，但本链未复用； batches/remark 接收调用方提供的 `product_id`，未见对应工厂断言。

**影响**：厂绑定用户只要拥有相应功能权限，就可能读取、导出或修改其他工厂的数据。该结论来自静态调用链，本轮未在生产发起跨工厂请求。

**必须修复与测试**：

- factory 必须由服务端当前用户派生；对厂绑定非超管缺失/空 factory 应明确拒绝，不得退化为全量。
- summary、batches、export、remark 全链传递并强制 factory 条件；产品操作复用 `assert_product_factory_scoped()`。
- 客户筛选、聚合、导出与写删使用同一数据范围口径。
- 使用两个工厂的 HTTP 级测试覆盖列表、汇总、批次、导出和 remark；跨厂按既有契约返回 404，并验证无数据泄漏、无写库副作用。

---

## 4. Medium 发现

### M1：Redis 状态 unknown 被 DLQ 日检当成“空队列/成功”

**位置**：`fastapi_app/core/redis_wrapper.py:218-263`；`fastapi_app/tasks/deadletter_patrol_task.py:83-88`

`safe_llen()` 在 client 不存在、类型错误或基础设施异常时返回 0。DLQ 日检直接消费该整数，无法区分“真实空队列”和“状态不可知”，可能生成空队列结论并让巡检返回成功。

**修复要求**：为巡检提供三态/结构化结果或让基础设施异常显式失败；unknown 必须 `success=False` 并触发可外发的 critical 告警。补 client 缺失、连接失败、错误类型、真实空队列、真实非空队列测试。

### M2：文件上限与 multipart 请求体上限相等，合法近上限文件会被提前 413

**位置**：

- `fastapi_app/api/v1/endpoints/import_guard.py:82,150-159`
- `fastapi_app/api/v1/endpoints/production_summary.py:42`
- `fastapi_app/services/batch_import_parser.py:45-50`
- `fastapi_app/core/middleware.py:47,140`
- `config/nginx-windows.conf:73`

文件上限为 10 MiB，端点按 `>` 拒绝，声明语义允许恰好 10 MiB；但全局请求体和 nginx 也都是 10m。multipart 开销 `O>0`，所以当 `F <= 10 MiB` 且 `F+O > 10 MiB` 时，合法文件会在到端点前被 413。源码注释所称“对齐后不会出现 nginx 先 413”不成立。

**修复要求**：统一文件字节预算和外层请求体预算，外层必须包含明确的 multipart 开销余量，或下调对用户承诺的文件上限；覆盖七个导入端点及 packaging。测试恰好上限、超过文件上限、带/不带 Content-Length 和流式累计边界。

### M3：DLQ 残留仅发 warning，默认前两次日检不会外发

**位置**：`fastapi_app/tasks/deadletter_patrol_task.py:134`；`fastapi_app/services/backup/metrics/alert_service.py:57,134-164`

DLQ 残留使用 `severity='warning'`，默认 `failure_threshold=3`。warning 被计入连续错误次数，首次和第二次通常不满足通知条件；而每日 cron 成功标记会影响后续 catch-up，可能使残留存在但外部渠道静默。

**修复要求**：DLQ 非空使用独立且立即可外发的告警策略，或提升为 critical；不得依赖普通失败计数器的第三次触发。补“第一次发现残留即通知”和“任务自身失败仍 critical”测试。

### M4：ARQ/DLQ 外发告警直接包含异常文本，截断不等于脱敏

**位置**：`fastapi_app/core/arq_callbacks.py:155`

`error=f'{type(exc).__name__}: {exc}'[:300]` 会把异常原文的一部分发往 email/webhook。任务异常可能携带参数、标识符或其他敏感片段，300 字符截断不提供机密性保证。

**修复要求**：集中使用脱敏/字段白名单；外部告警发送通用消息与关联 ID，详细异常仅进入受保护的内部日志。测试构造含密钥样式、业务标识和长异常的消息，断言所有外发渠道均无敏感原文。

### M5：XLSX 解压与解析缺少统一的 CPU、内存及解压后尺寸预算

**归属**：存量问题，相关解析文件不在 PR #13 增量中  
**攻击前提**：持有对应上传权限的已认证用户；文件通过现有扩展名、魔数和压缩体积校验。当前 HEAD 的真实调用链为：

- 包装记录：`POST /packaging/upload`（`production_summary.py:291-327`，要求 `production_summary_manage`）→ `production_summary_service.py:220-230`，`:223` OpenPyXL 读取，`:228` 将行转为完整 `list`。
- 生产计划：`POST /upload`（`production_plan.py:225-259`，要求 `production_plan_manage`）→ `production_plan_service.py:226-239`，`:232` 读取，`:237` 全量物化。
- 采购计划：`POST /upload`（`purchase_plan.py:414-440`，要求 `production_plan_manage`）→ facade/re-export → `purchase_plan_staging.py:39-50,94-98`，`:42` 读取，`:47` 全量物化。
- 批量综合导入：`POST /import-comprehensive`（`batch.py:243-269`，要求 `batch_import`）→ `batch_import_service.py:987-1009` → `batch_import_parser.py:61-109`。其中 `:73/:75` 为 Polars `read_excel()`，`:79` 为 `df.to_dicts()` 全量物化；`:102` 的 OpenPyXL 用于 sheet 枚举。
- `fastapi_app/services/xlsx_cell_images.py:38-40,68-142`：图片提取有 64 MiB 局部上限，但关系/XML 成员读取及整个工作簿解析没有统一预算。

请求体 10 MiB 只限制压缩后的上传大小，不能约束解压后 XML、shared strings、样式、单元格数量和解析耗时。`read_only=True` 也不等于整体资源安全，尤其在结果再次全量物化时。静态确认的是控制缺口和可达调用链；未运行动态 ZIP bomb，实际 DoS 阈值仍未验证。

**修复要求**：建立统一 XLSX 资源策略，至少覆盖 ZIP 成员数、单成员/总解压大小、压缩比、行列/单元格/shared strings 上限、解析超时和结果物化上限；所有导入入口一致执行。使用高压缩比、高 shared strings、超宽/超长及稀疏大尺寸工作簿做拒绝和资源 bounded 测试。

**证据更正说明**：安全角色初报中的 `fastapi_app/core/xlsx_importer.py` 和 `tasks.py:249 read_workbook` 不属于当前 HEAD；本报告不沿用这些错误定位，以上路径由主理人按当前代码重新核实。

---

## 5. QA 与机器门禁证据

### 5.1 精确 HEAD 的远端检查

当前 HEAD 的 post-merge CI run `40179052967`：test、lint、frontend、build 全部成功。原始日志提取结果：

| 项目 | 结果 |
|---|---|
| 后端 pytest | `4935 passed, 118 skipped in 448.30s` |
| `prod_audit` 独立套件 | `296 passed` |
| 覆盖率 | `70.54%` |
| pip-audit | `No known vulnerabilities found` |
| 前端 Vitest | `227` 个测试文件，`1731` 个测试全部通过 |
| 前端构建 | 成功，`22.23s` |
| DTO/types 跨端对齐 | 对齐检查 PASS，相关步骤成功 |

CodeQL run `40179052344`：Python、JavaScript/TypeScript、Actions 全部成功。

本地保留的复核材料为 `logs/prelaunch-20261025-ci-test.log`、`logs/prelaunch-20261025-ci-frontend.log` 和 `logs/review-packet-prelaunch-20261025.md`。

这些结果只证明对应检查在精确 HEAD 上通过，不证明：

- B1 的部署假成功不存在；
- H1 的工厂授权语义正确；
- 当前生产进程已经加载该 HEAD；
- 未覆盖的故障注入、外部告警和恶意 XLSX 场景安全。

### 5.2 本地 QA 实测

以下命令均在仓库根目录执行；Vitest 在 `frontend-vite` 中执行。除明确标记 `NOT_RUN` 的项目外，表中最终命令均为 exit 0。

| 检查 | 命令/方式 | 最终结果 |
|---|---|---|
| 基线 | `git status --short --branch`、`git rev-parse HEAD`、`git rev-parse erp/main` | main 与 erp/main 均为精确 HEAD，检查时工作区干净 |
| 质量门禁 | `.venv/Scripts/python.exe scripts/quality_gate.py --verbose` | PASS；基线棘轮无新增问题，不等于基线债务为零 |
| 门禁自测 | `.venv/Scripts/python.exe scripts/quality_gate_selftest.py` | 67 项自测 PASS |
| Ruff | `.venv/Scripts/ruff.exe check fastapi_app` | PASS |
| mypy | `.venv/Scripts/mypy.exe fastapi_app` | 380 个源码文件通过 |
| 泄密扫描 | `python -m scripts.security_scan --output <QA日志>` | 扫描 2901 个文件，门禁通过 |
| 测试残留 | `python -m scripts.check_test_orphans` | 1328 = 1327 + 1；仅 `purchase_order_spare` warning |
| 依赖锁 | `python -m scripts.check_requirements_lock` | 7 组依赖锁一致 |
| 导入体积门禁 | `python -m scripts.check_import_file_size_guard` | 7 个批量导入端点及 packaging 通过既有门禁 |
| Bandit | `python -m bandit -c bandit.yaml -r fastapi_app utils -f json -ii` | 21 个基线发现，棘轮通过；不是“零发现” |
| pip-audit | `python -m pip_audit --path .venv/Lib/site-packages` | 0 个已知漏洞 |
| 前端静态 | `npm run type-check && npm run lint && npm run check:api && npm run check:routes && npm run check:dto && npm run check:types` | 全部通过 |
| 前端测试 | `node node_modules/vitest/vitest.mjs run`，独立 TEMP/TMP | **227 files / 1731 tests 全通过，245.10s，EXIT_CODE=0** |
| 本地全量/聚焦 pytest | `logs/run_full_tests.sh` 需要交互 UAC | **NOT_RUN**；未绕过 ACL，复用第 5.1 节同一 merge HEAD CI，不声称本地已跑 |
| 本地前端构建 | 未执行；不得覆盖生产 dist | **NOT_RUN**；精确 HEAD 的远端构建已通过 |

关键可复核日志：

- `logs/prelaunch-20261025-qa-final-workspace.log`
- `logs/prelaunch-20261025-qa-quality-gate-verify.log`
- `logs/prelaunch-20261025-qa-frontend-vitest-final.log`
- `logs/prelaunch-20261025-qa-pytest-eligibility.log`
- `logs/prelaunch-20261025-qa-production-listeners-verify.log`
- 其余原始证据保留在 `logs/prelaunch-20261025-qa-*`。

QA 没有发现可独立追加的第五个 Medium 或其他新产品缺陷；执行异常见第 9 节。

### 5.3 生产只读状态

- `erp-prod`、`erp-arq`、`erp-redis`、`erp-redis-broker`、`erp-web` 均为 `Running / Automatic`。
- 直连 `http://127.0.0.1:5002/api/health` 为 200；nginx `http://127.0.0.1:3000` 首次返回 301，跟随跳转后为 200；生产 HTTPS 根页及 nginx health 均为 200。未调用业务写入或故障端点。
- 2026-10-25 20:04 的监听核对中，`127.0.0.1:5002` 只有 PID 9872 一个监听者，祖先链为 `9872 → 23944 → 17932 → nssm`；当前进程组为真，无历史监听者残留。
- 主理人读取的最新 `logs/prod_runner.json` 快照时间为 `2026-10-25T20:09:58`：`ready=true`、`frontend_ok=true`、8 workers、backend ready、Redis/broker 正常，`arq.status='external'` 符合独立服务拓扑。
- pyc/启动日志没有可定位 SHA 的字段。上述健康与进程证据均不能证明生产已加载 `0dfb5d77`，运行版本指纹仍属未验证。

---

## 6. 已核实的正向控制与排除项

- M-A 抵扣流水净量 `>0` 过滤与导出语义一致，未发现额外回归。
- M-B aware/naive datetime 的 `fmt_business` 替换未发现误改。
- M-H 删除的六个测试类确为零断言空类，未误删有效断言。
- DLQ 使用 List 所需的 `LLEN`，不是错误的 `GET`；M1 是异常降级语义问题，不是 Redis 命令类型错误。
- DLQ 管理端点要求 superuser；重试参数使用 `ast.literal_eval`。
- 新运维调用使用 argv 列表，未发现新增 `shell=True` 拼接注入。
- 请求体已有 Content-Length 预检和无长度逐块累计控制；M2 是各层预算口径不一致，不是完全没有体积限制。
- M-D 已关闭：`smart_cleanup()` 当前调用 `_enforce_count_ceiling()`，count/hybrid 策略会读取 `retention_count()`；该执行链在 base 已存在，不计入本次问题。

---

## 7. 修复行动清单与重新放行条件

| 优先级 | 行动 | 验收证据 |
|---|---|---|
| P0 | 修复 B1 重启结果契约、外层脚本和版本指纹验收 | 同 PID + 旧健康进程测试非零退出；真实重启 PID/commit 均改变；checkpoint 分支有效覆盖 |
| P0 | 修复 H1 finished-stock 全链工厂隔离 | 两工厂 HTTP 级读写/导出测试；跨厂 404 且无副作用 |
| P1 | 修复 M1/M3 DLQ unknown 与告警外推语义 | Redis 故障、首次 DLQ 残留、任务自身失败均产生正确 critical/失败结果 |
| P1 | 修复 M2 multipart 边界 | 七个导入端点及 packaging 的边界集成测试通过 |
| P1 | 修复 M4 告警脱敏 | 所有外发渠道通过敏感样例断言 |
| P1 | 修复 M5 XLSX 统一资源预算 | 恶意/异常工作簿在受限 CPU、内存、解压尺寸内被拒绝 |
| P0 | 修复后重新跑聚焦测试和精确新 HEAD 全量 CI | 新 commit 的测试、lint、前端、构建、CodeQL 全绿 |

P1 不代表可以无条件延期。按 `docs/agents/code-review-standard.md`，Medium 若未修复，必须由有权限的责任人明确批准延期并记录风险接受；否则仍不得放行。

重新放行至少需要：B1/H1 关闭、所有 Medium 修复或正式批准延期、聚焦回归通过、精确新 HEAD 门禁通过、发布版本指纹可验证。

---

## 8. 发布与 5 分钟内回滚预案

### 8.1 当前动作

当前裁决为 No-Go，本轮没有执行上线，也不建议先上线再观察。

### 8.2 修复后发布前置条件

1. 确认生产工作区位于目标 `main`、工作区干净，记录目标 commit 和经指纹确认的上一良好版本。
2. 精确目标 commit 的 CI/CodeQL 和本地聚焦测试全部通过。
3. 当前增量涉及后端与 `erp-arq` 代码，两者都需要加载新版本；重启必须使用已修复的显式 stop→start 路径，并核对前后 PID。
4. 主理人以 pathspec diff 复核，当前受审增量没有 `migrations/`、`frontend-vite/`、`requirements/`、`config/`、`.env.example` 变更。因此按当前范围不需要重建依赖、替换 dist 或执行 migration；后续修复若扩大范围，必须重新评估。
5. 不把 PR base `d3fe6812` 自动当作生产上一版本；当前健康快照没有证明生产已加载哪个 commit。回滚目标必须由 owner 明确确认。
6. 本报告不授权任何数据库迁移。若后续修复引入 migration，必须另做迁移与数据回滚方案，不能套用“5 分钟代码回滚”。若后续包含前端产物，必须先备份当前 `dist` 再按 runbook 原子切换。

### 8.3 回滚时间表（仅适用于无数据库迁移的代码/静态产物发布）

| 时间 | 动作 |
|---|---|
| 0:00-0:30 | 停止继续发布，记录异常版本、服务 PID、健康/版本指纹和前端产物状态 |
| 0:30-2:00 | 在确认干净的生产工作区恢复 owner 指定的上一良好版本；若前端有变更，恢复发布前备份的 `dist` |
| 2:00-3:30 | 由管理员按受支持路径显式 stop→start `erp-prod` 和 `erp-arq`；记录并比较前后 PID，不信任同 PID 的“成功” |
| 3:30-5:00 | 验证后端健康、目标回滚 commit 指纹、关键只读 API、前端静态可达、ARQ/DLQ 状态；全部符合才宣布回滚完成 |

若且仅若 main 仍恰为 `0dfb5d77`，且 owner 决定整体回退 PR #13 到 `d3fe6812c10594184044ca07b120b25e02103141`，可在干净工作区使用 `git revert --no-edit -m 1 0dfb5d7706049d67689c336f7445d755e9345403`，随后以 `git diff --exit-code d3fe6812c10594184044ca07b120b25e02103141 HEAD` 验证树一致，并检查 `git status --short` 无意外源码改动。已有后续提交、钩子失败或选择其他良好版本时，该等式不适用，不得硬套。

若进程 PID 未改变、版本指纹不符或关键探针失败，应保持事故状态并升级处理，不得仅凭 `/api/health` 200 宣告回滚成功。若已执行破坏性数据库变更，以上 5 分钟预案不适用，必须进入独立的数据恢复流程。

---

## 9. 未验证项、执行异常与证据边界

- 未对生产执行真实重启、停止或故障注入，因此 B1 由代码路径和现有测试契约证明，不是生产事故复盘。
- 未在生产发起跨工厂读写请求；H1 是静态授权调用链结论。
- 未真实发送 email/webhook，未验证外部渠道实际投递内容。
- 未对生产 Redis/DLQ 注入 unknown、wrong type 或断连。
- 未在真实 XLSX 解析进程上执行恶意压缩炸弹/资源耗尽测试。
- 本地全量及聚焦 pytest 均为 `NOT_RUN_NO_NONINTERACTIVE_ELEVATION`；复用的是同一 merge HEAD 的远端 CI，不声称本地已执行。
- 本地前端构建未运行；只有精确 HEAD 的远端构建证据，本轮未覆盖生产 dist。
- 本机没有独立预发环境；工作区源码会在后端重启时进入生产，后续发布必须继续遵守干净工作区与版本指纹纪律。
- 生产健康快照只能证明快照时点的进程/探针状态，不能证明其已加载指定 commit。

QA 执行异常均与产品问题分开记录：

1. 初次 quality gate 与其 self-test 并发，self-test 生成的临时 BOM 文件触发 BOM check FAIL；self-test 退出后顺序复验 PASS，因此不记为产品回归。
2. 初次 Vitest 因 TEMP 目录已存在于 mkdir 阶段退出，未计入测试结论；最终独立目录重跑为 227/1731 全绿。
3. 最终 Vitest 临时目录 `frontend-vite/.vitest-tmp/prelaunch-20261025-qa-final` 含 779 项，清理触发 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`，结果为 `CLEANUP_EXIT_CODE=1 / CLEANUP_VERIFIED=0`。主理人未绕过保护或重复删除，目录保留，后续需在明确授权下清理；这不改变测试 exit 0 的事实。
4. QA 原始日志作为本次审计证据保留，不按临时垃圾删除。

---

## 10. 最终结论

**当前版本 No-Go。** 精确 HEAD 的自动化门禁全绿是正面证据，但 B1 的部署假成功和 H1 的跨工厂授权缺口均未闭环；5 项 Medium 也尚无修复或批准延期记录。本轮仅完成检查和报告，没有自动修复、上线或回滚。修复后应针对上述触发链进行独立复验，并以新的精确 HEAD 重新作出 Go/No-Go 决策。

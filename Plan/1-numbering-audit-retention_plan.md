# numbering_audit 30 天保留治理实施计划

## 状态

已交付：`fc5bda7b`（初版）+ `9cba5831`（评审修复），已推送 `erp/main`；CI run **41969414917 success 12m16s**，4 job（test / frontend / lint / build）全绿。

- `agent_proposed_status`: 实现、评审问题修复、全量回归、CI 全部通过。
- `verifier_status`: 独立窄域评审已闭环（2 High + 4 Medium 全修）；全量 diff 评审代理的 B0 为变异测试窗口内的误报，已用 `grep` 与全量回归证伪。

## 不卡死计数

- 已确认失败：0（L0）。
- 同一失败签名达到 2 次即停该方向，先记录新证据和替代路径。

## 项目启动信息

- 项目：滨发协同系统后端 ARQ 保留治理。
- 初始需求：用户要求“按你的建议优化”；接受调优报告中 P1 的 30 天保留建议。
- 技术栈：Python 3.13.13、FastAPI、SQLAlchemy AsyncSession、asyncpg/PostgreSQL 18.3、ARQ、pytest。
- 终极功能：每日 03:10 自动将 30 天前的编号巡检记录先归档再分批删除，最近记录查询不受影响，失败在健康检查可见。
- 默认循环轮次 3，安全最大轮次 6，每轮最大改动点 3。
- 授权边界：仅本地代码与测试；不直接重启生产、不直接删除生产数据、不修改数据库参数或索引。

## 目标与验收

1. UTC 日界保留 30 天；`checked_at == cutoff` 的记录保留，只有严格早于 cutoff 的记录进入计划。
2. 归档先于删除，归档含全部目标 ID、JSONL 行、CRC 与 SHA-256；归档失败/损坏/行数不符时不得删除。
3. 删除同时匹配归档 ID 集合和过期时间，批大小不超过 5000，每批独立 commit。
4. 中断重跑复用既有归档，已删 ID 自然跳过；部分批次失败按实际提交数记账。
5. 删除后窗口仍有未归档行时只报 `archive_incomplete`，不删除这些行。
6. ARQ 入口使用独立连接持 advisory lock，`join_transaction_mode='control_fully'`；解锁失败丢弃连接。
7. 状态文件原子写，任务失败和锁跳过均留痕；pending error 或超过 7 天未成功使健康状态 degraded。
8. 每日 03:10 调度、日级补跑和按名入队注册完整；匿名健康响应不暴露新增运维细节。
9. 真库集成只使用专用哨兵 ID，证明列表绑定、过期双条件和真实 commit；不在生产库运行测试。

## 方案与取舍

- 方案 A（选择）：独立轻量任务与状态文件。优点是 audit_log 合规任务零改动，故障隔离；代价是少量状态/归档结构相似。
- 方案 B（反选）：扩展 audit_retention_task 同时处理两表。可复用更多代码，但会把法定审计日志与诊断记录放入同一失败路径，文件已超过 800 行。
- 方案 C（反选）：仅按时间 DELETE，不归档。实现最短，但不满足先归档与可恢复要求。
- 撤销条件：若后续形成三类以上同构保留任务，再抽取公共归档/状态组件；本次不为未来假设做抽象。

## 输入、输出与失败处置

- 输入：UTC now、配置 `NUMBERING_AUDIT_RETENTION_DAYS`（0/负数=禁用，默认30）、归档目录、数据库行。
- 输出：任务 report、JSONL.GZ 归档、状态 JSON、登录用户健康块 `numbering_audit_retention`。
- 空数据：成功，不建空归档，不调用 DELETE。
- 归档失败：拒绝删除 + `archive_failed` pending error。
- 归档损坏：拒绝复用 + `archive_failed`，人工改名后重导。
- 行数不符：拒绝当轮删除 + `archive_row_mismatch`。
- 删除失败：保留归档 + 已提交行数 + `delete_failed`，下轮续删。
- 晚到历史行：不删除未归档行 + `archive_incomplete`。
- ANALYZE 失败：不抹除已提交结果，追加 `analyze_failed`。
- 并发：锁冲突干净跳过并写 `lock_busy`；任务异常先写失败状态再上抛。
- 状态损坏：另存 `.corrupt-*` 后重建并报错，不静默清零账本。

## 依赖与文件清单

新增：
- `fastapi_app/tasks/numbering_audit_retention_task.py`
- `fastapi_app/tests/test_numbering_audit_retention_task.py`
- `fastapi_app/tests/test_numbering_audit_retention_pg.py`

修改：
- `fastapi_app/core/arq_app.py`：导入、03:10 cron、日级补跑集合、functions 注册。
- `fastapi_app/core/config.py`：保留天数与归档目录。
- `fastapi_app/core/health.py`：第四保留链信号、缓存和登录/匿名响应。
- `.env.example`：配置说明。
- `fastapi_app/tests/test_arq_functions_registry.py`：新增任务显式注册断言。
- `tests/test_health_anonymous_detail.py`：新增信号隔离和可见性断言。

预计 9 个产品/测试文件 + 本计划；无新第三方依赖、无 ORM/DDL 变更。

## 风险与回滚

- 数据风险：实现只在部署后执行；部署前必须确认最新可恢复备份和归档目录权限。回滚代码只能停止后续清理，已删数据需从归档恢复。
- 事务风险：复用现有专用连接 + `control_fully` 模式，真库入口测试验证 commit。
- 并发风险：独立 advisory lock；重跑以归档 ID 幂等。
- 性能风险：游标分批、每日执行、稳态约 4.3 万行；不新增索引，先以 EXPLAIN/实际耗时验证。
- 契约风险：健康新增字段仅登录可见，匿名最小响应保持不变；`_resolve_status` 第四参为**必填**（不设默认 True），强制所有调用方显式表态，已同步更新 `test_audit_retention_task.py` 与 `test_health_anonymous_detail.py` 的调用。
- 回退：产品代码由 Git 还原；不执行生产 DDL/DML。本任务不创建 .bak，版本化工作区是回滚点。

## 二阶效应与边界

- 清理后行数下降 → autovacuum/备份扫描量变化 → 观察 ANALYZE、备份 L2 与慢查询；异常时停用配置并回退任务。
- 新增日级 cron → catch-up 可能补跑 → 同 advisory lock 防重入，幂等归档防重复删除。
- 健康 degraded → prod_runner 不因此重启（沿用既有语义）→ 运维按 pending_errors 处理。
- 保护范围：仅自动日级清理；管理员手工触发也走同一归档与锁约束，无绕过清理的安全豁免。配置 0 是明确的管理员停用出口。

## Wave 与出口校验

### Wave 1：Red 测试

- 写单元/集成测试与注册/健康断言。
- 出口：目标测试因模块/配置/调度/健康字段不存在而失败，证明测试具备判别力。

### Wave 2：核心实现

- 实现配置、归档、分批删除、状态、锁入口。
- 出口：核心单元测试全绿，归档失败/部分失败/边界均覆盖。

### Wave 3：调度与健康

- 接入 ARQ、健康块、匿名/登录可见性。
- 出口：注册、日级补跑、健康状态与隐私测试全绿。

### Wave 4：验证与评审

- 聚焦提权测试、相邻回归、ruff、quality_gate、mypy（适用）、真库集成。
- 至少一次定点变异：破坏归档前置/过期双条件/control_fully 之一，对应测试必须变红并立即还原。
- 新鲜上下文只看 diff + 需求审查；Blocker/High/Medium 清零后才可交付发布候选。
- 需要跨层改动，最终运行一次全量提权 pytest；未全绿不发布。

## 实测证据归档

- [环境] `D:/erp_system/.venv/Scripts/python.exe` = Python 3.13.13；工作区目标文件 diff 为空。
- [基线] 2026-11-05 只读实测 `numbering_audit` 46,680 行、完整日 1,440 行；报告位于 `deliverables/db-tuning-2026-11-05/`。
- [Red-1] `logs/_pytest_elevated.1018.log`：新任务模块不存在 → `ImportError: cannot import name 'numbering_audit_retention_task'`，收集期 1 error、EXITCODE=2。
- [Red-2] `logs/_pytest_elevated.1876.log`：接线缺口 → `StopIteration`（cron 条目缺失）、`AttributeError: _numbering_audit_retention_signal`（×2 setup error）、`TypeError: _resolve_status() got an unexpected keyword argument`。合计 2 failed / 2 errors / 3 passed。
- [Green-1] `logs/_pytest_elevated.491.log`：81 passed / 2 failed。两处失败均为**测试口径**缺陷，不是实现缺陷：删除集合断言依赖 FakeDB 初始行顺序（`[2,1]` vs `[1,2]`）；补跑断言把传入扫描时间当业务日（`2026-10-22` vs `business_today()`）。已修正为排序比较与 `business_today()`。
- [Green-2] `logs/_pytest_elevated.1766.log`：**96 passed / 1 skipped，EXITCODE=0**（1 skip = 契约比对需真实后端 `CONTRACT_BASE_URL`）。
- [Green-3 真库] `logs/_pytest_elevated.1273.log`：**6 passed，0 skipped**，含 `test_archive_and_delete_only_expired_sentinel_rows` 与 `test_real_entry_point_commits_batches`。真库用例必须与 `tests/` 下文件同批执行，才会经 `tests/conftest.py` 的会话夹具把 `settings.ASYNC_DATABASE_URL` 重定向到 `*_test`；单独跑该文件会被 `_test_db_guard` 以 EXITCODE=2 拒绝（设计如此，非缺陷）。
- [变异] `logs/_pytest_elevated.81.log`：把 DELETE 的 `AND checked_at < :cutoff` 去掉后 **5 failed / 16 passed**，命中归档顺序、晚到行、非过期行、部分失败记账、ANALYZE 五条；已还原并复跑通过。
- [自审 Blocker] 初版 advisory lock 键 `0x4E4152455400000001` 是 71 位，超出 PostgreSQL `bigint`（2^63−1），`pg_try_advisory_lock` 会直接报数值溢出而不是返回 false，任务第一行就崩。已改为 `0x4E41524554000001`（63 位，仍与旧任务 `0x4152455400000001` 区分）。
- [Review] 独立审查代理（全量 diff）跑了 30 分钟未收口；另起窄域评审（只审核心任务 + 其单测）产出 **2 High + 4 Medium**，逐条核对均成立并已修复：
  - **H-1 归档文件名不含库标识**：生产 `erp_system` 与恢复演练库 `erp_system_test` 在同一天会命中同名归档；ID 是自增序列、两库高度重叠，后跑方会复用对方 ID 集删自己的行，而 `checked_at < cutoff` 只拦「未过期」，拦不住「ID 相同但内容从未进本库归档」。修法：文件名与账本键都带 `current_database()`（`numbering_audit_before_<db>_<cutoff>.jsonl.gz`），库名做字符白名单清洗。残余限制：两台主机上的同名库共用同一目录仍会撞名，属部署约束，已写进 runbook 说明。
  - **H-2 SHA-256 只算不比**：复用归档时重算当前文件 hash 却从不与账本比对，gzip CRC 又只防随机损坏。修法：复用前比对账本 `sha256`，不一致即 `archive_tampered` 且整轮不删；同时把列契约从「键名 + id 类型」扩到全 5 列类型校验。
  - **M-1 停用轮洗绿**：`days<=0` 空跑仍写状态，会推进 `last_success_at` 并清空 `pending_errors`，「临时关掉再打开」即可把上一轮失败洗成绿灯。修法：停用轮不落盘；软失败轮不再推进 `last_success_at`，并写入 `last_error` 让 7 天阈值生效。
  - **M-2 `sys.exc_info()` 取到清理期异常**：改为 `except BaseException as exc` 显式捕获，清理路径统一 `suppress(Exception)`，避免 `AsyncSession.__aexit__` 的异常顶替根因。
  - **M-3 状态文件原子写缺 fsync**：补 `flush + fsync` 后再 `os.replace`。
  - **M-4 测试用子串断言 SQL**：`AND`→`OR` 变异存活。改为逐字锁定 `WHERE id = ANY(:ids) AND checked_at < :cutoff` 并禁止 ` OR `；另修两处镜像断言（stale 阈值改用字面量 8 天并断言阈值=7；信号键集改为 16 键字面量而非两次调用互比）。
- [变异-2] `logs/_pytest_elevated.1597.log`：把 DELETE 的 `AND` 改成 `OR` → **5 failed / 19 passed**（修复前该变异存活），已还原。
- [Green-4] 修复后聚焦 + 真库：**88 passed / 0 skipped，EXITCODE=0**（`logs/_pytest_elevated.1590.log`）。
- [Review-2] 全量 diff 评审代理最终返回（它抓到了工作区正处的 `OR` 变异态，那条 B0 属误报，已用 `grep` 与全量回归证明是 `AND`）。其余 4 条成立并已修复：
  - **M6 真库入口用真实 cutoff**：`test_real_entry_point_commits_batches` 直接调真实入口，`now` 取真实时间 → cutoff = 今天−30 天 → 会删掉共享测试库里**所有** 30 天前的行。修法：`monkeypatch.setattr(nrt, 'retention_cutoff', lambda _now=None: _SENTINEL_CUTOFF)`，并断言 `archive_key` 落在哨兵日，证明窗口真的被钉住。
  - **M5 状态 tmp 固定名**：锁竞争落败方写 `last_skipped_at` 与持锁方收尾写并发，固定 `.tmp` 名会互相截断。修法：tmp 名带 pid + 随机后缀；`_persist_report_state` 的写失败改为留痕不抛（数据已删完，不该因账本写失败报任务失败）。
  - **M4 缺 `recent_failure` 回归测试**：补 `test_signal_recent_failure_after_success_degrades`（成功 2h 前、失败 1h 前 → ok=False / note=recent_failure）。
  - **L3/L4/L5/L6/L7/L12**：账本损坏时另存原文件保留现场；`pending_errors`/`deleted_rows_total` 非预期类型时兜底，避免健康端点抛异常导致契约形状漂移；「只被锁挡过」改为 `only_skipped` + ok=True（不是故障）；补「归档里混入恰好等于 cutoff 的行也不得删」的 DELETE 侧用例；补「先取锁再开事务」顺序断言；`archive_tampered` 只对**复用**归档生效，避免运维按 remediation 删坏归档重导后被误判。
  - **M2「从未运行 → ok=True 永远绿」不予修改，明确为设计决策**：与既有 `audit_retention` 链语义一致——刚部署到首次 03:10 之间报警是纯噪声；可观测性由登录可见健康块的 `note=not_yet_run`、以及 `test_arq_functions_registry` 对 cron 注册的守卫承担。已加测试钉住该语义，防止后人误改。
- [Green-5] 第二轮修复后聚焦 + 真库：**91 passed / 0 skipped，EXITCODE=0**（`logs/_pytest_elevated.893.log`）。

## 中断点

Wave 1–4 已完成，评审问题全部闭环，等待推送与 CI。若中断，先读取本计划与 git diff；不得跳过 Red→Green，不得直接在生产运行清理任务。归档目录**不得跨环境共用**（文件名已带库名，但两台主机上的同名库仍会撞名）；生产首次运行前必须确认最新可恢复备份。

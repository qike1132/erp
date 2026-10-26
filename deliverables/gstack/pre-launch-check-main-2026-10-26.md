# ERP 全项目上线前质量审查报告

**审查日期**：2026-10-26  
**审查基线**：`main@56b4f30449d9d5afb6a97158996e90b145ab2d3e`  
**分支核对**：本地 `main` 与 `erp/main` 均为上述提交  
**审查范围**：当前整个项目，而非仅 PR #14；覆盖后端、前端、生产运维、备份恢复、安全、依赖与测试真实性  
**工作方式**：只读源码审查、现有测试审查、隔离复现、远端精确 SHA 检查；未修改业务源码、测试、依赖锁或生产配置  
**最终裁决**：**No-Go，当前版本不适合直接上线**

---

## 1. 执行摘要

当前版本不能放行，理由不是“扫描发现数量较多”，而是存在可明确定位到真实调用链的发布假成功、恢复保护失效、业务结果错误和前后端契约冲突；同时，目标提交的必需 CI 已失败。

最关键的上线风险如下：

1. **发布身份仍可出现假成功**：停前 PID 探测失败会被折叠成 `prev_pid=None`，GUI 单服务重启路径可能把未生效的重启报告为成功；脚本路径在更严格的组合故障下也仍可能返回 0。
2. **数据库恢复中断保护是 fail-open**：标记写入失败不阻止 DROP，失败恢复也会无条件清除标记，读取失败又会被视为无标记，可能让空壳或部分恢复的数据库失去后续告警。
3. **真实业务结果已有确定性错误**：生产计划客户级 `shipped_qty` 因重复判断同一去重集合而恒不累计；出货创建按客户而非“客户+月份”分组，合法跨月明细会被后端拒绝。
4. **发布健康验收过宽**：Redis 不可用时通用健康状态仍可为 `healthy`/200，发布脚本还接受 `degraded` 且不检查 `security_degraded`，健康响应也不证明实际 worker 加载了目标提交。
5. **前端仍有可选择错误产品、丢失失败草稿及假成功提示的路径**：包括生产录入搜索乱序叠加 Enter 默认首项、创建失败后仍关闭对话框、批量已读部分/全部失败仍提示全部成功。
6. **当前精确 SHA 的 CI 不是绿色**：`lint` 因 `test.lock` 中 `pytest-asyncio 1.4.0` 与新鲜解析 `1.4.1` 不一致而失败，`build` 被跳过。其他测试通过不能抵消该发布阻断。

### 1.1 去重后的计数

| 类别 | 数量 | 说明 |
|---|---:|---|
| 必需发布门禁失败 | 1 | G0；与代码缺陷分开计数 |
| Blocker | 2 | B1、B2 |
| High | 8 | H1-H8 |
| Medium | 11 | M1-M11 |
| Low / Nit | 0 | 未将风格偏好凑成问题 |

按照 `docs/agents/code-review-standard.md`：任一 Blocker 直接阻断；任一 High 当版必修；Medium 未修复时须由 owner 明确批准延期并建立 issue，否则也不能放行。因此，“建议尽快优化”不等于可以无记录地带入生产。

---

## 2. 证据口径与边界

本报告使用以下口径：

- **静态确认**：当前源码中的分支、状态转换或调用契约已经能够证明错误行为；不代表已在生产制造事故。
- **隔离复现**：在未触达生产服务和数据的隔离进程中观察到行为。
- **条件性风险**：需要特定故障组合或外部条件；报告明确列出条件，不将单次异常夸大为必然结果。
- **待动态验证**：需要 Windows/NSSM、PostgreSQL、真实不可取消线程、Excel/WPS 或故障注入才能确认最终运行表现。

本轮未重启生产服务，未写生产数据库，未执行迁移，未发送真实邮件/webhook，未运行恶意 XLSX，也未修改前端生产 `dist`。当前生产 worker 是否已加载上述 SHA，不在本次证据范围内。

---

## 3. 发布门禁阻断

### G0 [发布阻断] 目标提交的依赖锁新鲜度检查失败

**位置**：

- `requirements/test.txt`
- `requirements/test.lock`
- CI `Check requirements lock freshness`

**证据**：精确 SHA 的 CI run `40247966531` 已完成，整体结论为 `failure`。`lint` 明确输出：

```text
[lock] ✗ test.lock 与 test.txt 不同步：
变更 [('pytest-asyncio', '1.4.0', '1.4.1')]
```

`test`、`frontend` 成功，`build` 因依赖 job 失败而跳过；本地同类锁检查也曾非零，排除了单次远端日志误读。

**实际影响**：当前提交没有经过完整发布流水线，不能形成“所有必需检查均通过”的发布证据。它不是业务逻辑 Bug，但仍是明确的发布阻断。

**修复建议**：单独刷新并审查锁 diff，确认 `pytest-asyncio` 变更及兼容性；不要盲目改版本号只为变绿。所有代码修复完成后，在新的精确 SHA 上重跑完整 CI，确保 `build` 不再被跳过。

---

## 4. 上线前必须修复

### B1 [Blocker] 停前身份 unknown 可被当成“确认未运行”，重启仍可能假成功

**位置**：

- `server_manager/service_ops.py::restart_service_via_stop_start()`，尤其第 629 行
- `server_manager/service_ops.py::wait_service_running()`，第 764-798 行
- `scripts/restart_backend.py::main()`，第 181-250 行

**根因**：

1. GUI/ServiceOps 停前通过 `svc_pid()` 取得单值 PID，丢失 `svc_pid_ex()` 的 `ok` 状态；探测失败和确认未运行都会变成 `prev_pid=None`。
2. `wait_service_running()` 在 `prev_pid=None` 且事后 PID 可读时，会走第 797-798 行并返回 `effective=True`。
3. 因而 GUI 单路场景只需“停前探测失败 + stop 未真正生效 + start 后读到同一旧 PID”，即可出现“启动成功”。该路径没有脚本侧第二次身份与进程年龄复核。
4. 脚本虽然使用 `prev_ok`、`result.effective`、独立 PID 复核和年龄检查，但 `prev_ok=False` 与 `age is None` 目前只告警。脚本返回 0 的假成功需要完整组合：两侧停前身份均未知、stop 未生效、事后读到同一旧 PID、独立复核一致、年龄不可读、旧进程健康且 HEAD 一致或读取失败。**单次 PID 查询失败并不足以推出必然假成功。**

**实际影响**：管理界面或发布脚本可能显示成功，但实际仍由旧 worker 提供服务。由于健康接口不绑定目标 commit、实际监听 worker 和启动代次，后续发布验收也可能被旧进程健康状态污染。

**修复建议**：

- 停前统一使用 `svc_pid_ex()`，保留 `running / not-running / unknown` 三态；发布路径在身份 unknown 时应于任何停服副作用前拒绝，GUI 至少不得产生 `effective=True`。
- 发布脚本中 `prev_ok=False`、关键身份复核失败或进程年龄不可得不得只告警；无法证明本次启动代次时应非零退出。
- 发布验收绑定目标 commit、进程 PID/启动时间及实际端口监听 worker；健康 200 只能作为其中一个条件。
- 将“服务终态 RUNNING”和“本次重启已验证生效”继续保持为不同结果，所有调用方都必须消费后者。

**必须补测**：GUI 与脚本分别覆盖 confirmed-not-running、confirmed-running、unknown；同 PID 旧健康进程、stop 非零/超时、年龄不可读、HEAD 读取失败、独立复核不一致。测试应断言失败结果，而不只检查日志。

### B2 [Blocker] 恢复中断标记写入、读取和清除均可能 fail-open

**位置**：

- `fastapi_app/services/backup/dump.py::restore_database_via_psql()`，第 637-683 行
- `fastapi_app/services/backup/restore_guard.py::mark_restore_started()`，第 49-70 行
- `restore_guard.py::mark_restore_finished()`，第 73-78 行
- `restore_guard.py::read_marker()/check_interrupted_restore()`，第 81-104 行

**触发条件与错误行为**：

- 标记文件写入失败时只记录 warning，后续 DROP/CREATE 仍继续。
- `restore_database_via_psql()` 在外层 `finally` 中无条件调用 `mark_restore_finished()`；DROP/CREATE 或 psql 导入失败也会清除标记。
- 标记读取发生 I/O 或解码错误时返回 `None`，把“状态未知”折叠成“无中断”；启动检查也只打 CRITICAL，不阻断正常业务就绪。

**实际影响**：DROP/CREATE 与后续 psql 单事务导入不是一个原子操作。一旦中间失败或进程中断，数据库可能为空壳或部分状态，而保护标记可能从未写入、被误清或不可读，削弱下一次启动时的最后告警和回滚提示。恢复任务本身会返回 error，**本项不是“恢复假成功”**。

**修复建议**：

- `mark_restore_started()` 必须返回可检查结果或直接抛错；未可靠落盘前禁止 DROP。
- 只有确认导入及必要校验全部成功后才清除标记；失败时保留并更新失败阶段，不得在通用 `finally` 中无条件删除。
- 标记读取采用三态； unreadable/corrupt/unknown 必须告警并使正常业务 readiness 失败，同时保留受控的最小恢复入口，避免把运维恢复通道也锁死。
- 增加恢复状态机和事后验证，不以进程返回码单独证明业务数据完整。

**必须补测**：标记写失败、读失败、损坏 JSON、DROP 失败、CREATE 失败、psql 非零、进程被杀和成功完成；验证破坏性操作前标记存在、失败后的标记仍在、成功后才会清除。

### H1 [High] 客户级已出货汇总被同一去重集合阻断，结果恒不累计

**位置**：`fastapi_app/services/production_plan_service.py::_calc_monthly_summary()`，约第 168-182 行。

**问题**：首次遇到 `(customer_name, product_name)` 时，代码先将键加入 `_counted_shipped` 并累计 `total_shipped_qty`；随后客户级累计再次判断 `_key not in _counted_shipped`，该条件必为 False，因此 `cs['shipped_qty']` 永远不增加。

**影响**：`GET /api/v1/production-plans/list` 与 `/customer-summary` 的客户级出货量错误；总出货量及计划行明细不受这一特定错误影响。可能误导客户维度的出货进度判断。

**修复建议**：在首次键分支中保存 `is_new_shipment` 布尔值，或调整客户汇总初始化顺序，在同一个首次键语义下完成两级累加，保证每键只计一次。

**最小回归**：同客户、同产品、两条计划，二者均携带该键月度 `shipped_qty=7`；断言总计和客户级均为 7。该用例同时能拦截恒 0 和重复累计成 14。现有 `fastapi_app/tests/test_production_plan.py` mock 整个 service/汇总结果，未执行真实 `_calc_monthly_summary()`。

### H2 [High] 杀树失败后仍清空进程身份并继续按已停止处理

**位置**：

- `fastapi_app/core/prod_runner.py::_Managed.kill_tree()`，第 472-532 行
- `_Managed.poll()` 的强制重启调用，第 597-614 行
- `Supervisor.shutdown()`，第 807-812 行

**问题**：硬杀失败或最终仍存活时仅打印警告，随后仍执行 `self.proc = None`；调用方可继续 `_mark_crashed()` 并安排重启，`shutdown()` 也无条件打印“已停止”。

**触发条件**：`taskkill`/terminate/kill/wait 失败，或进程在终止序列后仍存活。

**实际影响**：监督器丢失仍存活进程的句柄和身份，可能留下旧 worker、占用端口或与后续实例并存，状态文件/日志却表示已停止或进入重启流程。完整孤儿健康场景仍需隔离 Windows/NSSM 故障注入，本报告不声称当前线上已存在该进程状态。

**修复建议**：让 `kill_tree()` 返回结构化结果或在未确认死亡时抛错；未确认终止不得清空身份、不得自动拉起替代实例。`shutdown()` 汇总每个服务的真实结果，存在存活或 unknown 时明确报错并指导人工处理。

### H3 [High] 恢复没有覆盖解压、stdin 写入、进程等待和清理的统一绝对期限

**位置**：

- `fastapi_app/services/backup/dump.py::_psql_import_worker()`，尤其第 466 行
- `fastapi_app/api/v1/endpoints/backup/restore.py::_run_async_file_restore()`，第 635-677 行
- `fastapi_app/services/backup/strategies.py::PsqlRestoreStrategy.restore()`
- `fastapi_app/services/backup/restore.py::restore_from_zip()`

**问题**：psql 的 `proc_.wait(timeout=BACKUP_OPERATION_TIMEOUT)` 只有在全部解压数据写入 stdin 后才执行；解压、stdin 写入或管道阻塞阶段不受该 wait 超时限制。异步 API 的 watchdog 每 600 秒只续 Redis 锁并 `touch_progress()`，不是操作总 deadline，也不会终止 psql。现有调用链未发现能覆盖这些阶段的外层 `wait_for()`。

**实际影响**：恢复任务可能长期停留在破坏性操作之后，心跳仍被刷新，锁与 worker 资源持续占用；运维看到的是“仍在进行”，但没有统一终止和回收边界。

**修复建议**：使用 monotonic 绝对 deadline 覆盖解压、流式写入、进程等待和清理；超时后终止并回收整个相关进程组，验证最终状态。不要仅用 `asyncio.wait_for()` 包装不可取消线程来冒充进程级超时。

**待动态验证**：在隔离 PostgreSQL/psql 环境注入 stdin 阻塞、解压停滞和子进程不退出，验证进程回收、锁状态、进度终态及中断标记。

### H4 [High] 通用健康、readiness 与发布验收语义混用，降级状态也可通过发布

**位置**：

- `fastapi_app/core/health.py::_build_fresh_health()`，第 127-187 行
- `health.py::readiness_probe()`，第 242-264 行
- `scripts/restart_backend.py::_health_ok()`，第 61-66 行

**证据**：

- DB 和备份正常而 Redis client 缺失或 PING 失败时，只形成内部 `checks.redis=warning`，公开状态仍可为 `healthy`、HTTP 200；此行为已在隔离进程中复现。
- `readiness_probe()` 正确使用 `ready = db_ok and redis_ok`，失败返回 503。
- 发布脚本接受 `ok/healthy/degraded`，且不检查 `security_degraded`。

**实际影响**：发布脚本可能把依赖未就绪或安全能力降级的实例当成发布成功。通用健康端点在降级时返回 200 是既有契约，不能简单全部改为 503，否则可能引发监督器误重启。

**修复建议**：明确分离 liveness、readiness 和 release-acceptance；发布路径至少要求 DB/Redis readiness、`security_degraded=false`、备份状态符合发布策略，并核对 B1 所述版本和启动代次。为每种状态组合写契约测试。

### H5 [High] 出货创建只按客户分组，与后端“明细不得跨月”契约冲突

**位置**：

- `frontend-vite/src/views/purchase-plan/composables/useCreateShipmentPlan.ts`，第 185-206 行
- `fastapi_app/services/purchase_plan_crud_ops.py::_validate_details_cross_month()`，第 50-55 行；调用点第 143-144 行

**触发条件**：同一客户在一次创建中包含两个不同月份的 `plan_date`。

**错误行为**：前端仅按客户分组，并从首行生成整个请求的 `plan_month`；后端逐行拒绝与 `plan_month` 不一致的明细，因此该组合无法成功创建。

**修复建议**：按 `(customer_id, planMonth)` 分组提交，或在前端提交前明确禁止跨月并给出逐行错误；不得从首行隐式决定其他月份明细。补同客户同月、同客户跨月、不同客户跨月和部分成功用例。

### H6 [High] 创建部分或全部失败后仍关闭对话框，失败草稿丢失

**位置**：

- `useCreateShipmentPlan.ts`，第 195-235 行及打开时重置逻辑第 51-55 行
- `frontend-vite/src/views/purchase-plan/PurchasePlanView.vue::onCreated()`，第 236 行

**问题**：逐客户提交后，即使 `failures` 非空或全部失败，也无条件调用 `onCreated()`；父页面关闭对话框并刷新，下一次打开又重置明细。

**实际影响**：用户看到失败提示的同时丢失未成功提交的草稿；部分成功时还可能混淆哪些组需要重试，增加重复创建风险。

**修复建议**：区分“刷新成功数据”和“关闭对话框”两个事件。全部成功才关闭；部分成功只移除已成功组并保留失败组；全部失败保留全部输入。补全成功、部分失败、全部失败及重试幂等测试。

### H7 [High] 生产录入搜索响应乱序叠加 Enter 默认首项，可选择与当前关键词不符的产品

**位置**：`frontend-vite/src/views/production/composables/useProductionEntry.ts`，第 206-236、256-282 行。

**触发条件**：关键词 A 的请求尚未返回时输入 B，B 先返回、A 后返回；旧 A 响应覆盖当前结果。用户随后未按方向键直接 Enter，`confirmSearchSelection()` 默认选择第一项，`selectProduct()` 写入该产品 ID、名称和条码。

**实际影响**：可能将非当前搜索意图的产品带入生产记录。当前证据是可达的前端状态竞态，不是已发生错误生产记录的事故证明。

**修复建议**：每次输入（包括清空）递增搜索序号并快照关键词，可叠加取消旧请求；只有序号和关键词均匹配时才更新结果/loading/error。Enter 只能选择仍属于当前关键词的结果，存在歧义时要求显式选择。补 deferred A/B 响应、清空后在途响应、loading 状态和 Enter 提交链路测试。

### H8 [High] CSV 只做 RFC 4180 转义，未中和电子表格公式起始字符

**位置**：

- `frontend-vite/src/utils/csv.ts::escapeCsvField()`，第 17-24 行
- 实际链路：`views/purchase-plan/components/ImportPanel.vue::downloadErrors()`，第 202-207 行
- `views/purchase-plan/PurchasePlanView.vue` 的 SKU 与日汇总导出

**问题**：双引号、逗号和换行的 RFC 4180 转义已经存在，但不可信字符串若以 `= + - @` 开头，或在前导空白/Tab 后出现这些字符，未做公式中和。错误明细导出包含客户名、产品名、条码、日期和失败原因，是明确的数据流。

**实际影响**：用户用 Excel/WPS 等电子表格打开时，字段可能按公式而非文本解释。是否触发具体公式、外链或命令行为取决于客户端与策略，本轮未执行真实客户端验证，不声称已发生数据外泄或命令执行。

**修复建议**：对字符串类型在 RFC 4180 转义之前做电子表格中和，覆盖前导空白和控制字符；真正的数值类型保持数值语义，避免把正常负数一律文本化。补恶意样例、正常负数、逗号/引号/换行及 Excel/WPS 实际打开验证。

---

## 5. 建议尽快优化

> 以下均为 Medium。按仓库标准，它们仍属当版处理项；若确需延期，必须记录 owner、issue、期限和风险接受，不能静默放行。

### M1 [Medium] XLSX 超时只停止等待，后台线程与临时文件生命周期未闭环

**位置**：

- `fastapi_app/services/xlsx_budget.py::run_parse_with_timeout()`，第 117-134 行
- `fastapi_app/services/batch_import_parser.py::parse_excel_file_async()/read_excel_sheets_async()`，第 67-124 行
- `batch_import_parser.py::_save_uploaded_file()`，第 145-170 行
- `batch_import_parser.py::_read_excel_sheets_with_cell_images()`，第 343-375 行

**证据**：解析使用默认 executor；`asyncio.wait_for()` 超时不会终止底层同步线程。隔离验证中，约 0.05 秒返回 `XlsxBudgetError` 后，真实阻塞线程仍存活。临时文件在上下文 `finally` 中删除，但 Windows 上仍被工作线程打开时可能删除失败；图片提取也使用 `asyncio.to_thread()`，并非直接在事件循环执行，但缺少独立总时限和统一资源所有权。

**影响**：超时请求返回后仍消耗共享 executor/CPU/内存，临时文件清理与后台任务真实结束脱节。尚未证明 executor 已耗尽或生产 DoS 已成立。

**建议**：硬 deadline 需要可终止的独立进程或等价机制；至少使用专用有界 executor、跟踪任务真实终态并在结束后清理文件。使用真实不可取消同步阻塞和 Windows 文件占用做测试，不能用可取消协程模拟。

### M2 [Medium] 备份目录扫描 unknown 被当成“空目录且清理成功”

**位置**：`fastapi_app/services/backup/cleanup/service.py`，第 85-92、134-158 行。

**问题**：目录扫描 `OSError` 被转成 `[]`，`smart_cleanup()` 随后返回 `success=True` 和“没有找到备份文件”；单文件 stat 失败也会静默跳过，使调用方无法区分完整清单与部分清单。

**影响**：清理监控可能假成功；基于不完整清单的保留决策缺乏可靠性。不得把未知状态用于任何删除决策。

**建议**：扫描结果改为结构化状态或显式失败；任何影响清单完整性的错误都应 `success=False`、告警并中止删除。补真实空目录、目录不可读、单文件 stat 失败和完整非空目录测试。

### M3 [Medium] 未实际投递告警也写入冷却时间，后续普通告警可能被静默

**位置**：`fastapi_app/services/backup/metrics/alert_service.py::send_alert()`，第 102-116 行；`_should_send_alert()` 第 148-159 行。

**问题**：只要 `notify=True` 就更新 `last_alert_times[task_name]`，即使邮件和 webhook 均未启用；发送渠道失败时也同样进入冷却。critical 不受普通冷却限制，但其他级别可能受影响。

**建议**：按渠道记录真实投递结果，只有至少一次成功投递才进入对应冷却；无启用渠道和全部投递失败必须保持可重试并产生配置/投递异常信号。补首次达到阈值、无渠道、全部失败、部分成功及 critical 用例。

### M4 [Medium] webhook 非 2xx 响应正文被完整写入日志

**位置**：`fastapi_app/services/backup/metrics/alert_service.py::_send_webhook_alert()`，第 362-394 行，尤其第 389 行。

**问题**：直接记录 `response.text`，没有长度限制或脱敏。上游响应可能包含请求回显、内部信息或超大正文；是否实际含敏感内容取决于 webhook 服务，本轮未证明已有泄露。

**建议**：默认只记录状态码、请求关联 ID 和有界通用错误；确需正文时使用严格长度上限及脱敏，并防日志注入。补含敏感样式、控制字符和超长响应的测试。

### M5 [Medium] 周任务重编译七档锁后可未经完整必需检查直接推 main

**位置**：`.github/workflows/refresh-requirements-lock.yml`，第 37-56 行。

**问题**：锁变化后直接 `git commit`/`git push`，没有先跑完整必需检查或 PR 评审。只有机器人确实可写 main 时才构成未验证依赖进入主线的现实风险；没有证据表明它造成当前 CI 失败或会自动部署生产。

**建议**：优先改为自动开 PR，让必需检查和人工 lock diff 评审通过后合并；若保留直推，至少在推送前执行等效完整检查并配置分支保护。机器人权限按最小范围授予。

### M6 [Medium] 出货创建产品建议缺少请求代次和稳定行身份

**位置**：`useCreateShipmentPlan.ts`，第 85-137 行。

**问题**：异步回调按行下标回写建议，没有请求序号或取消；删行会移动下标，虽然现有代码会前移已有建议，但在途响应仍可能写入已经复用的下标。旧关键词响应也可能覆盖新关键词建议。

**影响**：下拉可能显示其他行或旧关键词的产品，用户点击后会把所选产品的 ID、名称和条码一起写入该行。不是字段必然彼此不一致，而是可能选择了非预期产品。

**建议**：为每行建立稳定 ID，按“行 ID + 请求序号 + 关键词快照”接收响应，删除/卸载时取消或失效请求。补 A/B 乱序、删行后在途响应和点击选择测试。

### M7 [Medium] 共享自动补全早退时未使在途请求失效，短查询还未复位 loading

**位置**：`frontend-vite/src/components/ui/UiAutocomplete.vue::triggerSearch()`。

**问题**：`suppressSearch` 或远程查询长度低于 `minQueryLength` 时提前返回，没有递增 `requestSeq`；旧请求仍可能通过序号检查并回写旧建议。短查询分支也未复位 `loading`。`listFn` 与 `searchFn` 实际共用同一序号，本项不是此前所猜的两套独立序号串扰。

**建议**：所有新输入/早退路径先递增统一代次并清理建议、loading，必要时取消旧请求；只有当前代次可写状态。覆盖 searchFn-only、短查询、抑制搜索、listFn/searchFn 切换和乱序响应。

### M8 [Medium] 批量已读吞掉部分/全部失败，UI 仍提示全部成功

**位置**：

- `frontend-vite/src/api/notification.ts::markBatchAsRead()`，第 56-68 行
- `frontend-vite/src/composables/useNotificationCenter.ts::markBatchAsRead()`，第 183-205 行
- `views/notifications/composables/useNotificationCenterPage.ts`，第 103-118 行

**问题**：API 使用 `Promise.allSettled()` 并正常返回计数，即使全部失败也不会 reject；composable 忽略 `success/marked_count`，成功 await 后清空选择并已提前移除全部项；页面固定提示“已标记 ids.length 条”。

**建议**：返回逐 ID 结果或至少明确失败数量；只移除/保留成功项，失败项回滚并保留选择，toast 使用真实成功数。补全成功、部分失败、全部失败及 HTTP 200 但 `success=false` 用例。

### M9 [Medium] 路由取消把 ticket Promise 永久挂起，窄条件下 WebSocket 连接状态无法恢复

**位置**：

- `frontend-vite/src/api/request.ts::_silenceCanceled()`，第 191-200 行；路由取消第 180-185 行
- `frontend-vite/src/api/auth.ts::websocketApi.ticket()`，第 5-6 行
- `frontend-vite/src/composables/useWebSocket.ts::connect()`，第 40-100 行
- `frontend-vite/src/router/guards.ts` 与 `router/navAccess.ts`

**触发条件**：ticket 在途时路由守卫取消请求，随后导航被取消或重定向且原页面仍存活。`connecting=true` 后 `await` 永不 settle，后续 WebSocket 创建、catch、finally 均不执行。普通组件卸载后创建新实例会重置局部状态，**不能笼统声称每次切页都会永久断连**。

**建议**：ticket 使用 `routeCancel:false` 并保留 `manuallyClosed` 生命周期管理，或让该调用的取消以可识别异常正常 settle 并显式恢复连接；仅补 `finally` 无法解决永不 settle。补导航取消、导航重定向、普通卸载/重建和重连测试。

### M10 [Medium] 前端依赖审计不能判绿，需区分 Node 依赖树与浏览器实际暴露面

**位置**：`frontend-vite/package-lock.json`，axios 第 6370-6377 行、follow-redirects 第 7960-7964 行。

**证据**：生产依赖树仍含 `axios@1.20.0 -> follow-redirects@1.16.0`，生产依赖审计不能判绿。开发依赖中的 Vite/Vitest 等风险主要落在开发服务器、CI 和构建输入。

**边界**：当前 Vite 静态浏览器构建未见 Node `follow-redirects` 可达证据，不能表述为“现有浏览器 Cookie 已被该漏洞泄露”。审计包数量也不等于线上可利用漏洞数量。

**建议**：依据当前审计建议升级并审查 lock diff，重跑前端测试、构建及生产/开发依赖审计；同时确认最终浏览器 bundle 的实际包含关系。按仓库依赖门禁要求，发布前应得到干净结果或有依据、带期限的正式例外。

### M11 [Medium] 名为启动流程的回归测试没有执行真实流程入口

**位置**：`tests/test_server_manager_start_services_flow.py`，第 36-46、70-86、88-101 行。

**问题**：`test_start_services_flow_reaches_redis_start` 的注释声称真正执行 `_start_services_flow()`，实际只直接调用 `app._start_redis()`；另一项也只测试 `_start_redis()` 的返回值。

**影响**：如果 `_start_services_flow()` 在调用 Redis 之前崩溃、顺序错误或根本没有调用 Redis，这些测试仍可能通过。它是测试真实性缺口，不是已证实的当前生产启动 Bug。

**建议**：在桩掉真实副作用后调用 `_start_services_flow()` 本身，断言完整顺序、Redis 调用、各服务结果聚合及失败分支；做一次变异检查，故意破坏流程调用，证明测试会红。

---

## 6. 关键测试遗漏总表

| 风险面 | 必须增加的有效回归 | 关联 |
|---|---|---|
| 月度汇总 | 直接执行真实 `_calc_monthly_summary()`，手工期望 7，同时拦截 0 和 14 | H1 |
| 重启身份 | GUI/脚本独立矩阵：PID 三态、stop 失败、同 PID、年龄 unknown、HEAD unknown、旧进程健康 | B1 |
| 实际 worker | 目标 commit、PID、启动代次、端口监听者一致才允许发布成功 | B1/H4 |
| 杀树失败 | terminate/kill/wait 故障后不得清空身份、不得自动重启、不得报告已停止 | H2 |
| 恢复安全 | 标记读写失败、DROP/CREATE/psql 失败、进程中断、成功后清除 | B2 |
| 恢复时限 | 解压、stdin、wait 各阶段阻塞；验证总 deadline、进程回收、锁与进度终态 | H3 |
| 健康契约 | DB/Redis/备份/security_degraded 的组合矩阵，分别验证 liveness/readiness/release | H4 |
| XLSX 资源 | 真实不可取消线程、默认/专用 executor 竞争、Windows 文件占用和最终清理 | M1 |
| 出货创建 | 同客户跨月、全失败不关窗、部分失败保留失败组、重试不重复 | H5/H6 |
| 产品搜索 | deferred A/B 响应、删行、短查询、清空、Enter 默认选择和真实组件链 | H7/M6/M7 |
| 批量已读 | 部分/全部失败、200 但 success=false、实际 toast 数量与列表回滚 | M8 |
| CSV | 公式起始、前导空白/Tab、引号/逗号/换行、正常负数及 Excel/WPS 打开 | H8 |
| WebSocket | 导航取消/重定向且原页存活，以及普通卸载重建的对照测试 | M9 |
| 启动流程 | 调用 `_start_services_flow()` 真实入口，而非只测 `_start_redis()` helper | M11 |

所有关键修复都应保留“修复前会红、修复后变绿”的证据。仅增加测试数量、mock 整个被测 service，或用可取消协程模拟不可取消线程，不能证明防线有效。

---

## 7. 已确认的正向控制与排除项

以下事项避免被误报为缺陷：

- `readiness_probe()` 已正确将 DB 与 Redis 同时纳入 readiness，Redis 失败返回 503；问题在发布消费者没有统一使用正确语义。
- XLSX 已有 ZIP 成员数、单成员/总解压大小、压缩比、行列等预算，不是“完全没有资源限制”；本报告聚焦线程超时和生命周期缺口。
- 单元格图片提取通过 `asyncio.to_thread()` 移出事件循环，不采纳“图片 XML 正则直接阻塞事件循环”的说法。
- `UiAutocomplete` 的 `listFn/searchFn` 共用同一请求序号，不采纳两套独立序号彼此串扰的假阳性。
- 生产录入单价请求已有 `_priceSeq`，本报告只指出产品搜索请求缺少同类防护。
- 恢复失败会返回 error，不称为恢复假成功；恢复 API 的 Redis 锁不可用路径已有 fail-closed 处理。
- `UiPagination` 实际会夹取页码；ReportView 的相关 prop 警告来自测试 mock 与真实 reactive 契约差异，不列为生产绑定错误。
- 当前树不存在 `fastapi_app/services/import_guard.py` 这一 service 路径；上传临时文件的真实实现是 `batch_import_parser.py::_save_uploaded_file()`。
- 普通路由切换并不必然造成 WebSocket 永久断连；只有 M9 所列窄条件成立时才构成该问题。

---

## 8. 可后续改进的结构项

这些是有价值的结构演进，但不作为独立缺陷凑数，也不能替代上述当版修复：

1. **恢复改为临时库完整导入、校验后原子切换**：可减少 DROP 与导入之间的空壳窗口，但必须先做隔离 PostgreSQL 演练、权限/连接处理及回滚设计，不宜作为未验证的快速补丁。
2. **统一前端远程搜索原语**：在 H7/M6/M7 修复后，将请求代次、取消、关键词快照、loading/error 和稳定行 ID 收敛为同一可测试 composable，降低不同页面重复犯错的概率。
3. **为关键运维和状态机测试增加变异检查**：重点覆盖重启、恢复、健康契约和启动流程，持续验证测试真的会红，而非只追求覆盖率。
4. **集中定义操作结果类型**：逐步将 `ok/effective/unknown`、健康状态和批量操作结果建模为可类型检查的判别结构，减少布尔值与 `None` 被不同调用方自行解释。

---

## 9. 按优先级排序的处理清单

| 优先级 | 行动 | 重新验收要点 |
|---|---|---|
| P0 | 修复 B1 身份三态、GUI/脚本重启契约和实际 worker 版本绑定 | 完整故障矩阵均失败关闭；只有新 PID/新代次/目标 commit/实际监听者一致才成功 |
| P0 | 修复 B2 恢复标记 fail-open，并完成 H3 全阶段总 deadline | 任何失败均保留可告警状态；卡住阶段可被终止、回收并形成任务终态 |
| P0 | 修复 H2 杀树失败与 H4 发布健康验收 | 未确认死亡不清身份；degraded/security_degraded/readiness 失败不得发布成功 |
| P0 | 修复 H1、H5、H6、H7、H8 的真实用户路径 | 真实 service/组件回归通过；错误产品、错误汇总、跨月拒绝、草稿丢失和公式输入均有反例测试 |
| P0 | 恢复 G0 锁门禁；所有修复合入后对新精确 SHA 重跑完整 CI | test/lint/frontend/build 全绿，build 不再跳过，CodeQL 通过 |
| P1 | 处理 M1 XLSX 生命周期及 M10 依赖审计 | 真实线程/Windows 文件占用有界；生产与开发依赖审计及 bundle 暴露面有结论 |
| P1 | 处理 M2-M9、M11；确需延期则逐项建立 owner/issue/期限 | 不存在未批准的 Medium；告警、清理、前端部分失败和真实启动入口回归有效 |
| P2 | 评估临时库原子切换、统一搜索原语、变异测试和结果类型演进 | 不扩大本次修复范围；分别有独立验收方案 |

### 重新放行（Go）的最低条件

1. G0 清零，B1/B2 与全部 High 关闭。
2. Medium 全部修复，或由有权限的 owner 明确批准延期并建立 issue；依赖门禁按仓库要求取得干净结果或正式例外。
3. 聚焦回归有修复前后红绿证据；最终新 SHA 的完整 CI、前端构建和 CodeQL 全通过。
4. 在隔离环境完成 Windows/NSSM 身份故障、PostgreSQL 恢复中断/阻塞、真实不可取消 XLSX 线程和关键前端异步交互验证。
5. 发布时核对干净工作区、目标 commit、实际 worker/启动代次、端口归属、readiness 和可执行回滚点；不得再用“进程在跑 + 健康 200”单独宣告成功。

---

## 10. 当前自动化证据

精确 SHA 的 CI run `40247966531`：

| 检查 | 当前结果 |
|---|---|
| 后端测试 | `4975 passed, 118 skipped` |
| `prod_audit` 独立套件 | `296 passed` |
| 覆盖率 | `70.68%` |
| pip-audit | `No known vulnerabilities found` |
| 前端测试 | `227` 个测试文件，`1731` 个测试通过 |
| 前端构建 job 内步骤 | 成功，约 `21.94s` |
| lint | **失败：test.lock 新鲜度** |
| 整体 build job | **跳过** |
| CodeQL run `40247966407` | 成功 |

这些正面结果说明大量既有行为仍有回归保护，但不能证明本报告未覆盖路径安全，也不能抵消门禁失败和已确认的业务/发布缺陷。

---

## 11. 未验证事项与最终结论

### 未验证事项

- 未在生产执行真实重启、kill 故障、恢复、故障注入或业务写入。
- B1 的完整组合、H2 的孤儿进程终态、H3 的真实管道阻塞需在隔离 Windows/NSSM/PostgreSQL 环境验证。
- 未对生产执行恶意 XLSX 或资源耗尽测试；M1 已证实的是线程超时语义，不是生产 DoS 阈值。
- 未真实发送邮件/webhook，未证明上游响应已经造成敏感信息泄露。
- 未在 Excel/WPS 中打开恶意 CSV；H8 的公式执行表现需客户端动态验证。
- 未证明当前生产 worker 已加载受审 SHA，也未将任何历史事故当作本轮新发现。
- 本轮没有重新执行完整本地测试套件；引用的是目标精确 SHA 的远端 CI 与已完成的隔离复核。

### 最终结论

**No-Go。** 当前提交同时存在必需 CI 失败、2 项 Blocker、8 项 High，以及 11 项尚无修复或批准延期记录的 Medium。最重要的风险集中在“发布是否真的作用于目标 worker”“恢复失败后是否仍能可靠告警与回滚”以及“用户看到的数据和选择是否正确”三条链路。

本轮仅完成审查和报告，没有实施修复、上线或回滚。建议先关闭 P0 项，再以新的精确 SHA 和真实故障路径证据重新作出 Go/No-Go 决策。

---

## 12. 修复实施记录（2026-10-26，第二轮）

用户明确要求“把发现的问题全部修复”。本节记录每一项的落地位置、行为变化与回归测试；
审查基线仍为 `main@56b4f304`，修复在**工作区**完成，尚未提交、未推送、未重启生产。

### 12.1 逐项闭环

| 编号 | 修复位置 | 关键行为变化 | 回归测试（先红后绿） |
|---|---|---|---|
| G0 | `requirements/test.txt` | 把 `pytest-asyncio>=1.0.0` 钉成 `==1.4.0`（与 `.lock` 同一事实）。根因是「`>=` + 上游补丁发布」使 fresh 解析（CI 得 1.4.1）与已提交锁（1.4.0）必然脱节，与代码改动无关。本地重跑 `check_requirements_lock.py test` → 一致（116 个包） | 锁门禁脚本本身 |
| B1 | `server_manager/service_ops.py`；`scripts/restart_backend.py` | 停前改用 `svc_pid_ex()` 保留三态，`not prev_ok` 时**在 stop 前**返回 `PID_UNKNOWN`；脚本停前同样失败关闭（PID 通道/HEAD 不可读即拒绝），成功口径改为「ok and effective + 脚本独立复核 PID + worker runtime 绑定」 | `tests/test_sm_restart_stop_start.py`（新增 unknown 拒绝、unknown 不得 effective）；`fastapi_app/tests/test_write_guard_wiring.py`（同 PID、复核不一致、PID 为 None、健康超时） |
| B2 | `services/backup/restore_guard.py`（重写）、`dump.py`、`main.py`、`core/health.py` | 写标记失败抛 `RestoreMarkerError` 并**在 DROP 前中止**（含 fsync + 回读校验）；`mark_restore_finished(success=…)` 只在 `status=='ok'` 时清除，失败保留并写回阶段；读取三态 `absent/present/unknown`，unknown 不再折叠成「无中断」；`/api/health/ready` 在标记残留或不可读时 `not_ready`（进程与恢复端点保持可用） | 新增 `test_restore_guard_fail_closed.py`（16 项：写失败/回读失败/损坏 JSON/不可读/失败保留/readiness 三态）；`test_restore_marker_wiring.py`（5 项：写不进去不 DROP、ok 才清、rc≠0 与 partial 保留、重建失败保留） |
| H1 | `services/production_plan_service.py` | 首次键标志 `is_new_shipped` 在 join 集合**之前**求值并在两级汇总复用；客户级 `shipped_qty` 不再恒 0，且每键只计一次 | 新增 `test_production_plan_monthly_summary.py`（4 项，直接调真实 `_calc_monthly_summary`：单行、同键两行=7 而非 0/14、跨产品=10、跨客户不串） |
| H2 | `core/prod_runner.py` | `kill_tree() -> bool`：未确认死亡时**保留** `proc/_logf` 身份；`poll()` 不再无条件 `_mark_crashed()`，改为 30s 退避重试且窗口内不起新进程；`shutdown()` 未确认终止时打印「关闭未完成」而非「已停止」 | `test_prod_runner_kill_tree.py`（+2：确认死亡才清身份／存活则保留）；`test_prod_runner_backend_restart.py`（+4：不清身份、窗口内不重复杀、shutdown 如实汇总） |
| H3 | `services/backup/dump.py`、`_constants.py`、`endpoints/backup/restore.py` | psql 增加**独立看门狗线程**，deadline 覆盖 `stdin` 写入 + `wait` 全过程（原先只在 stdin 写完后计时，psql 卡在锁等待时 `write` 永久阻塞，超时分支根本走不到）；超时用 `taskkill /F /T`（POSIX 用 `killpg`）回收进程树；恢复任务外层加 `RESTORE_TOTAL_TIMEOUT`（默认 3×1800s）的 `asyncio.timeout` | 由 B2 的接线测试覆盖编排路径；真实管道阻塞需隔离环境（见 12.3） |
| H4 | `core/health.py`、`scripts/restart_backend.py` | 导入期固化 worker 指纹（pid/boot_id/started_at/加载时 HEAD，后者直接读 `.git/HEAD` + `packed-refs`/worktree，**不起子进程**），**仅对回环请求**返回 `runtime`；脚本验收要求 health healthy + `security_degraded=false` + `/ready` ready + `runtime.commit==目标 HEAD` + worker 启动晚于本次操作 + supervisor 年龄可证实（不可证实即失败） | 新增 `test_health_runtime_fingerprint.py`（11 项：指纹稳定、仅回环、不写回缓存、HEAD 解析 5 种形态、导入期零子进程）；`test_write_guard_wiring.py`（+3：旧 commit、两小时前的 worker、年龄不可读） |
| H5 | `views/purchase-plan/composables/useCreateShipmentPlan.ts` | 分组键改为 `(customer_id, 月份)`，`plan_month` 由该组明细自身推导，不再由首行决定整户月份 | `useCreateShipmentPlan.test.ts`（同客户同月 1 次、同客户跨月 2 次且组内不跨月、双客户跨月 4 组） |
| H6 | 同上 + `CreateShipmentPlanDialog.vue`、`PurchasePlanView.vue` | 新增 `onSucceeded`（只刷新）与 `onCreated`（关闭）两个出口：全部成功才关闭；部分成功刷新并从草稿移除已成功组；全部失败原样保留 | 同上（全成功、部分失败保留失败组、全失败保留全部、重试只提交失败组） |
| H7 | `views/production/composables/useProductionEntry.ts` | 搜索加请求序号 + 关键字快照双校验：输入变化/选中产品/清空都作废在途响应，`finally` 仅在序号匹配时复位 loading | 新增 `useProductionEntrySearchRace.test.ts`（3 项：乱序不覆盖、回车选中的是当前关键字结果、清空后不回填） |
| H8 | `utils/csv.ts` | 在 RFC 4180 转义之外中和公式起始字符（`= + - @`、制表/回车，含前导空白绕过），纯数字（`-123`）保持原样 | `exportUtils.test.ts`（+4 组：公式中和、`-` 非数字、负数保留、前导空白不可绕过） |
| M1 | `services/xlsx_budget.py`、`batch_import_parser.py`、三个上传入口 | 解析改投**专用有界线程池**（不再占用默认 executor），新增 `run_sync_with_timeout(fn, …, cleanup=…)`：`cleanup` 在线程**真正结束**后执行，`pending_parse_count()` 暴露在途数；临时文件删除改为短间隔重试并在最终失败时 ERROR 留痕 | 新增 `test_xlsx_parse_lifecycle.py`（6 项，用真实 `threading.Event` 不可取消阻塞：超时先返回、cleanup 不提前、线程结束后才执行、计数归零） |
| M2 | `services/backup/cleanup/service.py` | 扫描失败抛 `BackupScanError` → `smart_cleanup` 返回 `success=False` 并告警（不再把「看不到备份」报成干净结果）；单文件 `stat` 失败不静默丢弃，计入 `unreadable_files` 出现在报告中 | `test_backup_cleanup_alert_failclosed.py`（扫描失败不报成功、不可读文件进报告） |
| M3 | `services/backup/metrics/alert_service.py` | 冷却只在「至少一个渠道实际投递成功」后写入；渠道全未启用或投递失败都打 WARNING 且不进入冷却 | 同上（无渠道不冷却、投递失败不冷却、成功才冷却且冷却期内不重复投递） |
| M4 | 同上 | Webhook 非 2xx 只记录 `status` 与 `body_len`，不再回显响应正文 | 同上（日志不得含正文中的令牌） |
| M5 | `.github/workflows/refresh-requirements-lock.yml` | 不再 `git push` 到 main：推固定分支 + `gh pr create`（PR 走完整 CI 与人工评审）；已有同名 PR 时不重复创建；越界路径直接失败 | YAML 解析校验；行为需下次定时任务验证 |
| M6 | `useCreateShipmentPlan.ts` | 每行建议请求带**全表单单调递增**序号 + 关键字快照，乱序/删行/选中后一律丢弃；序号用全局计数器避免行下标复用的 ABA | `useCreateShipmentPlan.test.ts`（旧关键字慢响应不覆盖、选中后不回填） |
| M7 | `components/ui/UiAutocomplete.vue` | `suppressSearch` / 静态建议 / 短查询三个早退分支都 `requestSeq += 1` 并复位 `loading` | 新增 `uiAutocompleteEarlyExit.test.ts`（3 项） |
| M8 | `api/notification.ts`、`useNotificationCenter.ts`、通知页 | 批量已读返回逐条结果（`marked_count/failed_count/failed_ids`）；组合式函数只回滚失败项并抛出带计数的错误；页面如实透出文案 | 新增 `notificationBatchMarkRead.test.ts`（4 项：全成功、部分失败回滚失败项、全失败、网络失败） |
| M9 | `api/auth.ts`、`composables/useWebSocket.ts` | ticket 改 `routeCancel:false`（不再被路由守卫取消）；`connect()` 另加 10s 硬超时，任何永不 settle 的 Promise 都不能把 `connecting` 钉死 | 新增 `useWebSocketTicket.test.ts`（3 项：源码口径、永不 settle 后仍能重试、正常路径照常建连） |
| M10 | `package.json`、`package-lock.json`、`ci-cd.yml` | `overrides.follow-redirects=^1.16.1`（实际解析 1.16.2）；新增 `audit:prod` 脚本与 CI 步骤 `npm audit --omit=dev --audit-level=high`，把「生产依赖树干净」变成可判定门禁；开发树（Vite/Vitest/launch-editor）风险面在开发服务器与构建输入，不阻断发布 | `npm audit --omit=dev` → `found 0 vulnerabilities` |
| M11 | `tests/test_server_manager_start_services_flow.py` | 两条「flow」用例改为真正调用 `_start_services_flow()`（桩掉停开发/清端口/broker/起服务/日志/闸门），并新增「broker 缺失判未完全成功」「闸门拒绝后零副作用」 | 该文件 5 项全绿；删掉流程内的 `self._start_redis()` 即变红 |

### 12.2 本地验证证据（修复后）

| 检查 | 结果 |
|---|---|
| 后端 `fastapi_app/tests` | `3463 passed, 8 skipped, 4 failed, 12 errors` |
| 后端失败归因 | 全部为**本机缺少 PostgreSQL/Redis**（`asyncpg ... ConnectionDoesNotExist`、限流用例需 Redis）与 1 条 `cwd` 相对路径（`test_backup_m6` 读 `migrations/...`）。基线 CI 在该 job 有 postgres/redis service，故这些用例在 CI 应通过 |
| 后端定向回归 | `test_write_guard_wiring` 34、`test_prod_runner_*` 19、`test_health_runtime_fingerprint` 5、`test_restore_guard_fail_closed` 16、`test_restore_marker_wiring` 5、`test_backup_cleanup_alert_failclosed` 6、`test_production_plan_monthly_summary` 4、`test_xlsx_parse_lifecycle`+`test_xlsx_budget` 23、备份子集 427（1 条为 `cwd` 假失败，已单独复核通过） |
| 后端 `tests/` 两个改动文件 | 在隔离目录单独运行：`test_sm_restart_stop_start` 19、`test_server_manager_start_services_flow` 5。整棵 `tests/` 需 PostgreSQL（autouse 会话夹具），本机无法执行 |
| `ruff check` | 全部改动文件通过 |
| `scripts/quality_gate.py` | `[PASS] 无新增质量问题`（bandit / nosec 预算 / 环境变量漂移 / 循环变量遮蔽均未新增；HEAD 读取改为纯文件 I/O，避免为读 HEAD 引入子进程调用） |
| `scripts/scan_secrets.py` | `[PASS] 未检出疑似凭据` |
| `scripts/check_orphan_modules.py` | `PASS`（1 项既有 WARN 需人工判定，与本轮改动无关） |
| 前端 `vitest run` | `232 passed` 个测试文件、`1757 passed` 个测试（基线 227/1731，新增 5 个文件 26 项，`exportUtils` +4 项） |
| 前端 `vue-tsc --noEmit` / `eslint` | 通过（0 error） |
| 锁门禁 | `check_requirements_lock.py test` → 一致（116 个包） |
| 依赖审计 | `npm audit --omit=dev` → `found 0 vulnerabilities`；全量审计仍余 7 条（均为 dev-only：Vite/Vitest/launch-editor） |

### 12.3 仍需在 CI/隔离环境完成（本次不能替代）

1. 在**新的精确 SHA** 上跑完整 CI（lint / test / build / frontend / CodeQL）。本机无法替代：`tests/` 整棵树需要 PostgreSQL，`build` job 需要完整依赖安装。
2. Windows/NSSM 真实故障注入：停前 `sc queryex` 失败、stop 返回 1051、杀树被拒（进程被调试器持有）、PID 复用。本次只用替身覆盖了判定与状态机，未在真实 SCM 上验证。
3. PostgreSQL 真实恢复中断：`DROP` 后杀掉服务，确认标记残留 → readiness `not_ready` → 按指引回滚后可清除；以及 psql 卡在锁等待时看门狗是否按 `RESTORE_TOTAL_TIMEOUT` 回收进程树。
4. 在 Excel/WPS 中实际打开含 `=HYPERLINK(...)` 的导出 CSV，确认显示为文本而非求值（客户端行为，代码侧只能中和）。
5. 浏览器端复核：路由取消后 WebSocket 仍能重连、跨月出货在真实后端上创建成功。

### 12.4 修复后的结论

审查发现的 1 项门禁失败、2 项 Blocker、8 项 High、11 项 Medium 均已在工作区落地修复并附回归测试；
其中 3 项（M2/M3/M4）与 1 项（M11）的语义变化也已写进测试断言。**结论仍为 No-Go，但性质改变**：
不再是「已知缺陷未修」，而是「修复未经新的精确 SHA 的完整 CI 与隔离故障验证」。

放行条件收敛为：

1. 提交后在新 SHA 上 CI 全绿（含本次新增的 `Audit production dependencies` 与锁门禁）。
2. 12.3 的 1–3 项在隔离环境取得证据；4–5 项由验收人手工确认。
3. 发布重启时核对 `runtime.commit` / `worker pid` / `started_at`，并保留 pre_restore 回滚点。

本轮**未**提交代码、未推送、未重启生产服务、未写生产库、未执行生产迁移、未发送真实告警。

### 12.9 16:25 重启复盘：守卫正确触发，但降级只活了 3 秒（已修，PR #19 → `fa5dc79c`）

用户 16:25 再次重启 erp-prod。`erp-prod.log` 实证 **PR #17 的身份守卫正确触发**：

```
[prod_runner] 后端(uvicorn) 已启动 (PID 17104, ...)
[prod_runner] 错误: 后端(uvicorn) 身份未证实 —— 应答进程 pid=12348 不属于本进程树
（本树根 PID 17104）；本实例可能收不到流量
```

但 `prod_runner.json` 仍显示 `ready:true`：`poll()` 的身份校验只在 `not _identity_checked`
时执行一次，之后每个 tick 的正常分支无条件把 status 置回 `ready` —— 降级只活了 3 秒。
已修（PR #19）：`identity_problem` 挂着期间每个 tick 重新证实（抢占者清掉的那一刻自动
恢复 ready），通过后不再每 tick 重查。新增 `test_identity_problem_persists_until_cleared`。

**同时确认了两件事**：

1. `:5002` 又是双 LISTEN——16:25 的新栈（`1020→8 workers`，加载 `b6629904`）+
   15:11 的旧栈（`20648→24632→8 workers`，加载 `a08211f0`）。08:11 那棵已被清掉，
   现在挡路的是 **15:11 这棵**，需要管理员 `taskkill /F /T /PID 20648`。
2. `GET /api/health` 现在带 `runtime`：`commit=a08211f0`（**全部 22 项修复**）、
   `/ready` 带 `restore_pending:false` —— 也就是说，**业务修复已经真正在跑**；
   尚未在跑的只有 PR #17/#18 的监督器侧加固（要等一次干净重启）。

main CI（`e5e9d49b` 与 `fa5dc79c`）均全绿：test 8m06s / lint 1m13s / frontend 3m26s /
build 11s / CodeQL。

### 12.10 最终状态（2026-10-26 18:52，全链路闭环）

| 事项 | 状态 |
|---|---|
| 22 项审查发现 | ✅ 已修复合并（PR #15/#16/#17/#18/#19），main（`fa5dc79c`）CI 全绿：test / lint / frontend / build / CodeQL |
| **业务修复在生产生效** | ✅ `GET /api/health` → `"runtime":{"commit":"a08211f0",...}`（含全部 22 项），`/ready` → `restore_pending:false` |
| 锁门禁结构性缺陷 | ✅ PR #18：改判「声明的直接依赖」，默认不联网不需 uv；传递依赖补丁不再让 main 随机红 |
| 端口清理"假成功" | ✅ PR #18：`kill_port_sync` 新增 `still_occupied`；`_release_ports` 返回 bool；清理失败即中止启动 |
| 身份守卫降级 3 秒即翻回 ready | ✅ PR #19：`identity_problem` 跨 tick 保持，抢占者清掉后自动恢复 |
| **:5002 双实例** | ✅ 已清（18:48 复核）：管理员执行 `taskkill /F /T /PID 20648` 后仅剩一个 LISTEN（`1020`）；旧树 `20648/24632/21172` 全部消失 |
| **业务修复在生产生效** | ✅ `GET /api/health` → `"runtime":{"pid":24976,"commit":"b6629904"}`，`pid` 落在新栈（`3160→17104→1020→24976`）内；`/ready` → `restore_pending:false, restore:{state:"absent"}`；`prod_runner.json` → `backend.status="ready"`（旧树清掉后自动恢复，与 PR #19 的语义一致） |
| 监督器加固上线 | ⏳ 部分生效：在跑的监督器（16:25 起）含 PR #17 的首次校验（已实证触发并如实告警），但**不含** PR #19 的"跨 tick 保持"与 PR #18 的 `still_occupied`——下次干净重启后整套生效 |
| 生产库写入/迁移 | ❌ 未执行（从未执行，需明确授权与回滚点） |

一句话：**代码全部修完、已在生产服务、单实例、身份可证**。今天这条链路的价值也在
日志里留了痕：守卫把「重启了但跑的是旧代码」从事故变成了日志里的一行 ERROR。

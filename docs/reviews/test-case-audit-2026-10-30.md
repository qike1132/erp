# 滨发协同系统测试用例全面审查报告

## 1. 基本信息

- **项目名称**：滨发协同系统（binfa-erp）
- **审查日期**：2026-10-30
- **代码基线**：`c6bbb48f`（`main`）
- **审查类型**：需求—实现—测试一致性审查、测试有效性审查、覆盖缺口分析
- **审查范围**：`tests/`、`fastapi_app/tests/`、`frontend-vite/src/test/`、浏览器/API E2E、CI 测试门禁，以及订单、采购、库存、出货、生产、外发、板房、审批、通知、备份等实现
- **安全边界**：未重启服务、未修改生产配置、未写生产库；后端聚焦测试使用显式测试密钥并屏蔽本机 `.env`

### 1.1 审查方法与证据

1. 静态盘点需求、业务规则、接口、服务和测试的对应关系。
2. AST 扫描测试收集、断言、跳过和接口引用；不把测试文件数或用例数等同于业务覆盖率。
3. 对核心模块逐文件核对测试数据、预期结果和副作用断言。
4. 实际执行聚焦测试并核查默认收集结果。

### 1.2 本次实测

| 验证 | 结果 | 说明 |
|---|---:|---|
| 后端默认收集（仅 `fastapi_app/tests`） | 3560 项 | `schedule_delete_guard_test.py` 不在收集结果中 |
| 未默认收集的备份守卫文件，显式执行 | 15 passed | 证明文件本身可运行，但默认套件漏跑 |
| 后端重点测试 | 98 passed | 湖北订单、订单边界、审批、备份完整性 |
| 前端关键交互测试 | 49 passed / 5 文件 | BOM 续提、采购行、弹窗、湖北确认 |
| 前端测试资产静态盘点 | 236 个测试文件 | 仅为资产数，不代表业务覆盖率 |
| 后端测试资产静态盘点 | 512 个文件 / 4616 个测试函数定义 | 排除 `tests/qa`、`tests/stress`；参数化展开前口径 |
| 全量后端 `tests + fastapi_app/tests` | 未执行 | 本次不做全量通过声明 |
| 真实隔离后端 API E2E / 动态契约比对 | 未执行 | 当前环境未配置隔离实例；CI 同样不执行动态部分 |

> 2026-10-27 历史报告中的后端 71.02%、前端约 54% 覆盖率属于当时基线，不能替代本次当前提交的全量覆盖率实测。

## 2. 总体结论

**现有测试对大量已知缺陷具有有效回归保护，但不能仅凭“全绿”认定核心业务覆盖完整。** 本次确认两项 P0 级测试证据问题：一份备份守卫测试文件默认不收集；真实 API 写路径和动态契约比对不在 CI 执行。另有多项 P1 级问题：核心断言过弱、筛选/软删除用例无效、库存缺少真实并发验证、关键 API 与跨组件链路缺测、共享测试数据存在顺序耦合。本报告评价的是测试证据本身，不把覆盖缺口直接等同于已证实的业务代码缺陷。

- **正常流程**：订单、采购、库存、退货、备份等领域覆盖较多，但部分“正常流程”仅验证 mock 返回或状态非空。
- **异常流程**：输入校验和业务错误覆盖较广；真实服务不可用、事务失败、并发冲突和跨用户隔离仍有缺口。
- **边界条件**：数量上下限、分页、时间、文件限制等较好；湖北采购单混合状态与差异化 MAX 数据不足。
- **模块交互**：服务层集成较强，真实前后端/浏览器闭环、采购页 BOM 组件串联、部分 HTTP 端点覆盖不足。
- **测试适配性**：存在未默认收集、重复、mock 自证、未接线特性测试被误认为现役覆盖，以及 PRD 与现行验收口径漂移。

## 3. 关键业务规则与风险分析

| 规则 ID | 业务规则 | 主要风险 | 当前测试判断 |
|---|---|---|---|
| BR-01 | 订单筛选、软删除和工厂隔离必须真实作用于查询 | 错单、跨厂数据泄漏 | 部分用例为 mock 自证；软删除用例数据错误 |
| BR-02 | 湖北开单仅看 completed 采购单；多单数量/备品按既定口径计算 | 误开单、数量高估或重复计数 | 主路径较强；混合状态和 MAX 变异敏感性不足 |
| BR-03 | 出库、退货、取消必须同步库存、流水、FIFO 和订单状态 | 超卖、库存与状态不一致 | 单事务集成较强；真实并发及 E2E 状态断言不足 |
| BR-04 | BOM 续提必须幂等、全 SKU 齐备才生成、同来源不重复 | 重复采购单、错误 SKU、重复提交 | 后端较强；采购页组件串联未闭合 |
| BR-05 | 审批只能由合法用户执行，审批/取消不能重复生效 | 越权、重复写入、状态覆盖 | 状态机和服务测试较多；HTTP/真实并发不足 |
| BR-06 | 通知和死信操作必须限定当前用户/超管并保证失败安全 | 越权已读、重复重试、死信丢失 | 直接 API 测试缺失 |
| BR-07 | 备份调度守卫与恢复必须可执行、可证明 | 自动校验被删、灾备能力假健康 | 一份关键守卫测试默认漏跑；部分权限分支长期跳过 |

## 4. P0：必须优先修正

### P0-01 备份调度删除守卫测试默认完全未收集

- **位置**：`pytest.ini:4`；`fastapi_app/tests/schedule_delete_guard_test.py:52-157`
- **事实**：项目只收集 `test_*.py`，该文件以 `_test.py` 结尾。默认收集 3560 项时，文件中 15 项参数化用例均未出现；显式指定文件后 15 项全部通过。
- **影响**：测试资产存在但 CI 不提供任何保护。删除 `integrity_check`、`disaster_recovery_test` 等校验任务的守卫若回归，默认套件仍可能全绿，直接削弱备份可恢复性保障。
- **改进**：
  1. 将文件改名为 `test_schedule_delete_guard.py`，保留现有 15 项测试。
  2. 在 CI 增加“默认收集结果必须包含指定关键用例”的收集守卫，防止改名/路径漂移再次静默漏跑。
  3. 收集后同时跑正常删除、整类禁止删除、禁用后删除、改名绕过和不存在 ID 五类场景。

### P0-02 真实 API 写路径与动态契约比对未进入 CI 判定

- **位置**：`tests/e2e_api/conftest.py:231-268`；`tests/e2e_api/test_write_paths.py`；`tests/contract/test_api_contract.py:55-58,106-137`；`.github/workflows/ci-cd.yml:111-115`
- **事实**：8 项鉴权 E2E + 7 项写路径 E2E 在未配置隔离后端时跳过；动态契约比对的 1 项核心测试也因 CI 无常驻后端跳过。CI 注释已明确该行为。
- **影响**：单元/ASGI 测试可以全绿，但真实进程、鉴权、CSRF、事务提交、数据库约束及序列化组合仍可能失败。契约快照主要覆盖只读 GET 的结构，不证明筛选语义或写数据正确。
- **改进**：在 CI 建立一次性隔离栈：独立端口、独立 `*_test` 数据库和 Redis、测试专用身份端点；强制执行 `test_auth_flow.py`、`test_write_paths.py` 与动态契约比对。**不得指向本机 3000/5002 或生产库**，不得把“环境缺失跳过”继续视为等价通过。

## 5. P1：核心用例需补充或修正

### P1-01 核心 E2E 的“状态推进/状态不变”断言仅为状态非空

- **位置**：
  - `tests/e2e_api/test_write_paths.py:424-426`：注释要求订单仍为「已备货」，实际只有 `assert detail["status"]`。
  - `tests/e2e_api/test_write_paths.py:448-455,520-522`：用例名声称“advances order status”，实际同样只断言状态存在。
- **影响**：状态错成任意非空值也会通过，无法发现确认误改状态、出货未推进状态等核心回归。
- **改进**：确认前后精确断言 `before == "已备货"` 且确认后不变；出库 10/10 后精确断言 `status == "已出货"`；补部分出货应为「待出货」、重复确认不写第二次时间的断言。

### P1-02 订单筛选测试是 mock 自证，未验证筛选行为

- **位置**：`tests/test_order.py:78-138`（customer/status/factory/date 四个用例）
- **事实**：测试将 `count_result.scalar.return_value` 直接设为 3/5/2/7，再断言 `result["total"]` 等于该数；没有真实记录、SQL 条件或结果 ID 断言。
- **影响**：删除或写错筛选条件，测试仍可通过；日期边界、关键字和多 SKU 工厂筛选同样缺少真实行为证明。
- **改进**：使用真实 PostgreSQL 至少构造“命中/不命中/软删除/跨厂”四类订单，逐项断言返回 ID 和 total；补 customer+status+date 组合、start=end、非法日期、keyword 命中订单号/客户/SKU 名/条码，以及混合 SKU 工厂订单。

### P1-03 “已删除订单查不到”用例实际复用了“不存在订单”数据

- **位置**：`tests/test_order.py:162-181`
- **事实**：`test_get_order_by_id_deleted_order` 与前一用例一样传入 999，并让数据库返回 None，未构造 `is_deleted=True` 的现存订单。
- **影响**：该用例与不存在用例重复，不能发现软删除条件被移除后导致已删订单详情泄漏的问题。
- **改进**：先持久化一个真实订单，再设置 `is_deleted=True`；断言详情返回 None、列表不包含、按 ID 直接访问不泄露字段；同时保留未删除对照组。

### P1-04 湖北多单 MAX 与 completed/pending 混合状态测试不充分

- **位置**：`fastapi_app/tests/services/test_beile_orders.py:111-116,224-249`；`fastapi_app/tests/services/test_qa_beile_adversarial.py:179-248`
- **事实**：多供应商用例的两张 completed 单均为 `qty=10000/spare=500`，只能发现误求和，不能发现误取 MIN、首单或末单；completed 与 pending 分别存在于不同订单，缺少同一订单混合状态。
- **影响**：错误的聚合实现仍可能通过；pending 大单若污染 completed 结果，会造成错误开单数量。
- **改进**：同一来源配置 completed(8000,300)、completed(10000,500)、pending(99999,9999)，预期仅取 completed 集合且数量/备品分别为 10000/500；再让两个字段最大值来自不同采购单，验证字段独立聚合而非整行选择。

### P1-05 库存扣减缺少真实 PostgreSQL 并发竞争测试

- **位置**：`tests/test_stock_concurrency.py`（全部 AsyncMock）；`fastapi_app/tests/test_stock_optimistic_lock_unification.py`（FakeSession/mock）；真实 E2E 默认跳过
- **事实**：现有测试验证锁语句、重试编排和单事务结果，但未用独立连接并发执行同一产品的出库/退货/取消。
- **影响**：无法证明行锁/乐观锁在真实隔离级别下不会超卖、丢更新或产生库存—流水—订单状态不一致。
- **改进**：至少补三组真实 PG 并发：两请求抢同一库存、出库与退货取消竞争、批量 FIFO 与单条出库竞争；断言成功/409 的确定数量、最终库存、净流水、FIFO 绑定和订单状态，且失败方无副作用。

### P1-06 根集成夹具提交共享状态，隔离只覆盖产品库存的一部分

- **位置**：`tests/conftest.py:502-517,593-641,692-756`；`tests/test_stock_routes.py:98-135,288-294`
- **事实**：`async_db_session` 每用例提交；`test_order/test_stockin/test_stockout` 按固定单号复用但不完整重置状态。当前只专门恢复 `test_product.current_stock`。部分用例已被迫动态读取旧数量或额外自建产品规避执行顺序。
- **影响**：测试顺序变化可能改变订单余量、关联行和预期错误分支，形成聚焦跑与全量跑结果不同、重复/遗漏相互掩盖的风险。
- **改进**：优先采用每用例事务回滚或唯一数据工厂；无法回滚时明确重置所有可变字段及关联行。增加随机顺序/重复执行元测试，禁止用例依赖前序创建或删除的数据。

### P1-07 审批缺 HTTP 业务闭环与真实 approve/cancel 并发验证

- **位置**：`fastapi_app/tests/test_approval.py`；`tests/test_approval_delete_*.py`；接口静态扫描仅发现少量 `/approvals` 路径引用
- **事实**：现有状态机、mock 服务和删除审批测试较多，但未完整证明“普通用户提交→另一用户审批→订单实际变更”的 HTTP+权限+事务链；approve 与 cancel 的真实行锁竞争没有独立连接验证。
- **影响**：自审批/越权、重复执行、审批与取消相互覆盖可能在单元测试全绿时仍存在。
- **改进**：补正常编辑/删除审批闭环、自审批拒绝、非超管审批他人请求的权限矩阵、重复 approve/reject/cancel；用两个 PG 会话并发 approve/cancel，断言只允许一个终态且业务副作用至多一次。

### P1-08 版师管理后端 CRUD 与删除联动没有直接测试

- **位置**：`fastapi_app/api/v1/endpoints/pattern_maker.py:32-78`；`fastapi_app/services/pattern_maker_service.py:32-80`
- **事实**：本次测试引用扫描未发现 `pattern-maker` 或 `pattern_maker_service` 的直接测试。板房项目测试未覆盖版师自身新增/删除。
- **影响**：去空格重名、空名、权限、404，以及删除后项目 `pattern_maker_id` 置空和冗余 `pattern_maker_name` 清空均可能回归。
- **改进**：补列表排序、空名/100 与 101 字符、去空格重名、并发重名、无权限、删除不存在、删除有关联项目；最后必须重查项目两个字段均为空且历史项目未删除。

### P1-09 通知 API 的跨用户隔离与已读语义未直接验证

- **位置**：`fastapi_app/api/v1/endpoints/notification.py:39-96`；现有通知测试主要覆盖 WebSocket/广播
- **影响**：用户 A 对用户 B 通知标记已读、`read-all` 越界、unread 过滤和分页错误无法被现有广播测试发现。
- **改进**：真实 DB 建两个用户及已读/未读通知，验证未读数、only_unread、分页 1/100/101、单条重复已读幂等、跨用户单条返回 404 且不修改、read-all 只影响当前用户。

### P1-10 死信重试端点缺少成功、失败和并发防重测试

- **位置**：`fastapi_app/api/v1/endpoints/dead_letter.py:91-179`；现有测试主要覆盖巡检脚本
- **影响**：`enqueue_job` 成功后 `LREM` 的顺序若改变或异常处理失误，可能重复执行或丢死信；畸形参数、Redis 故障、重复点击均无直接 API 回归。
- **改进**：覆盖列表/统计、404、Redis 503、args/kwargs repr 解析、坏 JSON、非超管；重点验证 enqueue 失败时原记录保留、成功后才移除，以及两个并发 retry 至多一个入队。

### P1-11 外发服务测试丰富，但 21 条 API 路径缺直接 HTTP 验证

- **位置**：`fastapi_app/api/v1/endpoints/outsource.py`；`tests/test_outsource*.py`、`fastapi_app/tests/test_outsource*.py`
- **事实**：本次静态路径扫描未发现外发 API 的直接 HTTP 引用；现有覆盖主要在服务层。
- **影响**：请求模型、权限、事务提交、错误映射和响应 DTO 与服务层之间可能失联，尤其是批量 ship/receive 和 shipment 创建。
- **改进**：至少打通工序生成→分批发货→分批收货→发货单创建/收货的 API 流程；补超量、非法状态、无权限、批量部分失败回滚、重复提交与跨厂访问。

### P1-12 浏览器 E2E 只覆盖登录，不覆盖核心业务流程

- **位置**：`frontend-vite/tests/e2e/login-flow.e2e.mjs:188-251`
- **事实**：现有 5 项浏览器测试为正常登录、401、503、空字段、未登录深链；API 全部 mock。
- **影响**：真实导航、表单、浏览器存储、前端请求与后端写库的组合没有端到端证据。
- **改进**：在隔离全栈环境增加一条高价值链路：创建订单→缺 BOM 配置/续提→完成采购→出库→退货/取消；另补无权限入口与直接 API 拒绝一致性。保留现有 mock 浏览器测试作为前端异常分支套件，不将其称为全栈 E2E。

### P1-13 采购页 BOM 续提缺真实父组件事件串联测试

- **位置**：`frontend-vite/src/test/purchaseOrderNoColumn.test.ts`、`bomOrderResumePurchase.test.ts`、`purchaseBomModal.test.ts`、`productBomResume.test.ts`
- **事实**：按钮事件、composable 状态机、弹窗 ref 装载和产品页事件分别测试；没有采购页父组件把 `configureBom → openBomEditor → saved/closed → completeConfiguration` 串起来。
- **影响**：事件名、props、监听注册或异步加载接线错误时，各单测仍可能全绿，而用户点击后无法续提。
- **改进**：挂载实际采购页/面板，BomEditor 可用受控替身；触发入口后分别 emit saved/closed，验证保存仅续提一次、取消零生成、失败保持可重试、多 SKU 使用服务端下一项。

### P1-14 部位差异化备品测试对应的是未接线特性，不能计入现役业务覆盖

- **位置**：`fastapi_app/services/purchase_order_spare.py:17-22`；`fastapi_app/tests/services/test_po_spare_from_part_rates.py`
- **事实**：模块明确说明 `recompute_po_spare_from_item_rates` 当前只被测试引用，生产导入图不可达。
- **影响**：大量绿色测试容易让评审误以为“部位差异化损耗率”已在采购保存/完成链路生效。
- **改进**：测试和覆盖率报告中标记为“待接线特性”；若该能力属于本期业务目标，先接真实保存/完成路径并补端到端测试，否则保持独立实验套件，不以其替代现行订单级备品测试。

## 6. P2：一致性、维护性与长期风险

### P2-01 “数量不变则不调库存”没有断言副作用为零

- **位置**：`tests/test_stock.py:245-259`
- **问题**：用例只断言返回数量仍为 100，没有断言库存未变化、未调用库存写入或日志。
- **改进**：保存初始库存，断言 `get_product_for_update`/统一库存入口和 `log_inventory_change` 均未调用；若允许修改客户/备注，另验证这些字段仍按业务保存。

### P2-02 重复用例增加维护成本，且部分重复掩盖了真正缺失的变异场景

- **位置**：
  - `tests/test_state_machine.py:14-74` 与 `fastapi_app/tests/test_state_machine.py:14-40`
  - `fastapi_app/tests/services/test_beile_orders.py:224-330` 与 `test_qa_beile_adversarial.py:179-248,436-489`
- **问题**：审批状态转换、湖北 MAX/门控/L1 禁用多组重复；独立 QA 的历史价值已转为长期双份维护。
- **改进**：状态机保留一份核心矩阵；湖北测试合并共享夹具，把省下的用例预算用于 P1-04 的差异化数据和混合状态。保留必要的“独立对抗”命名，但不要重复同一实现同一数据。

### P2-03 恢复权限拒绝路径依赖环境跳过，尚未形成确定证据

- **位置**：`fastapi_app/tests/test_restore_real_roundtrip.py:197-234`
- **问题**：文件自身注明本机 DB_USER 有 CREATEDB 时恒跳过；Pg 工具不可用或无法建 scratch 库也会跳过。
- **影响**：无建库权限必须“先拒绝、绝不先删库”的安全分支可能长期未测。
- **改进**：CI 建立专用无 CREATEDB 角色，断言拒绝发生在 DROP 前且 scratch 原数据不变；将跳过原因纳入发布证据审查，不允许安全关键用例长期以环境原因豁免。

### P2-04 空/损坏自述信息判 success 是兼容性设计，但需重新确认风险接受

- **位置**：`fastapi_app/tests/test_backup_completeness.py:20-24,85-86`；`fastapi_app/services/backup/records.py:168-180`
- **事实**：`None`、`{}`、非 dict 均预期 `success`；实现说明这是旧产物兼容，不是本次发现的代码—测试不一致。
- **风险**：若当前业务目标是“完整性未知就不能视为完整”，该预期会与目标冲突；若仅评价“产物未自述问题”，则可接受，但必须在界面/指标上与 truly verified 区分。
- **改进**：由业务/运维明确旧包、缺 sidecar、坏 sidecar 三类的状态口径；建议新增/同步产物用 `unknown` 而非 `success`，保留旧包兼容映射及明确提示。

### P2-05 湖北 PRD 与当前实现/测试的验收口径已漂移

- **位置**：
  - `docs/beile-order-sync/01-产品需求文档.md:67-68,142-145,154,179`：仍描述备货行取采购单数量及独立备品列。
  - `fastapi_app/services/order/beile.py:296-314`：模糊备货匹配只给开单信号，数量置 None。
  - `frontend-vite/src/test/BeileOrderTab.confirm.test.ts:430`、`QaAdversarial.beileSync.test.ts:309-329`：明确独立备品列已删除，生产数量=订单+备品。
- **影响**：当前实现与测试基本相互一致，但需求文档仍会导致新旧验收用例冲突，后续维护者可能按旧 PRD 把已修正行为改回去。
- **改进**：在 PRD 增加“现行调整”并更新 AC：模糊匹配的数量为 `None/—`；独立备品列删除；页面、导出、打印共用生产数量公式。先统一业务基线，再判断旧用例去留。

## 7. 建议补充/修正的优先测试用例集

| 用例 ID | 对应问题 | 前置条件与关键步骤 | 必须断言的预期结果 | 优先级 | 方法 |
|---|---|---|---|---|---|
| TC-P0-001 | P0-01 | 默认执行 pytest 收集并检索守卫用例 | 备份守卫 15 项被收集且执行；删除守卫被改坏时至少一项变红 | P0 | 收集守卫+变异检查 |
| TC-P0-002 | P0-02 | 启动一次性隔离后端和 `*_test` DB，运行 15 项 API E2E + 动态契约 | 全部实际执行而非 skip；写后数据库与响应一致；环境身份不符立即失败 | P0 | 真实 E2E |
| TC-ORD-001 | P1-02/03 | 造正常/软删/跨厂/不同日期订单，组合调用列表和详情 | 返回 ID/total 精确；软删不可见；筛选条件变更结果随之变化 | P1 | 场景法+真实 DB |
| TC-BEILE-001 | P1-04 | 同一订单含两个不同 completed 单和一个更大 pending 单 | 只取 completed；qty/spare 独立取正确值；pending 不污染；可确认 | P1 | 决策表+边界值 |
| TC-STOCK-001 | P1-01/05 | 两个独立 PG 会话并发出库/退货；再读订单和库存 | 状态精确；无超卖；净库存=流水；失败方无记录；至多一个冲突重试成功 | P1 | 真实并发+状态转换 |
| TC-APPROVAL-001 | P1-07 | 普通用户提交，另一用户审批；并发 approve/cancel | 权限正确；只有一个终态；业务副作用至多一次；无半提交 | P1 | 状态转换+并发 |
| TC-PM-001 | P1-08 | 版师关联项目后删除；另测重名/权限/404 | 项目保留，maker_id/name 均空；重名拒绝；无权限不写 | P1 | 跨模块场景 |
| TC-NOTIFY-001 | P1-09 | 两用户各有已读/未读通知，交叉调用 read/read-all | 跨用户 404 且不修改；read-all 只改当前用户；重复已读幂等 | P1 | 权限矩阵 |
| TC-DLQ-001 | P1-10 | enqueue 成功/失败及两个并发 retry | 失败保留原死信；成功才删除；至多一个入队；权限和 404 正确 | P1 | 异常注入+并发 |
| TC-OUT-001 | P1-11 | API 生成工序，分批发/收，构造一批部分失败 | 数量累计与状态正确；超量拒绝；失败批按契约回滚或逐行报告，无隐性半状态 | P1 | API 场景+边界 |
| TC-BOM-001 | P1-12/13 | 采购页点击配置，emit saved/closed，后端真实幂等重放 | saved 仅一次续提；closed 零生成；全 SKU 才生成；重复回跳零新增 | P1 | 组件集成+全栈 E2E |
| TC-FIXTURE-001 | P1-06 | 随机顺序、重复执行根集成套件 | 聚焦/全量/乱序结果一致；无固定单号冲突和隐含前置数据 | P1 | 测试卫生验证 |
| TC-RESTORE-001 | P2-03 | CI 使用无 CREATEDB 角色执行恢复 | 在 DROP 前拒绝；原库数据不变；错误明确 | P2 | 权限异常注入 |

> 每条新增或修正测试都应做一次变异检查：故意改坏对应业务行为，证明测试变红后恢复。仅增加“会通过的测试”不算完成。

## 8. 分模块覆盖评价（定性，不伪造百分比）

| 模块 | 正常流程 | 异常/边界 | 模块交互 | 结论 |
|---|---|---|---|---|
| 客户订单 | 较多 | 数量边界较好；筛选/软删除无效用例 | mock 较多，真实查询链不足 | 部分可信 |
| 采购/湖北 | 主流程较强 | MAX 混合状态不足；幂等较强 | 后端续提较强，前端父组件/全栈不足 | 较强但有明确缺口 |
| 库存/出货/退货 | 真实服务集成较强 | 单事务边界较多 | 真实并发与订单状态 E2E 不足 | 核心补测优先级最高之一 |
| 生产/外发 | 服务层较多 | 服务异常较多 | HTTP 端点覆盖不足 | 补 API 集成 |
| 板房 | 项目/版本/打印较丰富 | 项目状态与乐观锁较好 | 版师 CRUD/删除联动缺失 | 补版师模块 |
| 审批 | 状态机和服务较多 | 非法转换较多 | 真实 HTTP 与并发不足 | 补闭环与竞争 |
| 通知/死信 | WebSocket/巡检较多 | 直接 API 异常不足 | 用户隔离、重试写路径缺失 | 明显不足 |
| 备份恢复 | 测试广、真实 roundtrip 已有 | 多类安全边界较好 | 守卫漏收集；权限拒绝分支跳过 | P0 修正后再评估 |
| 前端 | 组件/composable 丰富 | 大量对抗性用例 | 浏览器仅登录；BOM 父组件串联缺失 | 补业务 E2E |

## 9. 推荐处置顺序

1. **立即**：改名备份守卫文件并加关键用例收集守卫；将隔离 API E2E/动态契约纳入 CI 必跑。
2. **随后**：修正订单状态、软删除、筛选和湖北 MAX 数据；补库存真实并发，完成对应变异检查。
3. **下一批**：补审批、版师、通知、死信、外发 HTTP 闭环，以及采购页 BOM 父组件和浏览器主链路。
4. **收尾**：治理共享夹具和重复用例；区分未接线特性测试；更新湖北 PRD；明确备份 unknown 状态口径和无 CREATEDB CI 角色。

**最终判断**：当前测试体系“基础较强、证据不完整”。P0 未关闭前，不应把默认全绿作为备份安全和真实写路径的充分证明；P1 未补齐前，不建议以现有测试数量或历史覆盖率宣称核心功能、异常流程、边界和模块交互已完整覆盖。

## 10. 修复处置（2026-10-30）

### 10.1 已落地改动

| 问题 | 处置 | 当前验证 |
|---|---|---|
| P0-01 | `schedule_delete_guard_test.py` 更名为 `test_schedule_delete_guard.py`；新增 `test_critical_test_collection.py` 阻止测试文件逃逸收集规则 | 收集守卫与备份守卫 **17 passed** |
| P0-02 | CI 新增隔离 5502 后端、API E2E、动态契约；E2E 写路径补精确状态、部分出货、确认时间幂等和出库→退货→取消全链 | 已在本地真实隔离栈执行：API E2E **24 passed / 4 failed / 1 skipped**；契约比对检出真实漂移（见 10.2/10.3） |
| P1-01 | 写路径状态改为精确断言，禁止“状态非空即通过” | 代码完成 |
| P1-02 | 订单 customer/status/factory/date 筛选改为真实 PostgreSQL 数据驱动，并补 keyword、非法日期、组合边界 | 已随完整后端套件执行通过（见 10.2） |
| P1-03 | 软删除用例改为真实 `is_deleted=True` 订单，并保留可见对照组 | 已随完整后端套件执行通过（见 10.2） |
| P1-04 | 湖北新增不同数值 completed + 更大 pending 混合场景，独立验证 qty/spare 的 MAX | 湖北聚焦 **27 passed** |
| P1-05 | 新增真实 PG 竞争：单条对单条、单条对批量、重复取消退货；对账库存/流水/FIFO/订单状态 | 已随完整后端套件执行通过（见 10.2） |
| P1-06 | 根夹具改为每用例唯一产品/订单/备货/出库；重写隔离元测试，删除旧固定行复用 | 已随完整后端套件执行通过（见 10.2） |
| P1-07 | 新增审批 HTTP 编辑闭环、自审批拒绝、非超管拒绝、真实 approve/cancel 并发终态 | 已随完整后端套件执行通过（见 10.2） |
| P1-08 | 新增版师 CRUD、权限、重名/长度、删除后项目双字段清空、并发唯一约束 | 已随完整后端套件执行通过（见 10.2） |
| P1-09 | 新增通知跨用户 404、单条幂等、未读筛选、分页边界、read-all 用户隔离 | 已随完整后端套件执行通过（见 10.2） |
| P1-10 | 死信重试新增 Redis 任务级锁（409 防并发）；补成功/入队失败保留/404/503/权限/列表/删除/坏 JSON | 死信 API **5 passed** |
| P1-11 | 新增外发 HTTP 生成→批量原子回滚→分批收发→发货单收货→权限 | 已随完整后端套件执行通过（见 10.2） |
| P1-12 | 新增真实全栈浏览器冒烟与 CI 步骤；浏览器真实登录、创建订单并在业务页渲染 | 本机实跑：登录/建产品/建订单通过，业务页文本渲染超时（见 10.3 第 7 项）；CI 已补 admin 种子 |
| P1-13 | 新增真实 `PurchaseView` 父组件事件链测试，保存只续提一次、取消零生成 | 新增测试 2 项通过；前端全量 **237 文件 / 1801 项通过** |
| P1-14 | 部位差异化备品测试标记 `experimental`，并从当前覆盖率中排除，避免误算现役特性 | 标记/配置完成 |
| P2-01 | 数量不变测试补库存入口/流水零调用和其他文本字段持久化断言 | 代码完成 |
| P2-02 | 删除审批状态机重复类、湖北重复的 L1 与 spare_rate=0 单测 | 去重完成 |
| P2-03 | 新增确定性建库权预检测试，证明失败发生在任何 DROP/CREATE 之前 | 恢复预检测试 **2 passed** |
| P2-04 | 自述缺失由 `success` 改为 `unknown`；补文件元数据无完整性自述用例 | 备份完整性套件通过 |
| P2-05 | 湖北 PRD 增加现行调整，修正备货数量、独立备品列和生产数量口径 | 文档更新完成 |

### 10.2 补齐的后端/前端实测（本轮新增证据）

| 验证项 | 命令/条件 | 结果 |
|---|---|---|
| 完整后端套件 | `pytest tests fastapi_app/tests --ignore=tests/qa --ignore=tests/stress --ignore=tests/performance`，临时 PostgreSQL + 独立 Redis + 干净 `PYTHONPATH` | **5123 passed / 15 failed / 52 skipped**（修复前同条件为 4483 passed / 47 failed / **609 errors**） |
| 失败分项归因 | 15 项中：10 项已修复后复验通过（见 10.3）；4 项为本机 `.env` ACL 导致子进程读不到配置；1 项为跨事件循环 Redis 客户端残留 | 见 10.3 / 10.4 |
| 后端改动聚焦复验 | 备份守卫、死信 API、批量出库、乐观锁、湖北、维护模式、批量任务语义、nosec 门禁、git guard、E2E 清理守卫 | **45 passed**（另 131 passed 覆盖维护/批量/导入权限） |
| 真实隔离栈 API E2E | 5502 + `*_test` 库 + 迁移 + admin 铸造 token；`--confcutdir=tests/e2e_api` | 首轮 **24 passed / 4 failed**；修复后 **28 passed / 1 skipped** |
| 动态契约比对 | `CONTRACT_BASE_URL=http://127.0.0.1:5502` + `CONTRACT_TOKEN` | 首轮检出真实漂移（`logs[]` 新增字段）；基线合并重建后**有数据/空库均 22/22 一致、0 漂移** |
| 真实全栈浏览器 | 生产构建产物 + 同源 `/api` 反代 + 真实登录 `admin/admin123` | 登录、建产品、建订单成功；**业务页等待客户文本渲染 20s 超时** |
| 前端全量 | `cd frontend-vite && npm run test:unit` | **237 文件 / 1801 项通过**；ESLint、`vue-tsc` 通过 |

### 10.3 本轮新发现（含两处产品级疑点）

**已修复的测试侧缺陷**

1. **维护模式哨兵污染（放大 609 条错误）**
   `test_backup_m3::test_enter_sets_flag` 只 mock 了 Redis 客户端，`enter_maintenance()` 仍写真实 `logs/maintenance_mode.sentinel`；用例异常退出未执行 `exit_maintenance()`，哨兵在 2×TTL 内让后续**所有**写请求返回 503 MAINTENANCE。
   处置：两个测试目录的 `conftest.py` 增加会话级 autouse 夹具，把 `_MAINTENANCE_SENTINEL` 重定向到 pytest 临时目录；新增回归用例 `test_sentinel_is_isolated_from_repo_logs`。

2. **E2E 清理守卫把隔离库误判为生产库**
   `_cleanup` 用 `'/erp_system' in dsn and 'erp_system_test' not in dsn` 判定，导致 `erp_system_e2e_test` 这类合法 `*_test` 库被拒，6 条写路径用例在清理阶段假失败。
   处置：改为与 conftest 同口径的 `make_url(dsn).database.endswith('_test')`。

3. **备份“自述缺失”口径变更未同步任务结果**
   P2-04 把自述缺失从 `success` 改为 `unknown` 后，`manual_full_backup_task` 结果由 `ok` 变 `partial`，`test_backup_m1` 仍断言 `ok`。
   处置：拆为两条——有完整自述断言 `success/ok`，无自述断言 `unknown/partial`，锁住“没人报错≠已验证完整”。

4. **批量出库状态重算使既有单测暴露 Mock 伪失败**
   `test_stockout_batch_gate` 的 `mock_db.execute()` 返回协程，触发 `'coroutine' object has no attribute 'all'`。
   处置：与 `test_batch_stockout` 一致，在 `_run` 内打桩 `_recalc_shipment_order_statuses`（真实行为由 PG 集成测试覆盖）。

**三项遗留已闭环（2026-10-30 第二轮）**

5. **一键生成 `created_count=0` —— 不是缺陷，是测试断言过期（已修）**
   追踪结论：下单事务 commit 后由 `services/purchase/_auto_generate.py` 的 post-commit 回调**就地自动生成**采购单（独立会话，幂等键为空）。因此手动「一键生成」到达时采购单已存在，返回 `created_count=0 / idempotent=True` 是**正确语义**；请求内并无重复执行，单号消耗 2 次来自自动生成与手动调用两条路径。
   处置：用例改为断言真实不变量——**同一来源恰好 1 张采购单 + 订单变「已备货」**，并用 `source_order_ids @> [order_id]` 计数防重复；0 新增时必须 `idempotent=True`。

6. **出库可用量不认包装部记录 —— 造数用错表（已修）**
   `get_inventory_balance` 的口径是 `daily_production_record.department='packaging' − inventory_log 净出货`；`/production-summary/packaging/create` 写的是另一张 `packaging_record`（报表用），从不参与结余。
   处置：E2E 造数改为 `POST /api/v1/daily-production/records`（`department=packaging`，产品初始余额置 0 由生产入库补足），出库/退货用例全部转绿。

7. **全栈浏览器用例的页面断言未对齐（仍开放）**
   `/customer-order` 页在订单创建成功后 20s 内未见客户文本。登录、建产品、建订单三步均真实通过，仅最后一步断言口径待确认；CI 中该步骤标为 `continue-on-error` 并注明跟踪项，不删除（保留 run 记录）。

8. **动态契约基线依赖“有数据”的库 —— 用「合并录制 + 空容器容差」解决（已修）**
   - 录制新增 `--merge`：与已有基线取 shape **并集，只增不减**，空库录制不再删掉历史嵌套字段；
   - 比较器补两处容差漏洞：根级空数组记为 `<root>:array[0]` 时匹配 `[].field`；空对象 `object{}` 与 `object` 互认（空容器本就观测不到子结构）；
   - 基线按可复现环境重建：`plans_monthly_aggregated` 的 `total_shipped_qty` 已从实现移除（前端为可选字段）故重置，其余一律合并；`dashboard_nav_sections` 用 `scripts/seed_nav.py`（新库补齐导航的权威幂等来源）恢复 **+35** 个字段。
   - 结果：快照 shape 总量 **291 → 324（+33）**，仅 1 个字段按判定移除；有数据与空库两种环境均 **22/22 一致、0 漂移**。

### 10.4 仍需外部执行的验证与已知限制

- **本机 `.env` ACL**：非提权进程读不到 `D:\erp_system\.env`，导致 4 项子进程类用例（`test_openapi_snapshot_freshness` ×2、`test_test_db_exclusivity`、`test_secret_key_default_empty_raises`）稳定失败。属环境限制，不改生产文件权限。
- **跨事件循环 Redis 客户端**：`test_v1_health_check` 在长会话中偶发 `'NoneType' object has no attribute 'send'`（模块级客户端绑定已关闭的 loop），为既有脆弱点，未在本轮改动范围内重构。
- **CI 隔离步骤**：`Run isolated API E2E and live contract checks` 已恢复**全阻塞**（API E2E 28 passed / 1 skipped；契约 22/22），步骤内先跑 `seed_nav.py` 以复现导航结构。
- **全栈浏览器 CI 前置**：空库没有用户，已用项目自身 ORM + `hash_password` 幂等造 `admin`，否则真实登录必然 401；该步骤因第 7 条暂为 `continue-on-error`。
- **前端全量**必须在 `frontend-vite` 作为工作目录运行；在仓库根运行会因 `process.cwd()` 造成 11 个静态文件用例假红。
- **临时目录位置影响测试语义**：`--basetemp` 落在仓库内会同时打破 `test_non_git_directory_does_not_block`（非 git 目录判定）、批量任务的上传路径白名单、`test_nosec_budget_gate` 的运行时目录排除。正确做法是仓库外临时目录 + `TEST_DATABASE_URL` 显式指向 `*_test` 库。

---
intent: 在生产 API（http://192.168.0.95:3000）上以 SIMTEST- 前缀隔离数据完成 3 年跨度（2026-09→2029-09、约 1095 天日级、每日 10 次混合节奏）出入库全生命周期模拟，验证库存余量、出入库流水、账目汇总三账一致性
success_criteria: 37 个检查点三账全部一致 + 6 组边界探针全部被正确拒绝且状态零变化 + 预期成功操作 100% 成功（无意外失败）
risk_level: high
auto_approve: false
---

## Steps

- [ ] **Step 1: 创建公共模块 common.py**
action: 新建目录 scripts/stock_sim/，创建 common.py，包含：SimAPIClient 类（httpx.AsyncClient 封装，BASE_URL=http://192.168.0.95:3000/api/v1；login() 调 POST /auth/login 取 access_token 并存 Bearer 头；所有请求限速 80ms 间隔；429/5xx 指数退避重试上限 3 次）；JournalWriter 类（ops.jsonl 逐行追加 {seq, month, op_type, request, expected, actual}；checkpoints.json 与 summary.json 写入）；常量 PREFIX='SIMTEST-'、SEED=20260910、TIME_SPAN=('2026-09-01','2029-09-01')。凭据从环境变量 ERP_SIM_USER / ERP_SIM_PASSWORD 读取，缺失时报错退出。
verify: python -m py_compile scripts/stock_sim/common.py

- [ ] **Step 2: 实现 simulator.py 序列生成器（纯本地，不连网）**
action: 创建 scripts/stock_sim/simulator.py。plan_ops() 用 random.Random(SEED) 生成约 1095 天（2026-09-01 至 2029-09-01）日级操作计划并维护影子账本（shadow_orders、shadow_stockin、shadow_stockout、shadow_current_stock）：每日 10 次操作按业务节奏随机混合——优先订单创建（70% regular / 30% custom 且带国家字段，数量 100-500）、入库（数量 50-300）、出库（数量取影子可出货量的随机份额，每单出库前断言 qty ≤ 可出货量且 current_stock ≥ qty）；每日以 20% 概率穿插一次入库编辑（数量 ±20%）、10% 概率一次删除（限无出库关联的入库）；影子订单耗尽且当日仍有出库计划时生成补单。每个自然月末（共 36 个）标记检查点，最终日标记最终检查点（共 37 个）。每 6 个自然月（第 6/12/18/24/30/36 月末）追加 5 项边界探针（超卖 current_stock+1、超可出货量、数量 0、数量 -1、非法日期 '2029-13-45'）。--dry-run 模式：生成计划 → 逐条自检合法性（出库量 ≤ 影子可出货、每步后余额 ≥ 0、探针全部标记 expected_reject）→ 打印统计（总操作数、各类型计数、检查点数 37、非法操作数）。总操作数应为约 10950（3年×365×10），允许合理整数舍入；越界则调整每日节奏参数后重新生成。
loop: until dry-run 输出"非法操作: 0"且检查点数为 37
max_iterations: 3
verify: python scripts/stock_sim/simulator.py --dry-run

- [ ] **Step 3: 实现 simulator.py 执行引擎（live 模式）**
action: 在 simulator.py 增加 --live 模式：①登录；②POST /products/create 创建产品（名称 PREFIX+'PROD-'+时间戳）；③影子账本归零初始化；④按计划逐条执行——预期成功操作调对应写 API（订单 POST /orders/create、入库 POST /stock/in/create、出库 POST /stock/out/create、编辑 PUT /stock/in/edit/{id}、删除 DELETE /stock/in/delete/{id}），成功后同步影子账本并把实际响应写入 journal；边界探针调写 API 并断言响应为 4xx 或 success=false，断言通过才记 PASS；⑤每个自然月末及最终日（共 37 个检查点）生成检查点（GET /aux/product-available-stock、GET /stock/inventory?customer=、GET /stock/in/list、GET /stock/out/list 快照存入 checkpoints.json，并与影子账本当场比对，不一致立即中止并记录）；⑥模拟开始前 GET /stock/stats 存 baseline；⑦结束时写 summary.json（操作计数、检查点计数、产品ID、客户名）；⑧--resume 从 ops.jsonl 最后一行继续。live 执行前若 journal 目录已存在同名 run 则拒绝，需 --resume 或新目录。
verify:
  - type: shell
    command: python -m py_compile scripts/stock_sim/simulator.py
  - type: shell
    command: python scripts/stock_sim/simulator.py --help

- [ ] **Step 4: 实现 verifier.py 独立三账核对**
action: 创建 scripts/stock_sim/verifier.py，--journal <目录|latest> 参数（latest 自动定位 journal/ 下最新 run 目录）：①独立登录；②按 summary.json 中的客户名/产品ID分页拉取全量数据（per_page=500 翻页）：GET /stock/in/list?customer=、GET /stock/out/list?customer=、GET /stock/inventory?customer=、GET /aux/inventory-logs/{pid}、GET /aux/product-available-stock?product_id=、GET /stock/stats；③执行六项核对——A1 余额账：API current_stock == 影子 current_stock；A2 流水账：inventory-logs 全量 Σchange_quantity == current_stock；A3 视图账：inventory 响应 total_stock == 影子值（备货余量+订单剩余）；A4 流水明细：in/out 列表逐条与 journal 对照（数量、日期、客户、单号唯一性）；A5 汇总账：列表 Σquantity == journal 累计、stats 的 stockin_quantity 较 baseline 增量 == journal 入库总量；A6 不变量：37 检查点快照中余额恒 ≥ 0；④任一差异项等待 65 秒（local TTL 60s 缓存过期）复检一次，复检仍差异才判 FAIL；⑤输出 docs/reports/2026-09-10-stock-multiyear-simulation-report.json（机器可读，逐项判定）与 .md（人类可读：判定标准表、37 检查点结论、边界探针结论、差异明细）；⑥全部 PASS 退出码 0，否则 1。
verify:
  - type: shell
    command: python -m py_compile scripts/stock_sim/verifier.py
  - type: shell
    command: python scripts/stock_sim/verifier.py --help

- [ ] **Step 5: 实现 cleanup.py 幂等清理**
action: 创建 scripts/stock_sim/cleanup.py，--confirm 参数实际执行（缺省只列出待清理项），--journal <目录|latest>（latest 自动定位最新 run 目录）：①登录；②从指定 journal 的 summary.json 读客户名/产品ID（或 --customer/--product-id 直传）；③按顺序清理：先 GET /stock/out/list?customer= 全量并逐条 DELETE /stock/out/delete/{id}（出库有关联时入库删不掉，必须先删出库）→ 再全量 DELETE /stock/in/delete/{id} → GET /orders/list?customer= 全量 DELETE /orders/delete/{id} → DELETE /products/delete/{pid}；④每步记录删除数；⑤无待清理项时输出"无待清理项"；⑥重复执行结果幂等。
verify:
  - type: shell
    command: python -m py_compile scripts/stock_sim/cleanup.py
  - type: shell
    command: python scripts/stock_sim/cleanup.py --help

- [ ] **Step 6: 连网 dry-run 与端点探测**
action: 向用户获取 ERP_SIM_USER / ERP_SIM_PASSWORD 并设置环境变量（用户名/密码不写入任何文件）。运行 simulator.py --dry-run --probe：登录成功 + 逐一 GET 探测全部依赖读端点（/stock/stats、/stock/inventory、/stock/in/list、/stock/out/list、/aux/inventory-logs、/aux/product-available-stock、/aux/available-shipment）可达性（200 且非 403 权限拒绝），再执行 Step 2 的序列生成与合法性自检。任一端点 403 则停止并提示用户换账号或补权限。
loop: until 登录成功、全部端点可达、非法操作为 0
max_iterations: 3
verify: python scripts/stock_sim/simulator.py --dry-run --probe
gate: human

- [ ] **Step 7: 人工放行 gate②——全量备份后确认 live 执行**
action: 向用户确认生产服务健康状态。调用 POST /api/v1/backup/full 触发全量备份，轮询 GET /api/v1/backup/progress/{task_id} 直至状态完成（复用现有备份模块，进度键机制见项目约定）。备份完成后向用户展示 dry-run 统计与备份结果，明确请求人工放行 live 执行（3 年 / 约 1095 天 × 每日 10 次混合节奏，约 1.1 万次生产写操作，限速约 80ms/次合计纯等待约 15 分钟 + 网络往返，预计总耗时 30-60 分钟）。
verify:
  type: human-review
  check: 用户确认备份完成并明确放行 live 执行
gate: human

- [ ] **Step 8: live 执行 3 年日级模拟（约 1.1 万次）**
action: 运行 python scripts/stock_sim/simulator.py --live --seed 20260910。若中途失败或中断，修复原因后以 --resume 续跑（journal 从断点继续）。执行完成后确认 ops.jsonl 记录数 == 计划操作数、checkpoints.json 含 37 个检查点、summary.json 已生成。
loop: until simulator 退出码 0 且 journal 完整
max_iterations: 3
verify: python -c "import json,sys; s=json.load(open(sorted(__import__('glob').glob('scripts/stock_sim/journal/*/summary.json'))[-1])); assert s['planned_ops']==s['executed_ops'] and s['checkpoints']==37, s; print('journal OK')"

- [ ] **Step 9: 运行 verifier 生成测试报告**
action: 运行 python scripts/stock_sim/verifier.py --journal latest。若退出码非 0，检查报告差异明细：属脚本缺陷则修复后重跑（三账数据已在库，verifier 可反复重跑，不重放操作）；属系统真实缺陷则记录为发现项并向用户报告，由用户决定是否继续。
loop: until verifier 退出码 0 或用户判定差异为真实缺陷并决定继续
max_iterations: 3
verify: python scripts/stock_sim/verifier.py --journal latest

- [ ] **Step 10: 人工放行 gate③——审阅报告后确认清理**
action: 向用户呈现 Markdown 报告全文（37 检查点结论、6 组边界探针结论、三账核对明细、判定标准逐项结果），明确请求人工放行 cleanup 清理（删除全部 SIMTEST- 记录与测试产品）。
verify:
  type: human-review
  check: 用户审阅报告后明确放行清理
gate: human

- [ ] **Step 11: 执行清理并验证幂等与零残留**
action: ①运行 python scripts/stock_sim/cleanup.py --journal latest --confirm；②复跑一次同命令验证幂等（输出"无待清理项"）；③GET /stock/in/list?customer=<SIMTEST客户> 与 /stock/out/list?customer= 确认 total=0；④若产品删除失败（被关联限制），执行兜底：确认其 current_stock 为 0 并在报告中标注产品遗留。全部清理完成后向用户提交最终交付摘要（报告路径 + 清理结论）。
loop: until 清理完成、复跑幂等、列表零残留
max_iterations: 3
verify:
  - type: shell
    command: python scripts/stock_sim/cleanup.py --journal latest --confirm
  - type: shell
    command: python scripts/stock_sim/cleanup.py --journal latest --confirm

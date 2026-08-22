---
intent: 支持每道外发工序分批多次发货/收货，并在弹窗新增「台账」Tab 展示 总数量/发货记录/收货记录/未发货清单
success_criteria: 台账 Tab 展示 总数量/发货记录/收货记录/未发货清单；分批发货/收货后累计与剩余正确；后端与前端测试通过
risk_level: medium
auto_approve: true
branch: main
worktree: false
dirty_worktree: allow
---

# 外发工序分批发货/收货 + 台账 Tab — 工作流

设计文档：docs/designs/2026-08-20-outsource-process-ledger-design.md
当前迁移 head：add_outsource_ship_receive

## Steps

- [x] **Step 1: 后端分批流水改造（模型/迁移/服务/端点/schema/测试）**
action: 在 fastapi_app 与 migrations 下完成——(1) shared_models/outsource.py 新增 OrderOutsourceProcessFlow（id/process_id FK index/action/quantity/operator/create_time）。(2) 新增迁移文件 migrations/versions/add_outsource_process_flow.py：revision='add_outsource_process_flow'、down_revision='add_outsource_ship_receive'；upgrade 建 order_outsource_process_flow 表并回填存量（status 为 shipped 或 received 的行各补一条 action='ship' 流水，quantity=shipped_quantity、create_time=actual_start_time；status='received' 的行再补一条 action='receive' 流水，quantity=received_quantity、create_time=actual_end_time，operator 置 NULL）；downgrade 删表。(3) outsource_service.py：实现目标数量解析（order_item.quantity，无 order_item 用 order.quantity）、ship_order_process 分批（校验 remaining=target-shipped>0 且 0<本次≤remaining，追加 ship 流水、shipped_quantity 累加、首次发货才写 actual_start_time、status 按数量派生）、receive_order_process 分批（本次缺省=remaining，追加 receive 流水、received_quantity 累加、首次收货才写 actual_end_time、status 按数量派生）、list_flows(order_id) 查询流水并 join process_type、进度/看板汇总改为「收齐=完成」（received_quantity>=shipped_quantity）。(4) endpoints/outsource.py：新增 GET /orders/{order_id}/flows；ship/receive 端点 body 语义=本次数量。(5) schemas/outsource.py：新增流水响应模型（含 process_type/action/quantity/operator/create_time）。(6) tests/test_outsource.py 新增分批用例：多次发货累加、超量拒绝、未发货收货拒绝、多次收货累加、自定义收货、流水记录断言。
verify: python -m pytest tests/test_outsource.py -q
loop: until 全部通过
max_iterations: 3

- [x] **Step 2: 前端双 Tab + 台账（api/composable/Flow/Ledger/Dialog）**
action: 在 frontend-vite 下完成——(1) api/outsource.ts：新增 orderFlows(orderId) 请求 /outsource/orders/{id}/flows；shipProcess/receiveProcess 数量参数语义=本次数量。(2) composables/useOutsourceProcess.ts：新增流水加载（flows 响应式）、台账计算（总数量=SKU 合计、已发合计=Σshipped_quantity、已收合计=Σreceived_quantity、未发合计=总-已发；发货记录/收货记录从 flows 按 action 分组并按时间倒序；未发货清单=remaining>0 的工序）；本次数量草稿默认=剩余（ship 默认 target-shipped，receive 默认 shipped-received）；批量 handler 改为发/收「剩余全部」。(3) components/OutsourceProcessFlow.vue：发货/收货数量输入语义=本次数量（默认剩余），状态回显累计已发/已收。(4) 新增 components/OutsourceProcessLedger.vue：汇总条（总数量/已发货合计/已收货合计/未发货合计）+ 发货记录表（时间/工序/数量/操作人）+ 收货记录表（时间/工序/数量/操作人）+ 未发货清单（工序/目标/已发/剩余），复用 oso-* 样式与设计变量。(5) components/OutsourceProcessDialog.vue：弹窗体改为「进度/台账」双 Tab 分段切换（进度 Tab 保留现有表格与一键发/收；台账 Tab 渲染 Ledger）。
verify: cd frontend-vite && npx vue-tsc --noEmit && npx vitest run
loop: until 全部通过
max_iterations: 3

- [x] **Step 3: 构建前端 dist**
action: 在 frontend-vite 执行 npm run build 生成新 dist（nginx 以 frontend-vite/dist 为根）。
verify:
  - type: shell
    command: cd frontend-vite && npm run build
  - type: artifact
    path: frontend-vite/dist/index.html
    assert:
      kind: exists

- [x] **Step 4: 部署（生产迁移 + 服务重启）**
action: 在 migrations 目录执行 python -m alembic -c alembic.ini upgrade head 应用流水表迁移（先于服务重启）；随后 Restart-Service -Name erp-prod -Force；等待服务恢复后验证 /api/health 返回 200 且 OpenAPI 含 /api/v1/outsource/orders/{order_id}/flows 路径。
gate: human
verify:
  - type: shell
    command: (Invoke-WebRequest http://127.0.0.1:3000/api/health -UseBasicParsing).StatusCode -eq 200
  - type: shell
    command: (Invoke-WebRequest http://127.0.0.1:3000/api/openapi.json -UseBasicParsing).Content.Contains('/api/v1/outsource/orders/{order_id}/flows')

- [x] **Step 5: 浏览器验证（进度分批 + 台账展示）**
action: 打开 http://localhost:3000/outsource，进入任一有工序的订单弹窗：确认「进度/台账」双 Tab 存在；进度 Tab 可分批发货/收货（先发部分再补发）且累计正确；台账 Tab 展示 汇总条/发货记录/收货记录/未发货清单，时间与操作人正确。
verify:
  type: browser
  url: http://localhost:3000/outsource
  check: 双 Tab 存在；台账展示 总数量/发货记录/收货记录/未发货清单；分批后累计与剩余正确

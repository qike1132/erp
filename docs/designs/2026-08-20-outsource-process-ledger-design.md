---
design_type: feature
created_at: 2026-08-20
---

# 外发工序分批发货/收货 + 台账 Tab

## Intent Contract

```
intent: 支持每道外发工序分批多次发货/收货，并在弹窗新增「台账」Tab 展示 总数量/发货记录/收货记录/未发货清单
constraints: 不改订单/列表/看板既有路由；ship/receive 路径与字段名保持兼容；新增流水与累计在同一事务；进度与看板按「收齐=完成」语义
success_criteria: 台账 Tab 展示 总数量/发货记录/收货记录/未发货清单；分批发货/收货后累计与剩余正确；后端与前端测试通过
risk_level: medium
```

## Verification Contract

```
verify_steps:
  - run tests: cd fastapi_app && python -m pytest tests/test_outsource.py -q
  - run tests: cd frontend-vite && npm run type-check && npx vitest run
  - check: 弹窗出现「进度/台账」双 Tab；台账含 汇总条/发货记录/收货记录/未发货清单
  - confirm: 分批发货（先发部分再补发）与分批收货后，累计、剩余、流水时间与操作人正确
```

## Governance Contract

```
approval_gates: [本设计评审, 数据库迁移执行]
rollback: 迁移 down=删流水表; 代码 revert 至上一 commit
ownership: 外发模块负责人
```

## Scope

| In | Out |
| --- | --- |
| 新增外发工序流水表 + 回填迁移 | 修改订单创建自动带出工序逻辑 |
| ship/receive 支持分批（本次数量、剩余校验、流水与累计同事务） | 删除/新增工序按钮（已移除，不在本次范围） |
| 状态按数量派生，进度/看板按「收齐=完成」 | 支持工序删除（保持现状） |
| 弹窗新增「进度/台账」双 Tab 与台账内容 | 移动端/其它模块改造 |

## Decisions

| # | Decision | Choice | Alternatives | Rejected |
| --- | --- | --- | --- | --- |
| 1 | 流水存储 | 新增 `order_outsource_process_flow` 表记录每次发/收 | 冗余 JSON 列 | 可查询、可审计、易回填 |
| 2 | 分批语义 | shipped/received_quantity 变累计，每次操作追加流水并校验剩余 | 快照覆盖 | 保留历史，支持分批 |
| 3 | 状态派生 | pending=已发0；shipped=已发>0未收齐；received=已收齐 | 新增部分态枚举 | 避免枚举膨胀，数量已表达部分 |
| 4 | 完成口径 | 完成=收齐（received>=shipped） | status==received 即完成 | 分批后 status 语义失真 |
| 5 | 台账数据源 | 新增 `GET /orders/{id}/flows` 返回流水 | 复用 orderProcesses 内嵌 | 解耦、避免列表响应膨胀 |
| 6 | 弹窗呈现 | 「进度/台账」双 Tab 分段切换 | 单页追加/独立页 | 用户明确选双 Tab |
| 7 | 目标数量 | target=所属 SKU 数量，无 SKU 用订单数量，服务端校验 | 前端信任 | 剩余校验必须服务端为准 |

## Surface

**存储**（迁移）：
- 新增 `order_outsource_process_flow(id, process_id FK 索引, action, quantity, operator, create_time)`
- 回填：存量 shipped/received 工序按累计值与实际时间各补一条流水；操作人置空显示「—」

**后端 API**：
- `POST /processes/{id}/ship`（保持路径）：body `shipped_quantity` 语义=本次数量；校验 剩余>0 且 本次≤剩余；追加 ship 流水、累加、首次发货记 actual_start_time、状态按数量派生
- `POST /processes/{id}/receive`（保持路径）：body `received_quantity` 语义=本次数量（缺省=剩余）；校验 剩余>0 且 本次≤剩余；追加 receive 流水、累加、首次收货记 actual_end_time、状态按数量派生
- 新增 `GET /orders/{order_id}/flows`：返回流水（工序名/action/数量/操作人/时间）
- 服务：目标数量解析、剩余计算、状态派生、流水写入；进度/看板汇总按「收齐=完成」

**前端组件/Composable**：
- `OutsourceProcessDialog.vue`：弹窗体改为「进度/台账」双 Tab 分段切换
- `OutsourceProcessFlow.vue`：数量输入语义改为「本次数量」（默认=剩余）；累计回显
- 新增 `OutsourceProcessLedger.vue`：台账内容（汇总条 + 发货记录 + 收货记录 + 未发货清单）
- `useOutsourceProcess.ts`：批量 handler 改为发/收剩余；新增流水加载与台账计算
- `api/outsource.ts`：新增 `orderFlows`；`shipProcess/receiveProcess` 语义更新

## Risks & Open Questions

- 存量工序语义：回填后 status 由数量派生，历史「已发货/已收货」行与现有状态一致，无需改状态列
- 目标数量解析依赖 SKU 数量；无 SKU 的订单级工序用订单数量，需现场确认少数异常数据
- 看板/列表进度改为「收齐=完成」后，部分收货的行进度表现会变化，属预期语义修正

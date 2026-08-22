---
design_type: feature
created_at: 2026-08-20
---

# 外发工序「发货 → 确认收货」流程改造

## Intent Contract

```
intent: /outsource 外发工序进度逻辑由「开始/完成」改为「发货 → 确认收货」，并按用户名区分操作权限
constraints: 不破坏订单/备货列表、进度看板数据结构；不需录入收货数量的场景，收货数量默认等于发货数量
success_criteria: 除贝乐外用户可对每道工序发货并自定义数量；仅贝乐用户可确认收货；列表进度条/看板按新流程展示
risk_level: medium
```

## Verification Contract

```
verify_steps:
  - run tests: cd fastapi_app && python -m pytest tests/test_outsource.py -q  (实测需适配新流程后通过)
  - check: POST /api/v1/outsource/processes/{id}/ship 非贝乐返回成功、贝乐被拒；/receive 贝乐成功、非贝乐被拒
  - confirm: 前端 /outsource 弹窗内流程卡片显示「发货/确认收货」，数量随发货录入，状态展示待发货/已发货/已收货
```

## Governance Contract

```
approval_gates: [设计文档评审, 数据库迁移执行]
rollback: 迁移 down=删列; 代码 revert 至上一 commit (git checkout)
ownership: 外发模块负责人
```

## Scope

| In | Out |
| --- | --- |
| order_outsource_process 状态语义替换为 待发货/已发货/已收货 | 保留 开始/完成 旧流程 |
| 新增发货数量/收货数量字段与迁移 | 不引入按角色/权限码识别贝乐 |
| 新增 ship/receive 端点 + 服务 + 权限校验 | 收货不做数量录入（默认=发货数） |
| 前端流程卡片/弹窗/看板按新流程与权限展示 | 不改动订单创建自动带出工序逻辑 |

## Decisions

| # | Decision | Choice | Alternatives | Rejected |
| --- | --- | --- | --- | --- |
| 1 | 流程关系 | 替换现有「开始/完成」 | 叠加两套流程 | 语义混乱、冗余 |
| 2 | 贝乐识别 | 精确匹配 `user.username == '贝乐'` | 按角色/权限码 | 需求明确为用户名 |
| 3 | 发货数量粒度 | 每道工序各自录入 | 按 SKU 共享 | 用户已确认每道工序 |
| 4 | 收货数量 | 确认收货不录数量，赋值为发货数 | 录收货数量 | 用户已确认仅确认 |
| 5 | 状态值 | 新枚举 `pending`/`shipped`/`received`，迁移旧 `in_progress`→`shipped`、`completed`→`received` | 复用旧枚举 | 语义与旧值误导 |

## Surface

**数据库**（迁移文件新增）：
- `order_outsource_process.shipped_quantity INTEGER NULL`（发货数量）
- `order_outsource_process.received_quantity INTEGER NULL`（收货数量，确认收货时=发货数量）
- 数据迁移：`UPDATE ... SET status='shipped' WHERE status='in_progress'`；`SET status='received' WHERE status='completed'`

**后端 API**（router 挂载于 `/api/v1/outsource`）：
- `POST /processes/{id}/ship {shipped_quantity}`
  - 权限：`outsource_manage` 且 **拒绝** `username=='贝乐'`（其不能发货）
  - 状态：仅在 `pending` 时允许；置 `shipped`、写 shipped_quantity、actual_start_time
- `POST /processes/{id}/receive`
  - 权限：`outsource_manage` 且 **仅允许** `username=='贝乐'`
  - 状态：仅在 `shipped` 时允许；置 `received`、received_quantity=发货数、actual_end_time
- 移除 `start` / `complete` 端点与对应服务函数
- `OrderProcessResponse` 增加 `shipped_quantity` / `received_quantity`，status 枚举更新

**服务**（`outsource_service.py`）：
- `ship_order_process` / `receive_order_process` 新增；`_serialize_order_process` 增补字段
- `_summarize_process_progress` / `_matches_process_status` 按 `received` 视为完成、`!=pending` 视为已开始

**前端组件/Composable**：
- `api/outsource.ts`：类型新增两字段、status 联合类型；新增 `ship` / `receive` 方法
- `views/outsource/composables/useOutsourceProcess.ts`：`isBeile` 判定；`handleShip`（弹数量输入）/`handleReceive`；状态中文映射
- `views/outsource/components/OutsourceProcessFlow.vue`：按钮改为 发货/确认收货；展示发货/收货数量；删除按钮保留
- `components/OutsourceProcessDialog.vue`：传递新 handler

## Risks & Open Questions

- `outsource_manage` 权限是否已授予所有需发货的普通用户，需现场确认；否则「除贝乐外用户可发货」会受权限门槛限制
- 既有存量工序数据的语义迁移可能使历史记录显示为非预期状态，属一次性质变，需业务确认可接受
- 前端「发货」数量输入形式（inline 输入框 vs 弹窗）待实现时按现有 UI 风格取内联输入最简方案
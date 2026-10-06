# 迭代审核报告 Round-4 —— 2026-10-05（审核时间 17:58–21:30）

> Round-3 见 [iteration-review-2026-10-05-round3.md](iteration-review-2026-10-05-round3.md)，本文不重复其已闭环项的论证。
> 范围：HEAD 494005dc + 全部未提交/未跟踪改动（27 个修改 + 19 个未跟踪）。
> **移动靶声明**：并行会话（退货管理"按产品退货"重构）全程活跃编辑。快照 17:58 固化后，
> `stock_return_service.py` 21:14:20、`endpoints/stock_return.py` 21:14:53、`tests/test_stock.py`
> 21:16:38 仍在变更。本文所有结论以 **21:26 终验** 为准，中间态仅用于记录演进时间线。
> 方法：git 快照固化（.zcode/snap-r4/）→ 逐文件读 diff → 生产库只读取证 → pytest/alembic/vue-tsc 实测。

## 审核结论总览

| 项 | 结论 |
|---|---|
| Round-3 P0-1（status 列缺迁移） | ✅ **已闭环**：070 已应用，生产库 status 列在位 |
| **新 P0**：071 迁移未应用，stockout_id 漂移 | 🔴 生产库仍 NOT NULL，新代码按产品退货 INSERT NULL → **创建退货当前必 500** |
| Round-3 P1-1（openStandalone 权限错配） | ✅ 以重构方式关闭：出货单选择链路整体删除，无残留断线 |
| Round-3 P1-2（守卫测试期望表改名） | 🔴 **仍开放**：仍期望 `delete_stockreturn_core`，实测红 |
| 新 P1：psycopg2 测试依赖未钉版 | 🟡 `test_real_pg_transaction_scoped_proof` 红（ModuleNotFoundError） |
| 本会话交付（备份域三项） | ✅ 已上线验证（见文末） |
| 迁移链 068→069→070→071 | ✅ 单 head（109 revisions）；068 由并行会话 16:51 补齐 |
| 前端契约 | ✅ vue-tsc 0 错误（21:2x 终验） |

## 🔴 P0：071（stockout_id 可空）文件在盘、生产库未应用 —— 模型/库漂移第 2 幕

与 Round-3 P0-1 完全同构，且 pytest 依旧无法暴露（测试库 metadata create_all 有可空列，生产库迁移演进无）：

1. 新录入语义已改为**按产品退货**：`create_stockreturn_core(db, product_id, ...)` 不再关联出货，
   INSERT `stockout_id=NULL`（`stock_return_service.py`，21:14 版）；
2. ORM 模型 `shared_models/stock_return.py`：`stockout_id: Mapped[int | None] ... nullable=True`；
3. 迁移 071（21:11:02 落盘，`DROP NOT NULL`，幂等）**文件在盘但未应用**；
4. **生产库 21:24:43 实测**：`alembic_version = pg_standalone_070_stock_return_status`，
   `stock_return.stockout_id is_nullable = NO`。

影响：生产上任何"按产品退货"创建请求（`POST /stock-returns/create`，stockout_id 为 NULL）→
`null value in column "stockout_id" violates not-null constraint` → 500。
测试全绿的原因同 Round-3 P0-1：测试库建表方式对模型/迁移漂移天然免疫。

修复（归属：退货模块工作流）：`alembic upgrade head` 应用 071 即可（幂等、低风险）。
**在应用之前，退货创建在生产上是不可用功能。**

## Round-3 开放项核销

### P1-1 openStandalone 权限错配 → ✅ 以重构方式关闭

21:26 实测：`useStockReturn.ts` 已重构为纯产品制——`openStandalone` 只调
`catalog.ensureProducts()`（产品目录），不再拉出货单列表；`openFromStockout`/`stockoutOptions`
在 composable、`api/stockReturn.ts`、`StockOutRecords.vue`（行内退货入口）、后端
`stockout-options` 端点与 `get_returnable_stockout_candidates` **全链路同步删除，零残留**
（逐文件 grep 实证 + vue-tsc 0 错误）。原最小授权矛盾随需求变更（不再选出货单）自然消解。

### P1-2 守卫测试期望表 → 🔴 仍开放

21:26 实测：`test_stock_optimistic_lock_unification.py` 仍期望
`delete_stockreturn_core`（服务已改名 `cancel_stockreturn_core`），
`pytest fastapi_app/tests/test_stock_optimistic_lock_unification.py` 实测 1 failed
（参数 `[fastapi_app/services/stock_return_service.py]`）。
修复仍是一行：期望表键名 delete→cancel。归属退货模块工作流。

## 🟡 P1：psycopg2 未装、未钉版、未 skip —— 测试环境债

- `test_real_pg_transaction_scoped_proof`（`test_import_idempotency_constraints.py`）：
  `import psycopg2 → ModuleNotFoundError`，实测红（21:24 批次）；
- psycopg2 不在 venv、`requirements.txt`/`pyproject.toml` 均无钉版；生产运行时用 asyncpg，不需要它；
- 与已知问题同族（2026-10-05 评审"Python 环境未同步钉版 pillow/PyJWT"）。
  建议：测试内 `pytest.importorskip('psycopg2')`（真实 PG 证明类测试本就该环境可选），
  或钉版入 requirements-dev。

## 测试基线（终验 21:24–21:26）

| 批次 | 结果 |
|---|---|
| `tests/test_stock.py` | ✅ 全绿（6→5 处调用 21:16 随并行会话修完为 product_id 制） |
| `tests/test_stock_return_api.py` + `test_stock_return_flow.py` | ✅ 全绿（21:19 起转绿；测试库口径） |
| 守卫测试（P1-2） | 🔴 1 failed |
| `test_real_pg_transaction_scoped_proof`（psycopg2） | 🔴 1 failed |
| 定向合并批 | **52 passed / 2 failed**（上述两红） |
| alembic heads | ✅ 单 head（109 revisions） |
| vue-tsc | ✅ 0 错误 |

⚠️ 注意"测试库口径全绿 ≠ 生产可用"：P0（071 未应用）正是被这个盲区掩盖的活例。

## 本会话交付（非审核对象，随报告存档）

1. **备份调度 stale-running 补跑**（`schedule_service.py` + `test_backup_m2.py`）：
   running 超 2h 视为未执行放行补跑；已上线（worker 17:43:59 > 代码 16:42），定向 42 测试全绿；
2. 备份页状态中文/日期-only 三组件 + ScheduleConfig cron→中文时间标签（已 build，live hash 验证）；
3. 生产事故定位：16:00 定时备份被 16:05:04 全栈重启杀死（详见 memory backup-scheduler-restart-kill）。

## P2 流程风险（Round-3 P2-1 延续并加剧）

- 生产 = 工作树 + **双会话并发编辑**（本会话审核期间目标文件 5 次变更）。
  任何一方的 `git checkout/clean` 都会静默销毁另一会话的生产代码。退货模块稳定后按内聚分批提交；
- `scripts/restart_erp_prod.bat`（未跟踪）实测纯 ASCII ✅，无编码风险，但属运维脚本应入库或明确忽略；
- `scripts/diag/` 下诊断残留已顺手清理（`_status_snapshot.txt`、`_snap_round4.py`）。

## 建议行动（按优先级）

1. **立即**：应用迁移 071（P0，一条命令）；应用前请并行会话勿在生产点"按产品退货"创建；
2. 守卫测试期望表 delete→cancel（P1-2，一行）；
3. psycopg2 importorskip 或钉版（P1，测试卫生）；
4. 退货模块分批提交（P2，回滚能力）。

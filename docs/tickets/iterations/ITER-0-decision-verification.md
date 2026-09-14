# 决策落地前核查报告（ITER-1 / ITER-2）

| 字段 | 值 |
|---|---|
| 核查时间 | 2026-09-13 00:38 – 00:46 |
| 触发 | 用户拍板两项阻塞决策：ITER-2 = 改应用逻辑去重；ITER-1 = 新写分块格式 + 读取兼容旧格式 |
| 核查性质 | **只读**（未修改任何生产代码） |
| 结论 | **两项决策在实施中已被采纳并落地**，但 ITER-2 有一处确凿缺口：去重原语是死代码 |

---

## 一、必须先说明的一件事：工作区里有另一路并行改动

核查开始时 `git status` 显示了一批**本会话未创建**的文件，时间戳全部落在 **00:06 – 00:37**
（本会话最后一次写盘是 23:56 的 P0-02）：

| 时间 | 文件 |
|---|---|
| 00:06 | `services/backup/_stream.py`（14 行，转出 shim） |
| 00:31 | `core/backup_encryption.py`（594 行） |
| 00:31 | `core/atomic_write.py`（75 行） |
| 00:33 | `services/numbering_sequence.py`（124 行） |
| 00:37 | `services/batch_import_dedup.py`（219 行） |

同时被修改的还有 `services/numbering.py`、`services/backup/format_strategy.py`、
`services/backup/orchestration/core.py`、`services/backup/_constants.py`、
`api/v1/endpoints/backup/_deps.py`。

**这批改动不是本会话所为**，且 docstring 中直接引用了「ITER-2 决策 1」等本会话产出的术语。
在来源确认前，本会话**不修改上述任何文件**，以免覆盖冲突。

---

## 二、ITER-1（备份加密流式化）：已落地且完全符合决策

### 2.1 决策落地情况 ✅

用户决策 =「新写的用分块格式，读取时兼容旧格式」。实现与之一一对应：

| 决策要求 | 实现位置 | 状态 |
|---|---|---|
| 新写分块格式 | `core/backup_encryption.py::encrypt_stream`（L287） | ✅ |
| 读取兼容旧格式 | `decrypt_stream`（L373）自动识别；`detect_encryption_format`（L231） | ✅ |
| 块序号防重排 | `_chunk_aad(header_fixed, index)`（L251） | ✅ |
| manifest 标记格式 | `encrypt_stream` 内 `'encryption_mode': 'chunked-v1'`（L362） | ✅ |
| 可一键回退 | `chunked_encryption_enabled()`（L221）feature flag | ✅ |

格式判定三态：`'chunked-v1' | 'plaintext' | 'legacy'`，magic 为 `b'BFBKENC1'`（8 B），
分块默认 4 MiB、上限 64 MiB。

### 2.2 接入情况 ✅ 深度接入

`core/backup_encryption.py` 的调用点（7 处，均为主链路）：

- `api/v1/endpoints/backup/_deps.py:180`（`encrypt_backup_auto`）、`:201`（`decrypt_backup`）
- `services/backup/format_strategy.py:321`、`:344`
- `services/backup/adapters.py:239`
- `services/backup/incremental.py:114`、`:244`
- `services/backup/records.py:63`（`create_meta_file`）
- `services/backup/orchestrator.py:272`、`orchestration/recovery_test_service.py:340`

`core/atomic_write.py::atomic_output` 被 `backup_encryption.py:27` 使用 ——
顺带覆盖了方案 ITER-1 §2.3 要求的 P1-13（清理并发保护）。

### 2.3 验证结果

```
test_backup_encryption_stream.py  →  32 passed
test_backup_m3.py + test_backup_p0.py  →  38 passed（既有回归全绿）
```

其中 `TestFormatSwitch::test_both_generations_readable_after_switch` **正是本次决策的验收项**。

---

## 三、ITER-2（批量导入）：已完成一半，另一半是死代码

### 3.1 已接入 ✅ 批量取号（T1 / T2）

`services/numbering_sequence.py::allocate_sequence_range` 已由
`services/numbering.py:33` 导入使用；`numbering.py:81/121` 的 docstring 已同步说明
「业务事务回滚仅产生跳号」的既有语义。测试 `test_numbering_batch.py` → 35 passed。

### 3.2 缺口已补 ✅ 去重原语接入导入链路（2026-09-13 01:05）

原状核查时：

```
grep -rn "batch_import_dedup|dedupe_by_keys|composite_key|build_conflict_note"
     --include=*.py fastapi_app/ scripts/ utils/
     （排除 tests/ 与自身）
→ 零命中
```

**已完成的接入**（4 文件 +184 / −23）：

| 文件 | 改动 |
|---|---|
| `services/batch_import_core.py` | 新增 `DedupeSpec`；`_import_data_generic` 加可选 `dedupe` 参数；新增 `_product_dedupe_key`；产品导入接入去重；完成消息不再混入 `debug_messages` |
| `services/batch_import_service.py` | 删除 `if count_key == 'products'` 返回值特例；行级消息并入 `results.errors` |
| `tests/services/test_batch_import_service.py` | 4 处适配新契约；新增 `TestProductDedupeIntegration` 3 用例 |
| `tests/test_comprehensive_import_atomicity.py` | 契约测试由「单值」改为「行级消息必须回显」 |

**设计要点**：`existing_keys` 来自 `pre_load` 的 DB 查询，而 `dedupe` 作为参数传入时查询尚未发生，
故 `DedupeSpec` 提供 `existing_keys_key` 从 context 延迟取值，而非要求调用方预先查库。
`message_limit`（默认 50）防止几千行的文件刷出上千条消息。

**验证**：新增 3 用例覆盖「批内重复保留首次」「大小写/空白变体判重」「行数守恒（无静默丢行）」；
回归 199 passed / 0 failed；ruff 对比基线**零新增**。

**遗留**：`ON CONFLICT DO NOTHING` + `build_conflict_note` 核对尚未接 —— 当前仍是逐行写，
不是 `executemany`，并发冲突由既有 savepoint 兜底。切到批量写入时必须补上。

### 3.3 唯一键事实清单（接入时的依据）

**单列唯一**（导入目标表）：

| 模型 | 列 | 位置 |
|---|---|---|
| `Order` | `order_no` | `shared_models/order.py:73` |
| `CaseStockIn` | `stockin_no` | `shared_models/case_stock_in.py:26` |
| `CaseStockOut` | `stockout_no` | `shared_models/case_stock_out.py:25` |
| `StockIn` | `stockin_no` | `shared_models/stock_in.py:27` |
| `StockOut` | `stockout_no` | `shared_models/stock_out.py:26` |
| `StockReturn` | `return_no` | `shared_models/stock_return.py:27` |
| `PurchasePlan` | `plan_no` | `shared_models/purchase_plan.py:20` |
| `PurchasePlanDetail` | `shipment_no` | `shared_models/purchase_plan.py:113` |
| `PurchaseOrder` | `order_no` | `shared_models/purchase_order.py:34` |

**复合唯一**（需 `composite_key` 构造）：

| 约束名 | 列 |
|---|---|
| `uq_outsource_pt_product_process` | `(product_id, process_type)` |
| `uq_product_material_product_role` | `(product_id, role_id)` |
| `uq_cs_role_project_name` | `(project_id, role_name)` |
| `uq_csfv_role_version` | `(role_id, version_no)` |
| `idx_csp_role_part_version` | `(role_id, version_no, part_name)` |

`batch_import_dedup.py` 的 docstring 已正确指出需覆盖三类键：
`Order.order_no`、`CaseStockIn.stockin_no`、`CaseStockOut.stockout_no`。

---

## 四、结论与建议

| 项 | 状态 | 建议 |
|---|---|---|
| ITER-1 加密格式决策 | ✅ 已实现、已接入、已验证 | 可继续推进 T4/T5/T7–T10 |
| ITER-2 批量取号 | ✅ 已接入 | 可继续 T3/T4 |
| **ITER-2 去重接入** | ✅ 已接入产品导入 | 下一步推广到订单/备货/出库（其唯一键为系统生成，需先确认是否有批内重复场景） |
| 并行改动来源 | ✅ 用户已确认为本人操作 | 可正常推进 |

### 补齐去重接入的最小动作

1. ✅ `_import_data_generic` 在行处理前调用 `dedupe_by_keys(...)`
2. ✅ `DedupResult.error_messages()` 并入 errors 列表（保持「跳过行要回显」）
3. ⬜ 批量写入带 `ON CONFLICT DO NOTHING`，用 `build_conflict_note(expected, rowcount)` 核对
   —— **切到 `executemany` 时必须补**，当前仍是逐行写，并发冲突由既有 savepoint 兜底
4. ✅ 断言「无静默丢行」—— `test_no_row_is_silently_dropped` 校验
   `入库数 + 消息数 == 输入行数`

> 该模块自身已提供 `DedupResult.total_count` 与 `kept_rows` 两个属性，就是为这些断言准备的。

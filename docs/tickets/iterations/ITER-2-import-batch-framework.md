# ITER-2　批量导入框架批量化改造（逐行 N+1 → 批量）

| 字段 | 值 |
|---|---|
| 迭代目标 | 把导入/批量创建的数据库往返从 **O(n)** 降到 **O(1)**，导入 5,000 行从 40–50 s 降到数秒 |
| 优先级 | P1-2（与 ITER-1 并列最高杠杆） |
| 预估 | 1 个迭代（3–5 个工作日） |
| 涉及模块 | `services/batch_import_core.py`、`batch_import_service.py`、`services/numbering.py`、`services/case/commands.py`、`services/staging/stockout.py`、`services/stock_out_service.py` |
| 前置依赖 | 无 |
| 风险等级 | 中（行为语义与技术语义各有一处变更，必须显式决策） |

---

## 一、问题本质：低效模式被**固化在框架层**

这不是"某个导入接口慢"，而是**框架把逐行模式变成了所有导入的默认行为**：

```
services/batch_import_core.py:75  _import_data_generic()
        ├── for idx, row_data in enumerate(data_list):
        │       async with db.begin_nested():            # 每行一个 SAVEPOINT
        │           await row_handler(...)               # 内部：1 次取号 + 1 次 flush + 1 次 FOR UPDATE
        └── await db.flush()
```

调用方继承开销，且**无法在调用层修复**：

| 调用方 | 位置 | 逐行开销 |
|---|---|---|
| 订单导入 | `batch_import_service.py:246` | 取号(2) + flush(1) + `get_product_for_update`(1) + savepoint(2) ≈ **5–6 次往返/行** |
| 通用导入（入库/出库/…） | `batch_import_core.py:75` | 同上 |
| 皮套出入库批量创建 | `case/commands.py:427,467` | 逐行取号（含 `asyncio.Lock` 串行化） |
| 出货确认 | `staging/stockout.py:131` | 逐行行锁 + 逐明细取号 + 逐订单重算状态 |
| FIFO 出库 | `stock_out_service.py:35` | 每命中一个订单取一次号 |

### 量化后果

以 5,000 行导入、内网单次往返 1.5–2 ms 计：

```
5,000 行 × 5 次往返 = 25,000 次往返 ≈ 40–50 秒
```

额外代价（往往比耗时更严重）：
- **长事务持锁**：整个导入期间持有行锁，阻塞其它写订单请求
- **导入失败的代价**：一旦失败要全部重来
- **用户体感**：导入按钮被反复点击 → 雪崩

---

## 二、目标设计

### 2.1 四阶段批量化（往返 25,000 → ~5）

```
阶段 1  内存校验（0 次 DB）
        用预载的 product_map / customer_map 在内存完成全部字段校验与归一
        产物：valid_rows: list[dict]、invalid_rows: list[错误信息]
        ← 现有 _pre_load_product_map() 已具备，直接复用

阶段 2  批量取号（1 次 DB）
        allocate_sequence_range(prefix, date_str, count=len(valid_rows))
        一次性预留连续号段，内存内分配

阶段 3  批量行锁（1 次 DB）
        get_products_for_update(db, product_ids)    ← IN (...) + FOR UPDATE，按 id 排序防死锁

阶段 4  批量写入（1–2 次 DB）
        await db.execute(insert(Order), rows)       ← executemany
```

### 2.2 编号批量分配（新增，`services/numbering.py`）

当前只有单号分配：

```python
# numbering.py:96 — 每次只取一个序号
current_seq = await allocate_sequence(prefix, date_str, seed=db_max)
```

新增批量版本（沿用同一把 advisory lock / 计数表，保持跨进程安全）：

```python
async def generate_number_batch(
    prefix: str, model, date_field: str, number_field: str,
    db: AsyncSession, count: int,
) -> list[str]:
    """一次预留 count 个连号，返回编号列表。

    与单号版本共用 numbering_counter 计数表与 advisory lock，
    多 worker 下仍无重号。业务事务回滚只会产生跳号（既有语义，不变）。
    """
    if count <= 0:
        return []
    date_str = datetime.now(UTC).strftime('%Y%m%d')
    async with _async_number_generator._lock:
        db_max = await read_daily_max(db, model, date_field, number_field)
        start = await allocate_sequence_range(prefix, date_str, count=count, seed=db_max)
        return ['-'.join((prefix, date_str, str(start + i).zfill(4))) for i in range(count)]
```

> ⚠️ `allocate_sequence_range` 必须**原子地 +count**（`UPDATE ... SET seq = seq + :count RETURNING seq`），
> 不能循环调用单号版本——否则只是把 N 次往返搬到了 numbering 内部。

### 2.3 利用既有的依赖注入点（关键：不改调用方即可切换）

`batch_import_core.py:40-58` 已有 `ImportDeps` 数据类，**这正是切换的杠杆**：

```python
@dataclass
class ImportDeps:
    generate_order_number: Callable = generate_order_number
    generate_stockin_number: Callable = generate_stockin_number
    ...
```

新增字段（带默认实现，完全向后兼容）：

```python
    generate_number_batch: Callable = generate_number_batch       # 批量取号
    get_products_for_update: Callable = get_products_for_update   # 批量行锁
```

**好处**：调用方无需改动；测试可注入假实现；单号路径与批量路径可**按模块灰度切换**。

### 2.4 新增批量化框架（与原框架并存）

```python
async def _import_rows_batched(
    db: AsyncSession,
    data_list: list,
    row_mapper,                      # 同步纯函数：(row, idx, ctx) -> dict | 抛 ValueError
    *, model, deps: ImportDeps, label: str = '导入',
) -> tuple[int, list[str]]:
    """批量导入：内存校验 → 批量取号 → 批量行锁 → executemany

    返回 (成功数, 错误消息列表)。错误行不落库，语义与逐行 savepoint 版一致。
    """
    ctx = await _pre_load_product_map(db)               # 复用既有预载
    valid, errors = [], []
    for idx, row in enumerate(data_list, start=2):
        try:
            valid.append(row_mapper(row, idx, ctx))     # 纯内存，无 IO
        except ValueError as e:
            errors.append(f'行{idx}: {e}')

    if not valid:
        return 0, errors

    for lookup in (deps.get_products_for_update,):      # 阶段 3：批量行锁
        await lookup(db, [r['product_id'] for r in valid])

    rows = await deps.import_rows(db, model, valid)     # 阶段 4：executemany
    logger.info('%s完成: 共导入 %d 条（跳过 %d 条）', label, len(rows), len(errors))
    return len(rows), errors
```

框架层不暴露 `use_savepoint` —— **批量化后不再需要逐行 savepoint**，
因为"部分成功"由阶段 1 的内存校验保证（无效行根本不进批量写入）。

---

## 三、两处必须显式决策的语义变更

### 决策 1：部分成功语义（**必须由业务方拍板**）

| | 当前（逐行 savepoint） | 批量版 |
|---|---|---|
| 1 行有错 | 该行回滚，**其余行照常入库** | 阶段 1 剔除该行，其余行入库 |
| 10 行有错 | 10 行跳过，其余入库 | 同上 |

**结论：语义可以保持一致**，只要把"校验"从 DB savepoint 前移到内存。
但有一个**边界差异**需要确认：当前是"尝试写库失败才跳过"（含**唯一约束冲突**等 DB 侧错误），
批量版是"内存校验通过即入库"。若存在"内存看不出、只有 DB 唯一约束才发现"的重复行，
批量 `executemany` 会**整批失败**（而非跳过单行）。

**缓解方案（推荐）**：
- 显式 `ON CONFLICT DO NOTHING` + 写入后按 `rowcount` 核对，把冲突行列回 errors
- 或在阶段 1 内**按唯一键去重**（用 `set` 检测批内重复），这是纯内存操作、零成本

**✅ 决策已拍板（2026-09-13 00:38，用户）：改应用逻辑去重，不依赖 DB 唯一约束兜底。**

即在阶段 1 用内存去重（批内 + 与库中已有数据），批量写入仍显式带
`ON CONFLICT DO NOTHING` 并按 `rowcount` 核对。

**落地状态（见 `ITER-0-decision-verification.md`）**：

| 产出 | 状态 |
|---|---|
| `services/batch_import_dedup.py`（219 行 + 33 测试全绿） | ✅ 已实现 |
| `dedupe_by_keys` 接入导入链路 | ✅ **已接入（2026-09-13）** |
| `services/numbering_sequence.py` 批量取号 | ✅ 已接入 `numbering.py:33` |

**接入方式**：`_import_data_generic` 新增可选 `dedupe: DedupeSpec | None`（不传则行为完全不变），
在行处理**之前**做内存去重；`DedupeSpec.existing_keys_key` 用于从 `pre_load` 的 context 中
延迟取出库中已有键（pre_load 查库发生在框架内部，作参数传入时那些键还不存在）。
首个落地 = 产品导入（`_product_dedupe_key`，名称去空白 + casefold）。

**一处附带的契约变更**：`import_products_from_data` 由 `-> int` 改为 `-> tuple[int, list[str]]`，
与另三种 Sheet 导入统一；`_process_comprehensive_sheet` 里针对产品的
`if count_key == 'products'` 特例分支随之删除。同时 `debug_messages` 不再混入
「X完成: 共导入 N 条」—— 该消息只进日志，因为它会被并进 `results.errors` 展示给用户。

### 决策 2：跳号语义（已被接受，需知悉）

批量取号后若事务回滚，会**一次跳掉整段号**（而非逐个跳）。
`numbering.py:78` 的 docstring 已明确"业务事务回滚仅产生跳号"，
故这是**既有语义的放大**，可接受。但需在验收中确认**无重号**（重号才是致命的）。

---

## 四、任务拆解

| # | 任务 | 产出 | 预估 | 依赖 |
|---|---|---|---|---|
| T1 | `allocate_sequence_range()`（原子 +count，`RETURNING`） | numbering 内部函数 + 并发单测 | 4 h | — |
| T2 | `generate_number_batch()` + 并发唯一性测试（多协程并发取号不重号） | 公开 API | 3 h | T1 |
| T3 | `get_products_for_update(db, ids)`（`IN` + 排序防死锁） | 查询函数 | 3 h | — |
| T4 | `ImportDeps` 扩展 + 默认实现注册 | 依赖注入点 | 2 h | T2,T3 |
| T5 | `_import_rows_batched()` 框架（含批内唯一键去重） | 新框架 + 单测 | 1 d | T4 |
| T6 | **基准测试脚本**（1k/5k/10k 行，记录往返数、耗时、RSS） | 基线数据 | 0.5 d | — |
| T7 | 订单导入切到批量框架（`batch_import_service.py`） | 首个落地 | 0.5 d | T5,T6 |
| T8 | 通用导入切换（`batch_import_core.py` 路径） | 覆盖入库/出库 | 0.5 d | T7 |
| T9 | 皮套批量创建 / 出货确认 / FIFO 出库 取号批量化 | 关闭 C2/C3/C4 | 1 d | T2 |
| T10 | E2E 回归 + 基准复测 + 长事务时长对比 | 报告 | 0.5 d | T8,T9 |

---

## 五、验收标准

### 5.1 性能（核心指标，必须量化对比）

```bash
# T6 产出的基准脚本，分别在改造前后各跑一次
python docs/tickets/iterations/bench_import.py --rows 5000 --repeat 3
```

| 指标 | 改造前（基线） | 目标 |
|---|---|---|
| 5,000 行耗时 | ≈ 40–50 s | **< 5 s**（≥ 8× 提升） |
| 数据库往返次数 | ≈ 25,000 | **< 10** |
| 事务持锁时长 | 全程（40–50 s） | **< 2 s** |
| 进程 RSS 增量 | 基准 | 不得劣化 |

> 往返次数用 SQLAlchemy `before_cursor_execute` 事件计数，作为**硬断言**（比耗时更稳定、更适合 CI）。

### 5.2 正确性（比性能更重要）

| 断言 | 方法 |
|---|---|
| 行数一致 | 批量导入 N 行有效数据 → 表内恰好新增 N 行 |
| **编号无重号** | 5,000 行导入后 `SELECT order_no, count(*) ... HAVING count(*)>1` → 空 |
| 编号连续 | 同批次内编号连续（跳号允许，跳段不连续不允许） |
| 错误行不进库 | 混入 10 行脏数据 → 恰好 (N−10) 行入库，errors 报告 10 条 |
| 并发安全 | 4 个协程各导入 1,000 行 → 合计 4,000 行、无重号 |
| 边界 | 0 行 / 全部无效 / 单行 三种输入均不抛异常 |

### 5.3 回归

```bash
python -m pytest fastapi_app/tests/test_staging.py -q
python -m pytest fastapi_app/tests/test_purchase_center.py -q
```
并按项目既有做法做一次**真实库 + 事务回滚**的只读式 e2e（建业务对象 → 调真实服务 → 断言 → rollback → 复查残留为 0）。

---

## 六、风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| **唯一约束冲突导致整批失败**（决策 1） | 🔴 高 | 开工前拍板；批内 `set` 去重 + `ON CONFLICT DO NOTHING` + `rowcount` 核对 |
| **重号**（批量取号的原子性） | 🔴 高 | T1 的 `RETURNING` 原子递增 + 4 协程并发唯一性单测（进 CI） |
| 批量 `FOR UPDATE` 死锁 | 🟡 中 | T3 按 `id` **排序后**加锁，统一加锁顺序 |
| `executemany` 与 ORM 事件/默认值不一致（如 `created_at` 未触发） | 🟡 中 | 显式传全部非空列；或用 `bulk_insert_mappings` 走 ORM 语义；单测断言时间戳/默认值已填 |
| 长事务改短事务后，"导入中途失败"的可见状态变化 | 🟡 中 | 保持"报告失败 + 已入库行保留"语义，并在响应中明确返回成功/失败行数 |
| 改造面覆盖 5 个模块，容易漏改一半 | 🟡 中 | T7→T8→T9 逐个模块独立 commit，每个都跑基准与回归 |

---

## 七、交付物

- `numbering.py`：`allocate_sequence_range` / `generate_number_batch`
- `batch_import_core.py`：`ImportDeps` 扩展 + `_import_rows_batched`
- `batch_import_service.py` / `case/commands.py` / `staging/stockout.py` / `stock_out_service.py`：切换
- `docs/tickets/iterations/bench_import.py`：基准脚本（可复跑，作为 CI 性能门禁）
- E2E 回归报告（含改造前后往返次数对比）

## 八、为什么值得排一个完整迭代

- **一个改动覆盖 5 处 N+1**：因为它们的根因都在框架层与取号层，改一次全局受益
- **指标可硬断言**：往返次数是稳定的 CI 门禁指标，不像耗时那样受机器负载干扰
- **持锁时长降低才是最大收益**：40–50 s → <2 s，直接消除"导入时全站写操作被阻塞"的隐患
- **与 ITER-1 无耦合**，可并行推进，两条线互不阻塞

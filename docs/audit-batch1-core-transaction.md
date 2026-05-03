# ERP 系统代码审核报告 - 第一批：核心交易链

**审核标准**: shenhecode.mdr 双策略审核（分类清单扫描 + 执行路径追踪）
**审核日期**: 2026-05-03
**审核范围**: 客户订单、出库管理、采购中心、出货计划（增量）
**代码版本**: new-main @ 561b045

---

## 审核范围统计

| 模块 | 文件数 | 代码行数 | 关键文件 |
|------|--------|---------|---------|
| 客户订单 | 14 | ~4,200 | order_service.py(671), staging_service.py(960), CustomerOrderView.vue(1828) |
| 出库管理 | 17 | ~3,800 | stock_service.py(482), stock_crud_service.py(642), stock_concurrency.py(121) |
| 采购中心 | 17 | ~5,100 | purchase_center_service.py(1098), purchase_product_service.py, 6路由文件 |
| 出货计划 | 6 | ~1,200 | purchase_plan_service.py(807), plan_utils.py |
| **合计** | **54** | **~14,300** | |

---

## 阶段 1：分类清单扫描（广度优先）

### 1. 算法与数据结构

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| ALG-01 | **P0** | `order_service.py` | 47, 92 | `not Order.is_deleted` 在 SQLAlchemy where 子句中使用 Python `not` 运算符，不会翻译为 SQL `NOT`。Python 中 `not InstrumentedAttribute` 求值为 `True`（因为属性对象是 truthy 的非零值，`not` 后变为 `False`），此过滤器实际被忽略，**所有已删除的订单也会被返回**。应使用 `~Order.is_deleted` 或 `Order.is_deleted == False` |
| ALG-02 | P1 | `order_service.py` | 54, 122 | `deduct_quantity` 计算逻辑完全重复：`sum(so.quantity for so in o.order_stockouts if so.stockin_id is not None)` 出现在 `get_order_by_id` 和 `get_orders` 两个函数中，违反 DRY 原则。更严重的是，此逻辑与库存查询中的出库量计算口径不一致 |
| ALG-03 | P1 | `stock_crud_service.py` | 500-641 | 同步版 `get_inventory` 使用 selectinload 加载全部产品+订单+入库+出库，再在 Python 中聚合。时间复杂度 O(P*C*S)，产品数增长时内存和计算量急剧膨胀。异步版使用 SQL GROUP BY 优化（stock_service.py:319-369），但两个版本的结果口径可能因实现差异而不一致 |
| ALG-04 | P2 | `batch_service.py` | 27-78 | `AsyncNumberGenerator` 使用 `asyncio.Lock` + 内存计数器生成编号。多进程部署时每个进程有独立的计数器实例，虽然从 DB 查询最大编号作为起点，但在并发高峰时仍可能出现编号冲突（两进程同时读到相同 max，各自+1 后相同） |
| ALG-05 | P2 | `stock_crud_service.py` | 27-98 | `SyncNumberGenerator` 与 `AsyncNumberGenerator` 是两套独立的编号生成器实现，分别用于同步和异步路径。逻辑上应保持一致但分别维护，存在漂移风险 |
| ALG-06 | P2 | `purchase_plan_service.py` | 43-59 | `_generate_plan_no` 未使用 `SELECT ... FOR UPDATE` 行锁，与注释描述不符。并发创建计划时可能生成重复编号 |

### 2. 代码结构与模块化

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| STR-01 | P1 | `stock_service.py` vs `stock_crud_service.py` | 全文件 | 入库/出库 CRUD 存在双实现：异步版（stock_service.py）和同步版（stock_crud_service.py），业务逻辑存在微妙差异。例如异步版使用 raw SQL 查库存，同步版使用 ORM + Python 聚合。修复一个版本的 bug 时极易遗漏另一个版本 |
| STR-02 | P1 | `order_service.py` | 37-74, 120-142 | `get_order_by_id` 和 `get_orders` 中构建订单字典的逻辑几乎完全相同（14个字段），任何字段增删改都需要同步修改两处 |
| STR-03 | P1 | `staging_service.py` | 全文件 | 960行单文件处理3种暂存类型（订单/备货/出货），每种都有 CRUD + Excel导入 + 确认逻辑。三种类型的代码结构高度相似（CRUD约60%重复），应抽象为通用暂存服务 |
| STR-04 | P2 | `purchase_center_service.py` | 全文件 | 虽已拆分4个子模块，仍剩1098行。客户管理、采购订单、供应商汇总等域仍在此文件中，继续维持 God File 反模式 |
| STR-05 | P2 | `order_service.py` | 205-222, 292-309, 417-444 | 事件发布（缓存失效+WebSocket通知）的 try/except 模式重复出现5次以上，应抽取为装饰器或上下文管理器 |
| STR-06 | P2 | `staging_service.py` | 238-371, 512-628, 818-959 | 3个Excel导入函数结构完全相同：清空暂存 -> 写临时文件 -> 读取Sheet -> 解析数据 -> 匹配产品 -> 写入DB。仅Sheet名和字段映射不同，应参数化 |

### 3. 命名与语义

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| NAM-01 | P2 | `stock_service.py` | 29, 41, 54, 65, 94, 116 | 下划线前缀函数（`_create_stockin_record`等）与公开函数（`create_stockin`等）命名区分不清。下划线版本执行核心业务逻辑+flush，公开版本添加commit/cache/events。建议改为 `create_stockin_core` 或类似命名 |
| NAM-02 | P2 | `order_service.py` | 570 | `_BatchItemError` 定义为内部异常类，命名暗示与批量操作绑定，但实际用于任何需要 savepoint 回滚的场景。且 `pass` 在 except 块中无注释说明为何忽略 |
| NAM-03 | P3 | `stock_crud_service.py` | 118-222 | `calculate_available_shipment_quantity` 函数签名中 `order_type: str = None`，类型标注应为 `str | None = None` |
| NAM-04 | P3 | `purchase_center_service.py` | 150-162 | `_generate_order_no` 采购订单编号生成与 `batch_service.py` 中的 `generate_order_number` 客户订单编号生成使用不同逻辑，但函数名含义混淆 |

### 4. 资源管理

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| RES-01 | **P0** | `stock_concurrency.py` | 115 | `update_stock_with_optimistic_lock` 在乐观锁冲突时调用 `await db.rollback()`，这会回滚**整个事务**而非仅当前 savepoint。如果在一个批量操作中第3次重试失败，前2次成功的库存更新也会被回滚。应使用 `await db.begin_nested()` 创建 savepoint 后在冲突时回滚 savepoint |
| RES-02 | P1 | `staging_service.py` | 258-263 | `tempfile.mkstemp` 返回文件描述符后立即 `os.close(temp_fd)`，然后用 `open(temp_path, 'wb')` 重新打开。在 close 和 open 之间存在 TOCTOU 竞态：其他进程可能替换该文件。应直接使用 `os.write(temp_fd, file_content)` 或 `tempfile.NamedTemporaryFile(delete=False)` |
| RES-03 | P1 | `order_service.py` | 439 | `asyncio.ensure_future(publish_stock_event(...))` 创建 fire-and-forget 任务，无异常处理和生命周期管理。如果事件循环正在关闭或任务抛出异常，会导致未捕获的异常警告。应使用 `asyncio.create_task` 并添加 done callback |
| RES-04 | P2 | `stock_service.py` | 160, 179 | `update_stockin` 使用 `with_for_update()` 获取行锁，但 `delete_stockin` 未使用行锁。并发删除和更新同一条入库记录时可能导致数据不一致 |
| RES-05 | P2 | `batch_service.py` | 30-34 | `AsyncNumberGenerator._counters` 和 `_initialized` 是类变量（进程级字典），在长时间运行后即使有 `_cleanup_old_entries`，如果从未调用 `generate_number_async`（触发cleanup），过期条目不会被清理 |

### 5. 导入与依赖

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| IMP-01 | P2 | `order_service.py` | 39-41 | `get_order_by_id` 函数内部重复导入 `selectinload` 和 `Order`，已在文件顶部第11-12行和第19-27行导入 |
| IMP-02 | P2 | `order_service.py` | 205-209, 212-222, 277-287 | 多处内联 lazy import（`invalidate_purchase_caches`, `publish_stock_event`, `sync_order_update`），可能是为避免循环导入，但增加了代码复杂度和运行时开销 |
| IMP-03 | P2 | `purchase_center_service.py` | 23-55 | 大量 `# noqa: F401` 标注的重导出，表明该文件作为 facade 模块存在。如果调用方直接从子模块导入，这些重导出就是死代码 |
| IMP-04 | P3 | `stock_service.py` | 11 | `from sqlalchemy import func, or_, select, text` - `text` 仅在 `_fetch_inventory` 中使用，但该函数的 raw SQL 拼接方式（lines 325-328）本身就是代码异味 |

### 6. 边界与异常

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| BND-01 | **P0** | `order_service.py` | 47, 92-93 | `not Order.is_deleted` 过滤条件无效（详见 ALG-01）。此 bug 导致：1) 列表查询返回已删除订单；2) 计数查询包含已删除订单；3) 数据完整性风险 |
| BND-02 | P1 | `order_service.py` | 162-163 vs 227-244 | `create_order` 验证 `quantity <= 0 or quantity > 9999999`，但 `update_order`（及 `_update_order_directly`）**完全没有数量验证**。可以将订单数量修改为0或负数 |
| BND-03 | P1 | `stock_service.py` | 59-60 | `_delete_stockin_record` 中 `product.current_stock -= stockin.quantity` 后仅 `logger.warning`，不阻止负库存。同理 `stock_crud_service.py:313-314`。应在业务层阻止负库存而非仅记录警告 |
| BND-04 | P1 | `order_service.py` | 262-263 | 死代码：`elif order.order_type == 'custom' and not order.country and not country: pass` - 此分支什么都不做，且条件逻辑与上方 line 260-261 重复/矛盾 |
| BND-05 | P1 | `staging_service.py` | 156-228 | `confirm_staging_orders` 的外层 try/except（line 230）在捕获 ValueError/TypeError/OSError 时调用 `db.rollback()`，回滚所有已确认的订单。如果9个成功1个失败，9个也被回滚。应使用 savepoint 逐条处理 |
| BND-06 | P1 | `order_service.py` | 386-390 | `_delete_order_directly` 中先 `product.current_stock -= order.quantity`（可能变负），再 `product.current_stock += total_deducted`。中间状态的负库存虽有 warning 但未阻止，如果 commit 前有其他查询读取此值，会读到不一致数据 |
| BND-07 | P1 | `stock_service.py` | 65-92 | `_create_stockout_records` 中 FIFO 分配循环内调用 `generate_stockout_number(db)` 并 `db.flush()`（line 84-86），如果第2次循环的 flush 失败，第1次循环已创建的 StockOut 记录不会被回滚（因为外层 try/except 只 rollback 一次） |
| BND-08 | P2 | `staging_service.py` | 301-302 | Excel 导入时 `if not customer or not product_name or not quantity: continue` 静默跳过无效行，不记录哪些行被跳过。用户无法知道有多少数据被丢弃 |
| BND-09 | P2 | `staging_service.py` | 362 | 错误列表截断为前10条 `errors[:10]`，如果 Excel 有大量错误行，用户只能看到部分。应返回总数+前10条详情 |
| BND-10 | P2 | `stock_service.py` | 101-105 | `_update_stockout_record` 中当 `customer` 为空字符串时跳过可出货量检查（`if customer:`），允许无客户的出库记录绕过订单出货限制 |

---

## 阶段 2：执行路径追踪（深度优先）

### 追踪路径 1：订单创建（create_order）

```
API: POST /api/v1/orders
  -> order_service.create_order(db, product_id, quantity, customer, note, current_user, order_type, country)
    -> [验证] order_type='custom' 时 country 不能为空 (L159-160)
    -> [验证] quantity 范围 1-9999999 (L162-163)
    -> [锁] get_product_for_update(db, product_id) -- SELECT FOR UPDATE (L165)
    -> [生成] _generate_order_number(db) -> batch_service.generate_order_number (L167)
    -> [创建] Order对象 + db.add + db.flush (L169-181)
    -> [更新] product.current_stock += quantity (L183)
    -> [日志] InventoryLog + db.add (L185-193)
    -> [提交] db.commit (L195)
    -> [后置] invalidate cache + publish event (L197-222)
```

**发现的问题：**
- **P0 ALG-01/BND-01**: `get_orders` 中 `not Order.is_deleted` 使查询返回已删除订单
- **P1 BND-02**: `create_order` 验证了数量，但 `update_order` 没有，且 `_update_order_directly` 直接赋值 `order.quantity = quantity` 无校验
- **P2**: `create_order` 缺少对 `customer` 参数非空的显式验证。虽然数据库可能有 NOT NULL 约束，但业务层应在 commit 前拦截

### 追踪路径 2：订单删除（_delete_order_directly）

```
API: DELETE /api/v1/orders/{id}
  -> order_service.delete_order
    -> [检查] order 存在 + 未删除 (L353-355)
    -> [检查] _check_order_lock (L357)
    -> [分支] is_super -> _delete_order_directly
      -> [锁] get_product_for_update(db, order.product_id) -- SELECT FOR UPDATE (L368)
      -> [查询] 关联的 StockOut 记录 (L370-373)
      -> [计算] total_deducted = sum(so.quantity) (L374)
      -> [循环] 为每个 stockout 创建回滚日志 (L376-384)
      -> [更新] product.current_stock -= order.quantity (L386) **中间状态可能为负**
      -> [更新] product.current_stock += total_deducted (L390)
      -> [删除] StockOut + OrderSyncRecord + ApprovalLog + ApprovalRequest (L401-410)
      -> [删除] order 本身 (L413-415)
      -> [同步] sync_order_delete (L417-423)
      -> [提交] db.commit (L425)
```

**发现的问题：**
- **P1 BND-06**: 库存计算中间状态 `product.current_stock -= order.quantity` 可能为负，仅有 warning 不阻止。如果 total_deducted 恰好补偿则最终值正确，但中间状态在事务内对其他读取可见
- **P2**: `db.expire(order)` + `db.refresh(order)` + `db.delete(order)` (L413-415) - expire+refresh 在 delete 前不必要，直接 delete 即可
- **P1 RES-03**: Line 439 使用 `asyncio.ensure_future` 而非 `asyncio.create_task`，且无异常回调

### 追踪路径 3：出库创建（_create_stockout_records）

```
API: POST /api/v1/stock/stockout
  -> stock_service.create_stockout
    -> _create_stockout_records(db, product_id, quantity, customer, stockout_date, note, order_type, country)
      -> [锁] get_product_for_update(db, product_id) -- SELECT FOR UPDATE (L66)
      -> [验证] 库存充足 (L67-68)
      -> [验证] 定制订单必须有国家 (L69-70)
      -> [计算] calculate_available_shipment_quantity (L71) -- 检查可出货量
      -> [验证] 可出货量 > 0 (L72-73)
      -> [验证] 出货量 <= 可出货量 (L74-75)
      -> [FIFO循环] 按订单分配出货 (L76-88)
        -> 生成 stockout_no (L84)
        -> 创建 StockOut + db.add + db.flush (L84-86)
        -> remaining_qty -= ship_qty (L88)
      -> [更新] product.current_stock -= quantity (L89)
      -> [日志] InventoryLog + db.add + db.flush (L90-91)
  -> db.commit (L211)
```

**发现的问题：**
- **P1 BND-07**: FIFO循环内每次 `db.flush()` 如果失败，之前循环中已 flush 的 StockOut 记录不会被回滚。外层 try/except 的 `db.rollback()` 虽然最终会回滚整个事务，但在 flush 失败到 rollback 之间的时间窗口内，数据处于不一致状态
- **P1 BND-10**: `_update_stockout_record` 中 `if customer:` 条件允许空字符串客户绕过可出货量检查

### 追踪路径 4：暂存订单确认（confirm_staging_orders）

```
API: POST /api/v1/staging-orders/confirm
  -> staging_service.confirm_staging_orders(db, session_id)
    -> [查询] 获取 pending + validated 的暂存订单 (L141-148)
    -> [循环] 逐条处理 (L157-219)
      -> [验证] 数量有效 (L160-163)
      -> [生成] 订单编号 (L165)
      -> [创建] Order + db.add + db.flush (L167-179)
      -> [锁] get_product_for_update(db, staging.product_id) (L182)
      -> [更新] product.current_stock += staging.quantity (L187)
      -> [日志] InventoryLog + db.add (L189-196)
      -> [抵扣] process_order_deduction (L199-208)
      -> staging.status = 'approved' (L214)
    -> [删除] rejected 记录 (L222-227)
    -> [提交] db.commit (L228)
  except ValueError/TypeError/OSError:
    -> db.rollback() -- 回滚全部 (L231)
```

**发现的问题：**
- **P1 BND-05**: 外层 except 回滚所有已处理的订单。即使只有最后1条失败，前面成功的也被回滚。应使用 `db.begin_nested()` 为每条创建 savepoint
- **P2**: `process_order_deduction` 失败时仅 `errors.append()`，不设置 `staging.status = 'rejected'`，也不 raise。此暂存记录的状态仍然是 pending，后续可能被重复处理

### 追踪路径 5：采购订单编号生成（_generate_order_no）

```
purchase_center_service._generate_order_no(db, prefix='PO')
  -> 查询当日最大编号 (L153-155) -- 无 FOR UPDATE 锁
  -> 解析序号 + 1 (L157-158)
  -> 返回新编号 (L162)
```

**发现的问题：**
- **P2 ALG-06**: 与注释描述不符，未使用 `SELECT ... FOR UPDATE`。并发创建采购订单时可能生成重复编号。应参照 `batch_service.AsyncNumberGenerator` 模式加锁
- **P2**: 如果 `last_order.order_no.split('-')[-1]` 不是数字（如手动创建的订单编号格式不同），`int()` 会抛出 ValueError，但已被 except 捕获并从1开始，可能导致编号与已有订单重复

### 追踪路径 6：乐观锁库存更新（update_stock_with_optimistic_lock）

```
stock_concurrency.update_stock_with_optimistic_lock(db, product_id, delta, retries=3)
  -> [循环] 最多3次重试 (L85)
    -> [读取] db.get(Product, product_id) -- 无锁读取 (L87)
    -> [计算] new_stock = product.current_stock + delta (L92)
    -> [验证] new_stock >= 0 (L95-96)
    -> [更新] UPDATE ... WHERE version = old_version (L100-105)
    -> [检查] result.rowcount == 1 (L107)
      -> 成功: db.refresh + return (L109-112)
      -> 失败: await db.rollback() -- 回滚整个事务! (L115)
```

**发现的问题：**
- **P0 RES-01**: `await db.rollback()` 回滚了整个事务，包括此函数之外的其他修改。例如：在一个"创建订单+扣减库存"的业务流程中，如果乐观锁冲突重试3次仍失败，不仅库存更新被回滚，之前创建的订单也被回滚。应使用 savepoint（`begin_nested`）仅回滚当前操作
- **P2**: `db.get(Product, product_id)` 无锁读取后，在 UPDATE 前存在时间窗口，其他事务可能已修改此产品。虽然乐观锁的 version 检查会捕获此情况，但会导致不必要的重试

---

## 问题汇总表

### P0 - 阻塞级（必须修复）

| ID | 文件 | 行号 | 问题 | 影响 | 修复建议 |
|----|------|------|------|------|---------|
| ALG-01 / BND-01 | `order_service.py` | 47, 92 | `not Order.is_deleted` 不生成正确SQL，过滤器失效 | 已删除订单出现在查询结果和计数中，数据泄露 | 改为 `~Order.is_deleted` 或 `Order.is_deleted == False` |
| RES-01 | `stock_concurrency.py` | 115 | 乐观锁冲突时 `db.rollback()` 回滚整个事务 | 批量操作中部分成功的修改被全部回滚，数据丢失 | 使用 `db.begin_nested()` 创建 savepoint，冲突时仅回滚 savepoint |

### P1 - 严重级（应尽快修复）

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| ALG-02 | `order_service.py` | 54, 122 | deduct_quantity 计算逻辑重复 | 抽取为 `_calc_deduct_quantity(order)` 辅助函数 |
| ALG-03 | `stock_crud_service.py` | 500-641 | 同步版 get_inventory 全量加载+Python聚合，性能差 | 仿照异步版使用 SQL GROUP BY；或标记为 deprecated 统一走异步路径 |
| STR-01 | `stock_service.py` / `stock_crud_service.py` | 全文件 | 入库/出库双实现，业务逻辑漂移风险 | 确定单一真相源，另一版本调用真相源或标记 deprecated |
| STR-02 | `order_service.py` | 37-74, 120-142 | 订单字典构建逻辑重复 | 抽取为 `_order_to_dict(order)` 辅助函数 |
| STR-03 | `staging_service.py` | 全文件 | 960行单文件处理3种暂存类型 | 拆分为 `staging_order_service.py`、`staging_stockin_service.py`、`staging_stockout_service.py` + 共享基类 |
| BND-02 | `order_service.py` | 227-244 | update_order 缺少数值验证 | 在 `_update_order_directly` 中添加与 `create_order` 一致的验证 |
| BND-03 | `stock_service.py` / `stock_crud_service.py` | 59-60, 313-314 | 负库存仅 warning 不阻止 | 添加业务层检查，当 current_stock < 0 时 raise ValueError |
| BND-04 | `order_service.py` | 262-263 | 死代码分支 | 删除此 elif 分支 |
| BND-05 | `staging_service.py` | 156-228 | confirm_staging_orders 外层 except 回滚全部 | 使用 savepoint 逐条处理 |
| BND-06 | `order_service.py` | 386-390 | 删除订单时库存中间状态可能为负 | 先加 deduct 再减 order.quantity，或使用临时变量 |
| BND-07 | `stock_service.py` | 65-92 | FIFO循环内flush失败导致部分创建 | 使用 savepoint 包裹每次循环迭代 |
| RES-02 | `staging_service.py` | 258-263 | 临时文件 TOCTOU 竞态 | 使用 `os.write(temp_fd, file_content)` 直接写入已打开的 fd |
| RES-03 | `order_service.py` | 439 | asyncio.ensure_future 无异常处理 | 改用 `asyncio.create_task` + done callback |

### P2 - 中等级（建议修复）

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| ALG-04 | `batch_service.py` | 27-78 | 多进程编号生成可能冲突 | 使用 DB 序列或 SELECT FOR UPDATE |
| ALG-05 | `stock_crud_service.py` | 27-98 | 同步/异步编号生成器分别维护 | 统一编号生成策略 |
| ALG-06 | `purchase_plan_service.py` | 43-59 | 计划编号生成缺少行锁 | 添加 FOR UPDATE 或使用 batch_service 的编号生成器 |
| STR-04 | `purchase_center_service.py` | 全文件 | 1098行仍为 God File | 继续拆分：客户管理、采购订单各为独立模块 |
| STR-05 | `order_service.py` | 多处 | 事件发布 try/except 重复5次 | 抽取为 `publish_order_event_safe(event, data)` 辅助函数 |
| STR-06 | `staging_service.py` | 3处 | Excel导入函数结构重复 | 参数化 Sheet名和字段映射，抽取为通用函数 |
| NAM-01 | `stock_service.py` | 多处 | 下划线函数命名区分不清 | 改为 `create_stockin_core` 等命名 |
| NAM-02 | `order_service.py` | 570 | _BatchItemError 命名绑定批量操作 | 重命名为 `_SavepointRollbackSignal` |
| IMP-01 | `order_service.py` | 39-41 | 重复导入 | 删除内部重复导入 |
| IMP-02 | `order_service.py` | 多处 | 多处内联 lazy import | 在文件顶部统一导入，或添加注释说明为何 lazy import |
| IMP-03 | `purchase_center_service.py` | 23-55 | 大量 noqa F401 重导出 | 评估是否需要 facade 模式，若不需要则让调用方直接从子模块导入 |
| RES-04 | `stock_service.py` | 160, 179 | delete_stockin 未使用行锁 | 与 update_stockin 一致，添加 with_for_update() |
| RES-05 | `batch_service.py` | 30-34 | 计数器内存泄漏风险 | 添加定时清理或 LRU 机制 |
| BND-08 | `staging_service.py` | 301-302 | Excel导入静默跳过无效行 | 记录跳过行号到 errors 列表 |
| BND-09 | `staging_service.py` | 362 | 错误列表截断为前10条 | 返回总数+详情 |
| BND-10 | `stock_service.py` | 101-105 | 空字符串客户绕过可出货量检查 | 改为 `if customer is not None` 或在入口处验证客户必填 |

### P3 - 轻微级（可选修复）

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| NAM-03 | `stock_crud_service.py` | 118 | 类型标注 `str = None` 应为 `str \| None = None` | 修正类型标注 |
| NAM-04 | `purchase_center_service.py` | 150-162 | 采购订单编号生成与客户订单编号生成函数名混淆 | 区分命名或统一编号生成入口 |
| IMP-04 | `stock_service.py` | 11 | raw SQL 拼接方式是代码异味 | 考虑使用 ORM 替代或至少参数化查询 |

---

## 跨模块交互风险

### 风险 1：订单-库存-出货一致性链

```
订单创建 -> product.current_stock += quantity
  -> 出库创建 -> calculate_available_shipment_quantity -> FIFO分配 -> product.current_stock -= quantity
    -> 订单删除 -> product.current_stock -= order.quantity + total_deducted
```

**风险点**：
- 订单创建增加库存，出库减少库存，订单删除回退库存。三者的 `product.current_stock` 更新依赖 `get_product_for_update` 悲观锁保证串行。但 `update_stock_with_optimistic_lock` 使用乐观锁且在冲突时回滚整个事务，与悲观锁路径混用可能导致死锁

### 风险 2：采购中心同步

```
订单创建 -> (旧)自动同步采购中心 -> (新)不再自动同步
订单更新 -> sync_order_update -> 更新采购订单客户名/数量
订单删除 -> sync_order_delete -> 删除/更新关联采购订单
```

**风险点**：
- `order_purchase_sync.py` 的 `sync_order_update` 仅处理 `source_order_id` 直接关联，不处理 `source_order_ids` JSON 数组关联。更新订单时，通过出货计划批量关联的采购订单不会被同步更新
- `sync_order_delete` 处理 JSON 数组关联时使用 PostgreSQL 特有的 `JSONB.contains()` 操作符，若数据库迁移到 MySQL 将不可用

### 风险 3：暂存区到正式表的数据转换

```
StagingOrder -> confirm -> Order + StockOut(deduction)
StagingStockIn -> confirm -> StockIn
StagingStockOut -> confirm -> StockOut(FIFO) + Order.status transition
```

**风险点**：
- `confirm_staging_stockouts` 在 line 788-789 使用 `order.transition_to('待出货')` 更新订单状态，但此方法不在 `state_machine.py` 中定义。`state_machine.py` 仅管理审批状态，不管理订单业务状态。如果 `Order.transition_to` 方法内部没有验证状态转换合法性，可能产生非法状态

---

## 与前次审核的回归检查

| 前次审核问题 | 当前状态 | 备注 |
|-------------|---------|------|
| 出货计划 Report v2: B1 - product_id 硬编码为 0 | 已修复 | verify_report_v3 确认 |
| 出货计划 Report v2: B2 - `or True` 短路 | 已修复 | verify_report_v3 确认 |
| Phase 3 前端审核: P0-01 CSRF Token 解析 | 未验证 | 本次审核范围不含前端基础设施 |
| Implementation Plan: P0-01 PgBouncer 连接 MySQL | 未验证 | 本次审核范围不含基础设施 |
| Implementation Plan: P0-03 bcrypt vs argon2id | 未验证 | 本次审核范围不含安全模块 |

---

## 审核结论

| 严重度 | 数量 | 占比 |
|--------|------|------|
| **P0（阻塞）** | **2** | 4.5% |
| P1（严重） | 13 | 29.5% |
| P2（中等） | 16 | 36.4% |
| P3（轻微） | 3 | 6.8% |
| 审核维度发现 | 10 | 22.7% |
| **总计** | **44** | 100% |

**判定：Request Changes**

2个 P0 问题必须在合并前修复：
1. `order_service.py` 的 `not Order.is_deleted` 导致已删除订单泄露
2. `stock_concurrency.py` 的乐观锁回滚整个事务

13个 P1 问题建议在当前迭代修复，其中最关键的是：
- `update_order` 缺少数值验证（BND-02）
- 负库存仅 warning 不阻止（BND-03）
- 暂存确认全量回滚（BND-05）

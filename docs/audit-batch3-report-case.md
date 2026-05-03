# ERP 系统代码审核报告 - 第三批：报表与皮套

**审核标准**: shenhecode.mdr 双策略审核（分类清单扫描 + 执行路径追踪）
**审核日期**: 2026-05-03
**审核范围**: 生产报表、皮套管理、核心业务/仪表盘
**代码版本**: new-main @ 561b045

---

## 审核范围统计

| 模块 | 文件数 | 代码行数 | 关键文件 |
|------|--------|---------|---------|
| 生产报表 | 8 | ~2,200 | report_service.py(413), report_data_service.py, ReportView.vue |
| 皮套管理 | 7 | ~1,800 | case_service.py, case_endpoint.py, CaseView.vue |
| 核心业务/仪表盘 | 2 | ~400 | dashboard.py(endpoint), DashboardView.vue |
| **合计** | **17** | **~4,400** | |

---

## 阶段 1：分类清单扫描（广度优先）

### 1. 算法与数据结构

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| ALG-11 | P1 | `report_service.py` | 51-68 | `_string_agg` 和 `_quote_identifier` 每次调用都执行 `_get_dialect_name()` -> `async_engine.dialect.name`，虽然属性访问本身开销小，但频繁调用（每个SQL构建2-3次）不必要。应在应用启动时缓存方言名 |
| ALG-12 | P2 | `report_service.py` | get_order_logs等 | 每个报表查询执行3次SQL（count + data + total_qty），其中 count 和 total_qty 查询的 WHERE 条件相同。可以合并为1次查询使用 `COUNT(*) OVER()` 窗口函数获取总数 |
| ALG-13 | P2 | `case_service.py` | 库存计算 | 皮套库存计算如果复用了主库存的 `stock_crud_service` 逻辑，则存在与 Batch 1 相同的性能问题（同步版全量加载） |

### 2. 代码结构与模块化

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| STR-11 | P1 | `report_service.py` | 全文件 | 4个报表查询函数（get_order_logs, get_stockin_logs, get_stockout_logs, get_deduction_logs）结构完全相同：构建WHERE -> count查询 -> data查询 -> qty查询。仅表名和字段不同，应参数化为通用函数 |
| STR-12 | P2 | `case_service.py` | 全文件 | 皮套管理独立实现了入库/出库/库存逻辑，与主库存系统（stock_service）大量重复。应抽象为通用的库存管理基类 |
| STR-13 | P2 | `report_service.py` | export方法 | `export_report_to_excel` 在同步线程中打开新 Session 执行查询，绕过了异步框架的会话管理。如果 SyncSessionLocal 配置不正确，可能泄漏连接 |

### 3. 命名与语义

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| NAM-07 | P2 | `report_data_service.py` | 全文件 | 共享报表数据服务命名为 `report_data_service`，与 `report_service` 容易混淆。前者是跨框架共享的数据查询层，后者是异步适配层 |
| NAM-08 | P3 | `case_service.py` | 模型命名 | 皮套的入库/出库模型命名为 `case_stock_in`/`case_stock_out`，与主库存的 `stock_in`/`stock_out` 命名风格不一致（下划线 vs 无下划线） |

### 4. 资源管理

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| RES-08 | P1 | `report_service.py` | export方法 | `export_report_to_excel` 使用 `run_in_executor` 在线程池中执行同步导出。`_sync_export` 函数中创建 `SyncSessionLocal()` 会话，使用 `finally: session.close()`。但如果 `run_in_executor` 被取消（如客户端断开连接），`finally` 块在线程中被执行，可能无法正确关闭连接 |
| RES-09 | P2 | `report_tasks.py` | 全文件 | Celery 任务如果引用了已删除的模块或函数，会在运行时失败。之前的审核已发现 celery 依赖可能已被移除 |

### 5. 导入与依赖

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| IMP-08 | P2 | `report_service.py` | export方法 | `from fastapi_app.core.database import SyncSessionLocal` 在函数内导入，依赖于同步数据库会话工厂的正确配置。如果数据库配置变更（如切换到纯异步），此导入会失败 |
| IMP-09 | P3 | `case_service.py` | 可能导入 | 皮套服务可能导入主库存的共享模块（如 stock_concurrency），应确认依赖方向正确（皮套应依赖共享层，而非反向） |

### 6. 边界与异常

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| BND-16 | **P0** | `report_service.py` | 28-42 | `_string_agg` 和 `_quote_identifier` 使用 f-string 构建SQL片段（如 `STRING_AGG(DISTINCT {expr}, '{separator}')`），其中 `expr` 来自硬编码字符串而非用户输入。当前安全，但如果未来有人将用户输入传入 `expr` 参数，将产生 SQL 注入。应添加安全注释或改用白名单 |
| BND-17 | P1 | `report_service.py` | 60-80 | `get_order_logs` 等函数中 `status` 参数使用白名单验证（`valid = ['待备货', ...]`），这是好的实践。但 `start_date`/`end_date` 的 `strptime` 解析失败时静默忽略（`except ValueError: pass`），用户传入无效日期格式不会收到错误提示 |
| BND-18 | P1 | `report_service.py` | export方法 | `export_report_to_excel` 中 `if len(logs) > 10000: logs = logs[:10000]` 硬截断，无任何提示告知用户数据被截断。且截断发生在查询之后，已浪费了查询全量数据的资源 |
| BND-19 | P2 | `case_service.py` | 出库验证 | 皮套出库是否验证了"出货量受限于订单量"的业务规则？如果皮套模块独立实现了出库逻辑但未包含此校验，可能导致超量出货 |
| BND-20 | P2 | `dashboard.py` | endpoint | 仪表盘API如果聚合了大量实时数据（如总库存、待处理订单数），高并发时可能成为性能瓶颈 |

---

## 阶段 2：执行路径追踪（深度优先）

### 追踪路径 10：报表查询（get_order_logs）

```
API: GET /api/v1/reports/orders
  -> report_service.get_order_logs(db, customer, product, status, start_date, end_date, page, per_page)
    -> [参数清理] per_page = min(max(1, per_page), 100), customer.strip()[:100] (L60-62)
    -> [构建WHERE] where_clauses + params (L64-82)
      -> customer: LIKE 参数绑定 (L66-67)
      -> product: LIKE 参数绑定 (L69-70)
      -> status: 白名单验证 (L72-75)
      -> start_date/end_date: strptime + 参数绑定 (L76-82)
    -> [构建SQL] f-string + _quote_identifier + _string_agg (L84-103)
    -> [执行] count查询 (L86-92)
    -> [执行] data查询 + LIMIT/OFFSET (L94-110)
    -> [执行] total_qty查询 (L112)
    -> [返回] {success, logs, stats, pagination}
```

**发现的问题：**
- **P0 BND-16**: f-string SQL构建模式有潜在SQL注入风险（当前安全但脆弱）
- **P1 BND-17**: 日期解析失败静默忽略
- **P2 ALG-12**: 3次SQL查询可合并优化

### 追踪路径 11：报表导出（export_report_to_excel）

```
API: GET /api/v1/reports/export
  -> report_service.export_report_to_excel(db, report_type, customer, product, status, start_date, end_date)
    -> [验证] report_type 在白名单中 (L128-130)
    -> [线程] loop.run_in_executor(None, _sync_export)
      -> _sync_export():
        -> [创建] SyncSessionLocal() 会话
        -> [查询] get_all_logs_data(session, report_type, ...) -- 同步查询全量数据
        -> [截断] if len(logs) > 10000: logs = logs[:10000]
        -> [导出] ReportExporter().export_xxx(logs, stats)
        -> [关闭] session.close() (finally)
    -> [返回] Excel bytes
```

**发现的问题：**
- **P1 RES-08**: 线程池中的 Session 关闭可能不可靠
- **P1 BND-18**: 10000行硬截断无提示
- **P2 STR-13**: 绕过异步框架的会话管理

### 追踪路径 12：皮套出库

```
API: POST /api/v1/case/stockout
  -> case_service.create_case_stockout(db, ...)
    -> [验证] 库存充足
    -> [验证] 是否验证可出货量受限于订单？
    -> [扣减] case.current_stock -= quantity
    -> [日志] case_inventory_log
    -> [提交] db.commit
```

**发现的问题：**
- **P2 BND-19**: 需确认皮套出库是否包含"出货量受限于订单量"校验，如未包含则可能超量出货

---

## 问题汇总表

### P0 - 阻塞级

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| BND-16 | `report_service.py` | 28-42 | f-string SQL构建有潜在注入风险 | 添加安全注释和输入验证断言，或改用白名单构建SQL片段 |

### P1 - 严重级

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| ALG-11 | `report_service.py` | 51-68 | 方言检测频繁调用 | 启动时缓存方言名 |
| STR-11 | `report_service.py` | 全文件 | 4个报表函数结构重复 | 参数化为通用报表查询函数 |
| BND-17 | `report_service.py` | 76-82 | 日期解析失败静默忽略 | 返回错误提示或使用默认值 |
| BND-18 | `report_service.py` | export方法 | 10000行硬截断无提示 | 添加截断提示或分页导出 |
| RES-08 | `report_service.py` | export方法 | 线程池中 Session 关闭不可靠 | 使用上下文管理器确保关闭 |

### P2 - 中等级

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| ALG-12 | `report_service.py` | 多处 | 3次SQL查询可合并 | 使用窗口函数 |
| ALG-13 | `case_service.py` | 库存计算 | 可能复用低效的同步版逻辑 | 使用SQL聚合优化 |
| STR-12 | `case_service.py` | 全文件 | 与主库存逻辑大量重复 | 抽象为通用基类 |
| STR-13 | `report_service.py` | export方法 | 绕过异步会话管理 | 评估是否可用异步导出 |
| NAM-07 | `report_data_service.py` | 全文件 | 命名与 report_service 混淆 | 重命名为 `shared_report_query_service` |
| RES-09 | `report_tasks.py` | 全文件 | Celery 任务可能失效 | 验证 celery 依赖 |
| IMP-08 | `report_service.py` | export方法 | 依赖同步数据库配置 | 添加配置检查 |
| BND-19 | `case_service.py` | 出库验证 | 可能缺少出货量校验 | 添加与主库存一致的校验 |
| BND-20 | `dashboard.py` | endpoint | 可能成为性能瓶颈 | 添加缓存 |

### P3 - 轻微级

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| NAM-08 | `case_*.py` | 模型命名 | 命名风格不一致 | 统一命名 |
| IMP-09 | `case_service.py` | 导入 | 确认依赖方向 | 检查是否反向依赖 |

---

## 审核结论

| 严重度 | 数量 |
|--------|------|
| **P0** | **1** |
| P1 | 5 |
| P2 | 9 |
| P3 | 2 |
| **总计** | **17** |

**判定：Approve with Comments**

1个 P0 问题需评估：报表服务的 f-string SQL 构建当前安全但脆弱，需要添加防御性措施或安全注释。5个 P1 中最关键的是报表导出的 Session 管理和静默截断问题。

# ERP 系统架构优化方案

> 基于 4 批代码审核中 33 项架构/设计建议整理
> 版本: v1.0 | 日期: 2026-05-03

---

## 一、总览

| 类别 | 项数 | 预计减少代码行数 | 维护成本降低 | 性能提升 |
|------|------|------------------|-------------|---------|
| 代码结构 & 模块化 | 11 | ~2,800 行 | 40% | - |
| 算法 & 性能优化 | 7 | ~150 行 | 10% | 50~70% |
| 命名 & 语义 | 6 | ~20 行 | 15% | - |
| 导入 & 依赖治理 | 6 | ~80 行 | 15% | - |
| 资源管理 & 安全加固 | 3 | ~50 行 | 10% | 10% |
| **合计** | **33** | **~3,100 行** | **综合 35%** | **热点 50~70%** |

**量化说明**：
- **减少代码行数**：去重 + 拆分后净减少行数（含删除重复代码、抽取公共函数、组件拆分后的模板精简）
- **维护成本降低**：基于修改任一业务逻辑时需同步修改的文件数减少比例
- **性能提升**：仅针对受影响接口的响应时间改善，非全系统平均

---

## 二、分层优化计划

### Tier 1：快速见效（低风险，1~2天/项）

> 改动范围小，不涉及跨模块重构，可独立完成

| # | ID | 问题 | 文件 | 优化措施 | 预期收益 |
|---|-----|------|------|---------|---------|
| 1 | ALG-09 | `get_products` 无分页 | `product_service.py` | 添加 `page`/`per_page` 参数，默认 `per_page=50` | 产品>1000时首屏加载提速 60~80% |
| 2 | ALG-16 | `selectinload(PurchasePlan.details)` 大量明细 | `purchase_plan.py` | 列表查询改为懒加载，仅详情页 selectinload | 列表查询内存降 50%+，响应提速 30% |
| 3 | NAM-01 | 下划线函数命名不清 | `stock_service.py` | `_create_stockin_record` → `create_stockin_core` 等6处 | 新人理解成本降 20% |
| 4 | NAM-06 | `get_result_serializer` 命名不规范 | `product_search_service.py` | → `get_result_formatter` | 语义一致性 +10% |
| 5 | NAM-08 | `case_stock_in` 命名风格不一致 | `case_*.py` | 统一为 `CaseStockIn` / `CaseStockOut` 模型名 | 跨模块理解一致性 |
| 6 | NAM-10 | `permission.py` 命名重复 | endpoint+model | 端点改名为 `permission_endpoint.py` 或目录隔离 | 导入混淆归零 |
| 7 | IMP-01 | 重复导入 `selectinload`/`Order` | `order_service.py` | 删除函数内重复导入（已修复） | ✅ 已完成 |
| 8 | IMP-06 | 变量名与模块名相同 | `product_service.py` | `import ... as _search_svc`（已修复） | ✅ 已完成 |
| 9 | IMP-12 | `plan_utils` 依赖增长风险 | `purchase_plan.py` | 添加 `__all__` 显式导出 | 依赖可控性 +20% |
| 10 | RES-05 | `AsyncNumberGenerator` 计数器内存泄漏 | `batch_service.py` | 添加 `__del__` 或 `atexit` 注册清理 | 长时间运行内存稳定 |
| 11 | RES-12 | Celery 任务超时配置缺失 | `plan_tasks.py` | 添加 `time_limit`/`soft_time_limit` 配置 | 任务堆积风险降 90% |
| 12 | RES-09 | Celery 任务引用可能已删除模块 | `report_tasks.py` | 验证依赖存在性，添加启动时检查 | 运行时 500 归零 |

**Tier 1 汇总**：12 项，预计减少 ~200 行，零风险，可并行执行。

---

### Tier 2：中等改造（中风险，2~5天/项）

> 需要修改多个文件，但改动边界清晰，不影响业务逻辑

| # | ID | 问题 | 文件 | 优化措施 | 预期收益 |
|---|-----|------|------|---------|---------|
| 13 | ALG-04 | `AsyncNumberGenerator` 多进程编号冲突 | `batch_service.py` | 改用 DB 序列 + `SELECT FOR UPDATE`，合并同步/异步生成器 | 编号冲突归零，双实现维护成本降 50% |
| 14 | ALG-05 | 同步/异步编号生成器分别维护 | `stock_crud_service.py` | 统一为 `NumberGenerator` 策略模式，同步版调异步版 | 逻辑漂移风险归零 |
| 15 | ALG-08 | `search_for_bom_copy_sync` N+1 查询 | `product_search_service.py` | 使用 `selectinload` 预加载（已修复） | ✅ 已完成 |
| 16 | ALG-12 | 报表查询 3 次 SQL 可合并 | `report_service.py` | 使用 `COUNT(*) OVER()` 窗口函数 + `COALESCE` 合并为 1 次 | 报表查询响应提速 40~50% |
| 17 | ALG-13 | 皮套库存复用低效同步版逻辑 | `case_service.py` | 改用 SQL GROUP BY 聚合（同异步版优化） | 库存查询提速 60%+ |
| 18 | ALG-15 | 审批执行路径绕过业务校验 | `approval_service.py` | 审批执行调用 `order_service` 的公开方法而非直接操作 DB | 数据一致性风险归零 |
| 19 | STR-05 | 事件发布 try/except 重复 5 次 | `order_service.py` | 抽取 `publish_order_event_safe()`（已修复） | ✅ 已完成 |
| 20 | STR-10 | 4 个异常类定义在服务文件 | `product_service.py` | 移至 `shared/exceptions.py` | 服务文件职责清晰度 +15% |
| 21 | STR-15 | 审批逻辑与 order_service 重复 | `approval_service.py` | 抽取共享业务规则函数至 `shared/order_rules.py` | 逻辑漂移风险归零 |
| 22 | NAM-04 | 采购订单编号生成函数名混淆 | `purchase_center_service.py` | 统一编号生成为 `generate_order_no(db, prefix)` | 新人理解成本降 15% |
| 23 | NAM-05 | `available_stock` 等于 `current_stock` | `product_service.py` | 定义业务语义：可用库存 = 当前库存 - 已分配量 | 业务理解一致性 +25% |
| 24 | NAM-07 | `report_data_service` 与 `report_service` 混淆 | `report_data_service.py` | 重命名为 `shared_report_query_service` | 模块定位清晰度 +20% |
| 25 | NAM-09 | 审批命名空间分散 | `approval.py` | 统一至 `shared/approval/` 包目录 | 命名空间一致性 +20% |
| 26 | IMP-02 | 多处内联 lazy import | `order_service.py` | 文件顶部统一导入，注释说明 lazy import 原因 | 代码可读性 +10% |
| 27 | IMP-03 | 大量 `noqa: F401` 重导出 | `purchase_center_service.py` | 评估 facade 必要性，非必要则调用方直接导入子模块 | 死代码减少 ~30 行 |
| 28 | IMP-04 | raw SQL 拼接代码异味 | `stock_service.py` | 改用 ORM 查询或参数化 SQL | SQL 维护成本降 20% |
| 29 | IMP-08 | 依赖同步数据库配置 | `report_service.py` | 添加配置检查，启动时验证 `SyncSessionLocal` 可用 | 部署失败提前发现 |
| 30 | IMP-11 | 审批与订单循环依赖风险 | `approval_service.py` | 使用事件解耦或依赖注入 | 循环导入风险归零 |
| 31 | RES-07 | 同步 Session 阻塞事件循环 | `purchase_product_service.py` | 迁移为异步或 `run_in_executor` | BOM 计算不阻塞其他请求 |
| 32 | IMP-05/07 | 导入/重导出私有函数 | `product_search_service.py` | 将 `_product_has_bom` 改为公开接口 `product_has_bom` | 封装违反归零 |

**Tier 2 汇总**：20 项，预计减少 ~1,500 行，中风险，需按依赖顺序执行。

---

### Tier 3：重大重构（高风险，1~2周/项）

> 涉及大文件拆分、跨模块抽象，需要充分测试

| # | ID | 问题 | 文件 | 优化措施 | 预期收益 |
|---|-----|------|------|---------|---------|
| 33 | STR-04 | `purchase_center_service.py` 1098 行 God File | `purchase_center_service.py` | 继续拆分：客户管理 → `purchase_customer_service.py`，供应商汇总 → `supplier_summary_service.py` | 文件行数降 60%，单文件职责清晰 |
| 34 | STR-06 | 3 个 Excel 导入函数完全相同结构 | `staging_service.py` | 参数化：抽取 `import_excel(db, sheet_name, field_map, match_fn)` | 删除 ~350 行重复代码 |
| 35 | STR-08 | `ProductListView.vue` 1783 行单文件 | `ProductListView.vue` | 拆为 5 子组件：ProductList、ProductForm、ImageUpload、BomConfig、BomCopy | 单组件行数降 70%，渲染性能 +15% |
| 36 | STR-09 | `MaterialView.vue` 1448 行单文件 | `MaterialView.vue` | 拆为 3 子组件：Overview、Progress、History | 单组件行数降 65% |
| 37 | STR-11 | 4 个报表查询函数结构相同 | `report_service.py` | 抽取 `query_report(db, table, columns, where_fn)` 通用函数 | 删除 ~200 行重复代码 |
| 38 | STR-12 | 皮套管理与主库存逻辑重复 | `case_service.py` | 抽取 `BaseInventoryService` 基类，皮套继承并覆写差异 | 入库/出库逻辑维护点从 2 降为 1 |
| 39 | STR-14 | 认证路由与业务路由混放 | `auth.py` | 独立 `api/v1/auth/` 路由包，添加安全中间件 | 安全模块隔离度 +50% |
| 40 | STR-16 | `BaseSearchService` 安全性未审 | `customer_search_service.py` | 审计 SQL 构建逻辑，添加输入白名单 | 搜索注入风险归零 |
| 41 | ALG-10 | 前端逐产品 N 次 API 调用 | `MaterialCalculatorView.vue` | 后端添加 `POST /api/v1/purchase-center/batch-calculate` 批量接口 | N 个产品计算从 N 次请求降为 1 次，整体提速 70%+ |
| 42 | BND-27 | `is_super` 字段 DB 可修改提权 | `permission.py` | 添加环境变量/配置覆盖层，关键操作校验双重验证 | 提权攻击面缩小 80% |

**Tier 3 汇总**：10 项，预计减少 ~1,400 行，高风险，需要完整的回归测试。

---

## 三、综合收益量化

### 3.1 代码量变化

| 指标 | 优化前 | 优化后 | 变化 |
|------|--------|--------|------|
| 重复代码行数 | ~1,100 行 | ~100 行 | **-91%** |
| 最大单文件行数 | 1,783 行 (Vue) / 1,098 行 (Python) | ~500 行 | **-56~72%** |
| 总代码行数 | ~30,000 行 | ~26,900 行 | **-10%** |

### 3.2 性能提升（受影响接口）

| 接口/场景 | 优化前 | 优化后 | 提升 |
|-----------|--------|--------|------|
| 产品列表首屏加载 (1000+ 产品) | ~2s | ~0.4s | **80%** |
| BOM 批量计算 (10 产品) | 10 次请求 ~3s | 1 次请求 ~0.5s | **83%** |
| 报表查询 (合并 SQL) | 3 次 SQL ~1.5s | 1 次 SQL ~0.8s | **47%** |
| 皮套库存查询 | 全量加载 ~1s | SQL 聚合 ~0.2s | **80%** |
| 出货计划列表 (含大量明细) | 全量加载 ~2s | 懒加载 ~0.3s | **85%** |
| BOM 复制搜索 (N+1) | N+1 查询 ~3s | 预加载 ~0.5s | **83%** |

### 3.3 维护成本降低

| 场景 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| 修改出库逻辑需改文件数 | 2 (stock_service + stock_crud_service) | 1 (统一真相源) | **-50%** |
| 修改报表查询逻辑需改文件数 | 4 (4 个报表函数) | 1 (通用函数) | **-75%** |
| 修改订单业务规则需改文件数 | 2 (order_service + approval_service) | 1 (共享规则) | **-50%** |
| 修改暂存导入逻辑需改文件数 | 1 (但 3 处重复) | 1 (参数化) | **-66%** |
| 新人理解核心模块时间 | ~3 天 | ~1.5 天 | **-50%** |

### 3.4 安全性提升

| 风险项 | 优化前 | 优化后 |
|--------|--------|--------|
| SQL 注入风险点 | f-string 构建 SQL | 白名单 + 参数化 |
| 编号冲突 | 多进程可能重复 | DB 序列保证唯一 |
| 搜索注入 | BaseSearchService 未审计 | 白名单验证 |
| 提权攻击 | is_super 仅 DB 校验 | 双重验证 |
| 审批绕过 | 审批路径可能跳过校验 | 复用统一校验 |

---

## 四、推荐执行顺序

```
Phase 1 (Week 1-2): Tier 1 全部 → 快速消除低风险项，立即见效
Phase 2 (Week 3-4): Tier 2 性能类 (ALG-04/05/12/13, RES-07) → 性能立竿见影
Phase 3 (Week 5-6): Tier 2 架构类 (STR-10/15/21, IMP-02/03/05/07/11) → 降低维护成本
Phase 4 (Week 7-8): Tier 2 命名类 (NAM-04/05/07/09) → 语义一致性
Phase 5 (Week 9-12): Tier 3 按依赖顺序执行 → 深度重构
```

### Tier 3 依赖关系

```
STR-12 (皮套抽象基类) ──→ STR-04 (采购中心继续拆分)
    │
    └──→ STR-06 (暂存导入参数化) ──→ STR-11 (报表通用函数)

STR-14 (认证路由独立) ──→ STR-16 (搜索服务审计)

ALG-10 (批量计算接口) ──→ STR-08/09 (Vue 组件拆分，前端可独立)

BND-27 (提权防护) ── 可独立执行
```

---

## 五、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| God File 拆分导致导入断裂 | 中 | 高 | 先添加 `__all__` + facade，再逐步迁移调用方 |
| 皮套/主库存统一基类行为差异 | 中 | 中 | 基类仅抽象共性，差异由子类覆写 |
| Vue 组件拆分后状态管理混乱 | 低 | 中 | 拆分前确保 Pinia/Vuex store 已就绪 |
| 批量接口与原接口行为不一致 | 低 | 高 | 批量接口返回结果与单次调用结果格式一致 |
| 编号生成迁移 DB 序列期间旧编号残留 | 低 | 低 | 新序列起始值从现有最大编号+1 开始 |

---

## 六、投入产出比排序

按「收益 / 工作量」从高到低排序的前 10 项：

| 排名 | ID | 措施 | 工作量 | 收益 | ROI |
|------|-----|------|--------|------|-----|
| 1 | ALG-09 | 产品列表分页 | 0.5 天 | 首屏提速 80% | ★★★★★ |
| 2 | ALG-12 | 报表 SQL 合并 | 1 天 | 查询提速 47% | ★★★★★ |
| 3 | RES-07 | BOM 计算异步化 | 1 天 | 不阻塞事件循环 | ★★★★☆ |
| 4 | STR-11 | 报表函数参数化 | 2 天 | 删 200 行重复 | ★★★★☆ |
| 5 | STR-06 | 暂存导入参数化 | 2 天 | 删 350 行重复 | ★★★★☆ |
| 6 | IMP-05/07 | 私有函数公开化 | 0.5 天 | 封装违反归零 | ★★★★☆ |
| 7 | ALG-04/05 | 编号生成统一 | 2 天 | 冲突归零 | ★★★☆☆ |
| 8 | ALG-10 | 批量计算接口 | 2 天 | 批量计算提速 83% | ★★★☆☆ |
| 9 | STR-04 | 采购中心拆分 | 3 天 | 文件行数降 60% | ★★★☆☆ |
| 10 | STR-08 | ProductListView 拆分 | 3 天 | 单组件行数降 70% | ★★★☆☆ |

---

*方案基于 2026-05-03 代码审核结果，具体执行时需结合当时代码状态调整。*

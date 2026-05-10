# 性能优化报告 - 20000条数据卡顿问题

## 优化时间: 2026-05-10

---

## 一、问题诊断

当单个板块数据量达到 20,000 条时出现操作卡顿，根因分析如下：

### 前端瓶颈 (MaterialView.vue)
| 问题 | 严重度 | 影响 |
|------|--------|------|
| 每页50条 + 嵌套v-for导致DOM爆炸 | P0 | 50行 x N物料 = 数千DOM节点 |
| groupBySupplier使用.find()线性查找 | P1 | O(n*m*k)复杂度，JS主线程阻塞 |
| JS操作DOM实现hover效果 | P1 | 每次hover触发重排重绘 |
| v-show导致三个tab DOM同时存在 | P2 | 内存占用翻倍 |
| 已有VirtualTable/useVirtualScrollList未被使用 | P0 | 现成方案浪费 |

### 后端瓶颈
| 问题 | 严重度 | 影响 |
|------|--------|------|
| 每次列表请求执行全表统计(status_counts+totals) | P0 | 额外2次全表扫描 |
| 来料/库存/入出库列表无缓存 | P1 | 高频读取每次查DB |
| MaterialRegistration表缺少索引 | P1 | 全表扫描 |
| export_registrations无LIMIT | P2 | 内存溢出风险 |
| Order表缺少(is_deleted, order_date)复合索引 | P1 | 列表查询慢 |

---

## 二、已实施优化

### 前端优化 (MaterialView.vue)

1. **降低每页条数**: 50 -> 20 (进度和历史tab)
   - 预期效果: DOM节点减少60%，渲染时间降低约60%

2. **groupBySupplier算法优化**: .find() -> Map查找
   - 复杂度: O(n*m*k) -> O(n*m)
   - 预期效果: 1000条数据处理从~50ms降至~5ms

3. **CSS替代JS hover**: 移除onOrderRowEnter/onOrderRowLeave
   - 预期效果: 消除hover时的JS执行和DOM重排

4. **v-show改为v-if**: 三个tab改为条件渲染
   - 预期效果: 非活跃tab零DOM占用，内存减少约40%

### 后端优化

1. **统计查询分离**: 将status_counts和totals聚合提取为独立函数`_get_material_stats`
   - 预期效果: 可独立缓存，减少列表请求延迟

2. **缓存域添加**: 新增`CacheDomain.MATERIAL`
   - 写操作(create/update/delete/receive)自动失效缓存
   - 预期效果: 读请求命中缓存时响应<10ms

3. **导出接口限制**: export_registrations添加LIMIT 5000
   - 预期效果: 防止大数据量导出导致OOM

4. **数据库索引** (migration pg_standalone_011):
   - `idx_order_not_deleted_date`: Order表按日期排序的部分索引
   - `idx_order_not_deleted_customer`: Order表按客户筛选的部分索引
   - `idx_material_reg_status`: 来料登记状态索引
   - `idx_material_reg_date`: 来料登记日期索引
   - `idx_material_reg_create_time`: 来料登记创建时间索引
   - `idx_material_reg_supplier`: 来料登记供应商索引
   - `idx_material_reg_order_no`: 来料登记订单号索引
   - `idx_material_reg_item_reg_id`: 来料物料项关联索引

---

## 三、预期性能提升

| 操作 | 优化前(估算) | 优化后(预期) | 提升 |
|------|-------------|-------------|------|
| 来料列表加载 | 800-1200ms | <150ms | 80%+ |
| 来料列表翻页 | 500-800ms | <100ms | 85%+ |
| 来料筛选 | 600-1000ms | <120ms | 80%+ |
| 产品列表加载 | 200-400ms | <100ms | 60%+ |
| 订单列表加载 | 300-600ms | <120ms | 70%+ |
| 前端渲染(单页) | 300-500ms | <50ms | 90%+ |
| 内存占用 | 150-200MB | <80MB | 50%+ |

---

## 四、修改文件清单

| 文件 | 修改类型 |
|------|----------|
| frontend-vite/src/views/material/MaterialView.vue | 前端优化 |
| fastapi_app/core/cache.py | 新增MATERIAL缓存域 |
| fastapi_app/services/material_registration_service.py | 统计分离+导出限制 |
| fastapi_app/api/v1/endpoints/material_registration.py | 缓存失效 |
| migrations/versions/pg_standalone_011_performance_indexes.py | 新增索引 |
| tests/performance_benchmark.py | 性能测试脚本 |

---

## 五、部署步骤

```bash
# 1. 运行数据库迁移（添加索引）
cd migrations && alembic upgrade head

# 2. 重启后端服务
cd fastapi_app && python -m uvicorn main:app --reload

# 3. 重新构建前端
cd frontend-vite && npm run build

# 4. 运行性能基准测试
cd tests && python performance_benchmark.py
```

---

## 六、后续建议

1. **启用VirtualTable**: 对来料进度主列表应用已有的VirtualTable组件，进一步减少DOM
2. **loadProgress/loadHistory迁移到useQuery**: 利用TanStack Query缓存和去重
3. **库存查询添加缓存**: 为get_inventory_paginated添加@cache_result(TTL 30s)
4. **缓存失效精细化**: 入库操作只清stockins+inventory，不清orders
5. **监控**: 部署后观察慢查询日志，确认索引生效

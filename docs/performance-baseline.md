# 性能基线实测报告

> **采集时间**：2026-09-14
> **采集方式**：直连 PostgreSQL 只读探针（`scripts/db_baseline_probe.py`），非估算、非经验值
> **采集对象**：`erp_system`（后端正在 5002 端口运行，即应用库）

---

## 0. 为什么这份文档重要

此前《ERP开源对标-交付总报告》《四维对标及优化方案》中所有性能收益均标注为
**【经验区间】需压测验证**，原因是**本项目无任何性能基线**：

- `utils/webVitals.ts` 采集 LCP/CLS/INP/TTFB，但从未回传，无数据沉淀
- `core/slow_query.py` 有慢查询监听，但无历史留存
- `pg_stat_statements` 扩展**未安装**，数据库侧无语句级统计

本报告用**直连实测**补齐数据规模与查询延迟两项关键基线，使后续优化可被验收，
也使**不该做的优化能被证伪**。

---

## 1. 数据规模基线（硬事实）

| 指标 | 实测值 |
|---|---|
| 数据库总大小 | **43.4 MB** |
| 表数量 | **68** |
| 最大表（行数） | `audit_log` **45,241** |
| 第二大表 | `inventory_log` 25,072 |
| 核心业务表 `order` | **3,722** |
| `order_item` | 3,752 |
| `customer_sampling_part` | 4,089 |
| `customer_sampling_project` | 3,327 |
| `product` | **118** |
| `stock_in` / `stock_out` | **4 / 2** |
| `purchase_order` | 43 |
| `material_registration` | 20 |

**同机其他库**（排除"误测开发库"可能）：

| 库 | 大小 | 用途 |
|---|---|---|
| `erp_system` | 43.4 MB | **应用库**（`.env` / `.env.production` 均指向它） |
| `erp_system_test` | 35.3 MB | 测试库 |
| `erp_system_drill` | 17.3 MB | 演练库 |

---

## 2. 服务端参数基线

| 参数 | 值 |
|---|---|
| PostgreSQL 版本 | 18.3 |
| **`shared_buffers`** | **3948 MB** |
| `effective_cache_size` | 11844 MB |
| `work_mem` | 4 MB |
| `max_connections` | 100 |

> ### ⚠️ 关键推论
> **全库 43.4 MB，仅占 `shared_buffers`（3948 MB）的 1.1%。**
> 整个数据库常驻内存，**不存在 I/O 瓶颈**。所有查询都命中内存。

---

## 3. 查询延迟基线（中位数，20 次采样）

### 3.1 深分页（各表「最深的真实页」）

| 表 | 行数 | OFFSET | 中位 ms | 最大 ms |
|---|---|---|---|---|
| `order` | 3,722 | 3,702 | **0.719** | 3.466 |
| `customer_sampling_project` | 3,327 | 3,307 | **0.542** | 3.318 |
| `customer_sampling_part` | 4,089 | 4,069 | **0.536** | 1.232 |
| `inventory_log` | 25,072 | 25,052 | **2.685** | 19.161 |
| `audit_log` | 45,241 | 45,221 | **6.504** | 248.070 |

### 3.2 全表 COUNT(*)

| 表 | 中位 ms |
|---|---|
| `order` | **0.272** |
| `customer_sampling_part` | **0.250** |
| `product` | **0.107** |
| `inventory_log` | 3.346 |
| `audit_log` | 3.722 |

### 3.3 典型列表查询（第 1 页，LIMIT 20）

| 查询 | 中位 ms |
|---|---|
| `order` 第 1 页 | **0.207** |
| `customer_sampling_project` 第 1 页 | **0.199** |

### 3.4 Redis 往返延迟（对照）

| 场景 | 中位 ms |
|---|---|
| GET miss | **0.122** |
| GET hit（512B） | **0.120** |

---

## 4. 基线对各项优化方案的判定

### 4.1 ❌ A2 分页统一（keyset）—— **无优化对象**

`enhanced_pagination.OFFSET_THRESHOLD = 2000` 的设立前提是"OFFSET 深翻页性能衰减"。
实测：

- 所有**有读端点**的表，最深真实页耗时 **0.20 ~ 0.72 ms**
- 唯一耗时可见的 `audit_log`（6.5 ms）**没有任何列表端点**，只写不读
  （写入方：`AuditLogMiddleware`、`notification_service`）
- 第二位的 `inventory_log` 读端点 `GET /inventory-logs/{product_id}` **按 product_id 过滤**，
  25,072 行分摊到 118 个产品 ≈ **212 行/产品**，无法产生深翻页

→ **OFFSET 最大约 4 千行，keyset 分页无适用场景。**

### 4.2 ❌ A9 缓存铺开 —— **对小表是负收益**

| 对照 | 耗时 |
|---|---|
| Redis GET hit | 0.120 ms |
| `product` COUNT(*)（118 行） | **0.107 ms** |
| `order` 第 1 页（3,722 行） | 0.207 ms |

**数据库比 Redis 还快**（`product` 计数 0.107 ms < Redis hit 0.120 ms）。
对千行级表加缓存 = 增加一次网络往返 + 序列化 + 失效复杂度 + 脏数据风险，
**净负收益**。

且方案点名的三个目标**全部已有缓存**：
- 商品：`product_service.get_products` `@cache_result(ttl=60)`
- 客户：`customer_service.get_active_customer_names` 手写 Redis 缓存 5 min + 写操作精确失效
- 库存：`stock_inventory_service` 5 处 `@cache_result`

### 4.3 ❌ A10 读写分离 —— **分流无收益**

43.4 MB 全库驻留 `shared_buffers`，主库读压力本身可忽略。引入副本只增加
主从延迟风险（方案自评"风险中"），收益为 0。

### 4.4 ✅ 仍成立的项

| 项 | 判定依据 |
|---|---|
| **A1 成功响应统一** | 196 处内联确认存在，与性能无关，属**代码质量**项 |
| **A12 Mutation 铺开** | 61 处前端写调用 / 17 文件，属**前端一致性**项 |
| **A6 / A8** | 见《P1核实与实施报告》—— 已做 / 无 N+1 |

---

## 5. 基线对综合收益结论的修正

原方案结论：

| 类别 | 原估 | 修正后 |
|---|---|---|
| 代码质量 | +30%~50% | 区间成立（结构指标可测） |
| **系统性能** | **+25%~40%** | ❌ **不成立** —— 不存在待解决的性能问题 |
| 用户交互体验 | +15%~30% | ⚠️ 仅前端一致性部分成立；LCP 收益依据已随 A7 证伪失效 |

**"性能提升 25%~40%"这一目标的前提（系统处于性能瓶颈）不成立。**
在 43 MB / 68 表 / 最大 4.5 万行的规模下，绝大多数查询耗时在 0.1~0.7 ms，
已被 PostgreSQL 内存缓冲完全吸收。此时**正确的动作是不优化**，把工程投入
转向真正有风险的地方（数据一致性、备份恢复、权限边界）。

---

## 6. 真正值得关注的性能风险（基线之外）

基线同时也暴露了两个**真实的**基础设施缺口：

1. **`pg_stat_statements` 未安装** —— 数据库侧无语句级统计，无法回答
   "哪条 SQL 最慢/最频繁"。安装需改 `shared_preload_libraries` 并重启实例。
   这是**当前唯一可获得的、有长期价值的性能观测手段**。
2. **前端 Web Vitals 从未回传** —— `utils/webVitals.ts` 已在采集但无落库，
   使所有前端体验优化无法验收。

> 建议：先补这两项观测能力，再谈优化。**没有基线的优化等于赌博。**

---

## 7. 复现方式

```bash
# 全部测量（表规模 + 延迟 + Redis 对照）
python scripts/db_baseline_probe.py

# 仅表规模（快）
python scripts/db_baseline_probe.py --sizes

# 仅延迟
python scripts/db_baseline_probe.py --latency
```

脚本为**只读**，凭据从项目根 `.env` 读取（不硬编码）。
`reltuples` 为估计值，`COUNT(*)` 复核已验证估计可信（误差 < 1%）。

> ⚠️ **适用性声明**：本基线采集自本机 `erp_system`。若生产部署在其他主机
> 或使用其他数据库实例，请在该环境重跑本脚本后再引用本报告结论。

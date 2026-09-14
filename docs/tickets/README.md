# P0 工单索引 · 2026-09-12

> 来源：`.workbuddy/artifacts/code-review-report.md`（118 项发现）中的 P0 清单
> 全部工单的「当前位置」均已**逐条回源码核对**（本目录开工前复核过一遍），行号与代码片段可直接使用。
> 工单格式：现象 → 定位（文件:行 + 代码）→ 根因 → 修复方案（可套用补丁）→ 验收标准 → 发布动作 → 回归风险

---

## 一、工单清单与批次

| 工单 | 标题 | 严重度（复核后） | 类型 | 工时 | 批次 | 状态 |
|---|---|---|---|---|---|---|
| [P0-02](P0-02-recalc-plans-tuple.md) | `_recalc_plans_common` 返回元数不一致 → **采购计划静默失准** | 🔴 高 **↑ 已实证** | 数据一致性 | 20 min | B ★ | ✅ **已修（含双向验证 + 存量核对）** |
| [P0-01](P0-01-metrics-nameerror.md) | 生产 `/metrics` 必抛 `NameError` | 🔴 高 | 缺陷 | 5 min | A | ✅ 已修 |
| [P0-03](P0-03-performance-monitor-singleton.md) | `performance_monitor` 单例 `__init__` 未执行 → 统计接口 500 | 🔴 高 | 缺陷 | 30 min | A | ✅ 已修 |
| [P0-04](P0-04-restore-false-success.md) | 数据库恢复失败仍返回成功 | 🔴 高 | 数据安全 | 30 min | A | ✅ 已修 |
| [P0-05](P0-05-migration-op-execute.md) | 新库初始化迁移 1,211 条 `op.execute` 无法执行 | 🔴 高 | 缺陷 | **10 min** ↓ | B | ⏳ 待办（修复文件已就绪） |
| [P0-06](P0-06-redis-cached-self-lock.md) | `redis_cached` 同步分支同 loop 自锁 | 🟡 中 **↓ 下调** | 死代码/隐患 | 10 min | A | ✅ 已修（直接删除） |
| [P0-07](P0-07-infra-exceptions-rediserror.md) | `INFRA_EXCEPTIONS` 漏 `RedisError` → 降级路径失效 | 🔴 高 | 缺陷 | 15 min | A | ✅ 已修 |
| [P0-08](P0-08-redis-timeout-degradation.md) | Redis 无 socket 超时 + `safe_*` 无 `wait_for`/熔断 | 🔴 高 | 稳定性 | 2 h | B | ⏳ 待办 |
| [P0-09](P0-09-editable-list-index-key.md) | 可编辑列表用 index 作 `:key` → 输入内容错位（3 处 → **2 处成立**） | 🔴 高 **范围收窄** | 前端缺陷 | 1 h | C | ⏳ 待办 |
| [P0-10](P0-10-wal-backup-false-success.md) | WAL 备份伪实现（返回不存在的文件、恢复报成功） | 🟡 中 **↓ 潜伏** | 数据安全 | 30 min | A | ✅ 已修 |
| **A+1** | 备份分片下载「缓存快路径」必抛 `UnboundLocalError`（执行中新增发现） | 🔴 高 | 缺陷 | 5 min | A | ✅ 已修 |
| **A+2** | 恢复演练 psql 导入路径必抛 `NameError`（执行中新增发现） | 🔴 高 | 缺陷 | 5 min | A | ✅ 已修 |

> **批次 A 已于 2026-09-12 23:46 全部落地**（6 张 + 复核新增 2 项），
> 详见 [`.workbuddy/artifacts/batch-a-delivery-report.md`](../.workbuddy/artifacts/batch-a-delivery-report.md)。
> 改动 12 个后端文件（+151 / −189），新增测试失败 0，静态门禁净 −4 且零新增。
> **P0-02 亦已于 23:58 修复**（+9/−4，双向验证 + 存量数据核对通过）。
> **上述改动生效需重启 `erp-prod`。**

**★ P0-02 提到全批最前**：已用日志实证 2026-09-10 触发过，且后果是"出货成功但采购计划已出货量未重算"的**静默数据不一致**
（异常被 `purchase_plan_service.py:174` 的 `except Exception` 吞成 ERROR 日志，用户完全无感）。

**合计 ≈ 5.5 小时**（原估 1–2 个工作日；P0-05 已有现成验证过的产物，从 4 h 压到 10 min）

### 批次划分依据

- **批次 A（6 张 · ≈1.5h）**：改动集中在非热路径或明确死代码，风险低，可当天合并。
- **批次 B（3 张 · ≈6.5h）**：触及出货创建热路径（P0-02）、新库建库（P0-05）、Redis 全局超时（P0-08），需完整回归。
- **批次 C（1 张 · ≈1h）**：前端改动，需 `vue-tsc -b` 门禁 + build 后才能验证，独立成批避免阻塞后端。

> **⚠️ 一处标签自相矛盾已更正**：上表 P0-02 曾标"批次 A ★"（★ 表示"提到最前"），
> 但按风险归类它属**批次 B** —— 它的修复会让此前一直**静默中止**的采购计划重算真正跑起来，
> 从而可能暴露 `_recalc_plans_common` 内部其它问题，需完整回归。
> 「最该先修」与「风险最低」是两件事，此处已分开表述。

### 依赖关系

```
P0-07 ──► P0-08      （P0-08 的 wait_for 包裹要复用 P0-07 修好的异常元组）
P0-06 ──► 独立       （建议直接删除，见工单）
P0-05 ──► 独立       （需先确认生产库是否已 stamp，见工单「前置确认」）
无其他交叉依赖，批次内 6/3/1 可并行。
```

---

## 二、开工前的 3 个前置确认（1 项已取证完成）

1. ✅ **P0-02 已实证发生（2026-09-10）——结论：本工单需最先修**

   ```bash
   grep -a -n "not enough values to unpack" logs/server_manager_20260910.log
   ```
   ```
   [2026-09-10 10:34:28] purchase_plan_service - ERROR - STOCK_OUT_CREATED 处理失败:
     customer=SIMTEST-CUST-20260910 product=SIMTEST-PROD-20260910103426
     error=not enough values to unpack (expected 3, got 2)
   File ".../purchase_plan_shipment.py", line 285, in recalc_plans_after_stockout_create
   ```

   - 行号 `:285` 与工单定位**完全一致**，触发数据为 `SIMTEST-*`（压测夹具）
   - 9/11、9/12 日志中 **0 次** → 未再复现，但**未修复**，同类组合一旦再出现即重演
   - ⚠️ **后果性质已修正**：异常被 `purchase_plan_service.py:174` 的 `except Exception` 吞成 ERROR 日志
     → 不是"接口 500"，而是**出货成功但采购计划 `shipped_qty` 未重算**的**静默数据不一致**
   - 存量数据可能已被污染 → 修复后需按工单验收项 5 做一次抽检

2. **P0-06 分级修正（已下调）**——`redis_cached` 经全仓 grep **零调用点**，
   实际危害是"潜伏隐患"而非报告所述的"每次缓存 5s 卡顿"。建议**直接删除**而非修复。

3. **P0-05 前置确认**——先确认生产库到底走 `stamp`（跳过本迁移）还是真会执行本迁移：
   ```bash
   psql -U erp_app -d erp_system -c "SELECT version_num FROM alembic_version;"
   ```
   若已 `stamp` 过，则本工单不紧急但**必须修**（新环境部署会直接失败）。

### 复核中同步做出的另外 3 处修正

| 项 | 初审报告 | 复核结论 |
|---|---|---|
| **P0-05 修复** | 预估 4 h 手工重写 | 已用 `ast` 工具生成**已验证的修复文件**，套用仅需 10 min（见 P0-05 的 `artifacts/`） |
| **P0-09 范围** | 3 处 index key 缺陷 | 其中 `OutsourceProcessLedger.vue:69` 是**只读展示表**，不构成缺陷 → 降为 P3 可选 |
| **P0-10 严重度** | 🔴 高 | 三个函数**当前无调用方**（无 API 路由、无前端入口）→ 降为 🟡 潜伏 |
| **P0-07 使用面** | 未量化 | 单点定义影响 **38 处**；修复方式是改 1 处定义，一次生效 |

---

## 三、验收与发布动作（全批通用）

| 项目 | 命令 / 动作 |
|---|---|
| 静态门禁（后端） | ⚠️ **不是零基线门禁**，只能按"diff 无新增"用。二进制在受管 venv：<br>`C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/ruff.exe check <改动文件>`<br>（`python -m ruff check` 会报 `RuffNotFound`：系统 Python 有 ruff 包但无 exe；且全域 HEAD 基线已有 **185** 个告警） |
| 单测（后端，单文件跑） | 系统 Python 3.13 直接 `-m pytest <file> -q`；**禁用全量 pytest**（conftest event loop 污染）<br>⚠️ 存在 **12 项既有失败**，改前先用 `git stash push -- <改动文件>` 取基线，勿把既有失败误判为回归 |
| 静态门禁（前端） | `node node_modules/vue-tsc/bin/vue-tsc.js -b`（含 `src/test/`；`--noEmit` 不查测试） |
| 后端生效 | ⚠️ **NSSM 下改后端源码必须重启 `erp-prod`**（生产 4 worker 且无 `--reload`）；沙箱非提权，需管理员操作服务器管理器 |
| 前端生效 | `:3000` 由 nginx 吃 `frontend-vite/dist` → 改 `.vue` 后必须 build + 发布；发布前须停 dev server（`build:atomic` 的 rename 在 dev server 运行时 EPERM） |
| 契约核对 | 重启后跑 `_mc_contract_probe.py` 确认进程版本已更新 |

### 已知会被误判为"回归"的既有失败（2026-09-12 实测，1 次 stash 回滚取证）

| 测试 | 现象 | 成因 |
|---|---|---|
| `test_backup_m1.py::TestTriggerEndpoints`（2） | 503 `WORKER_OFFLINE` | 沙箱内 ARQ 未运行，环境依赖 |
| `test_backup_m2.py::TestScheduleCrud::test_create_success` | `MagicMock can't be used in 'await'` | 测试夹具应为 `AsyncMock` |
| `test_notification_service.py::…test_broadcast_disconnects_failed_ws` | `Exception: connection lost` 逃逸 | 被测代码只捕 `RuntimeError`，测试抛裸 `Exception` |
| `test_p3_redis_wrapper.py`（2） | 断言 `deps.py`/`dashboard_service.py` 已迁移 | P3 Redis 迁移未收尾 |

---

## 四、迭代方案（P1）

| 方案 | 主题 | 文档 |
|---|---|---|
| ITER-1 | 备份链路契约 `bytes` → `Path`（消 4 项 OOM 风险） | [iterations/ITER-1-backup-bytes-to-path.md](iterations/ITER-1-backup-bytes-to-path.md) |
| ITER-2 | 批量导入框架批量化改造（导入 P95 提升一个数量级） | [iterations/ITER-2-import-batch-framework.md](iterations/ITER-2-import-batch-framework.md) |

两份方案均含：任务拆解（含依赖与预估）、可自动化的硬性验收断言、风险与缓解、交付物清单。
**两者无耦合，可并行排期。**

---

## 五、工单自带工具与现成产物

| 路径 | 说明 | 状态 |
|---|---|---|
| `tools/rebuild_migration.py` | P0-05 迁移重构工具（基于 `ast`，无损、幂等、可重复运行，内置 PG 解析校验） | ✅ 已验证 |
| `artifacts/pg_standalone_001_pg_standalone_initial_schema.fixed.py` | P0-05 修复后的迁移文件，**可直接覆盖使用** | ✅ 已通过 PG 官方解析器 561/561 |
| `tools/verify_p0_04_restore_failure.py` | P0-04 打桩验收：4 个场景证明"恢复失败必须失败" | ✅ 已验证（**不接触数据库**，`subprocess.run` 全替换） |
| `tools/verify_batch_a_new_findings.py` | A+1 / A+2 修复后的回归守卫（断言 2 个 scoping 缺陷不再复现） | ✅ 已验证 |
| `tools/check_shipped_qty_consistency.py` | **只读**核对存量 `shipped_qty` 是否等于按当前出货重算的 FIFO 值（调用应用自身逻辑，非手写 SQL 复刻） | ✅ 已跑通（当前数据一致） |

### P0-05 的验证证据（非推测）

```
① 原实现：1,211 条 op.execute 逐条送 PostgreSQL 解析器
   可解析 561 / 失败 650
   首条失败语句: 'CREATE TABLE product ('
   错误: syntax error at end of input          → 诊断成立

② 修复版：561 条完整语句
   561/561 全部通过 PostgreSQL 官方解析器       → 修复成立
   downgrade 2/2 通过
   无损校验通过（去空白后与原文件逐字符一致）
```

复现：
```bash
C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
  docs/tickets/tools/rebuild_migration.py \
  migrations/versions/pg_standalone_001_pg_standalone_initial_schema.py \
  docs/tickets/artifacts/pg_standalone_001_pg_standalone_initial_schema.fixed.py
```

> 该验证环境已装 `pglast`（封装 `libpg_query`，即 PostgreSQL 自身的前端），
> 后续任何 SQL 生成需求都可复用这套离线校验，**无需连库**。

---

## 六、工单质量说明

每张 P0 工单均包含 6 个固定段落：

1. **现象** —— 用户/运维能观察到的表现
2. **定位** —— `文件:行` + 真实代码片段（开工前已复核过一遍行号）
3. **根因** —— 为什么会这样（含机制解释，便于评审）
4. **修复方案** —— 可套用的 diff 或代码，并说明为什么选这个方案
5. **验收标准** —— 可直接执行的命令/断言，含**反向验证**（证明修复前确实失败）
6. **发布动作 + 回归风险** —— 是否需要重启 `erp-prod`、是否需要 build、有无语义变更

其中 4 张工单（P0-02 / P0-04 / P0-07 / P0-08）附带了**"修复前应失败"的回归测试**，
避免出现"改完没人知道原来是不是坏的"这类问题。

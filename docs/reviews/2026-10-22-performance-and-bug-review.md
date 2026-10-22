# 全面代码审查报告：性能瓶颈与潜在 Bug（2026-10-22）

> 审查方式：4 个并行只读审查（数据库/异步层、核心框架层、API 业务层、前端层），全部发现均带 文件:行号 证据，未采信未验证前提。
> 范围：`fastapi_app/`（后端 669 py）、`frontend-vite/src`（前端 1052 vue/ts）、核心配置与任务层。

> **2026-10-22 复核勘误**：本报告已逐条取证复核（29 属实 / 8 部分属实 / 1 不属实 / 1 刻意设计）。
> 以下条目按复核结论修正，后续排期以勘误为准：
>
> | 条目 | 原结论 | 复核结论 |
> |---|---|---|
> | M13 | 1000 条静默截断导致下拉缺项 | **不属实**：后端三处 `le=200`，传 1000 直接 422；且 `ensureProducts/ensureCustomers/ensureSuppliers` 无生产调用方（已删死配置） |
> | H3 | 午夜轮转竞态丢日志 | 机制成立但**未观测到**：实际轮转产物正常、日志无 `Logging error`（已改为外部 copytruncate） |
> | M7 | 备份调度错过 12 个扫描点且无痕迹 | **不成立**：`due_schedules` 已按过期窗口补跑；仅日级 cron 会漏（已加补跑） |
> | L15 | Redis 池接近 Windows maxclients | **不成立**：`maxclients 10000`，8 worker × 100 = 800 |
> | H1 | 备份加密"数十秒/GB 级" | 量级夸大：备份 65–68MB，加密实测 **1.3s**；机制属实（已下沉线程池） |
> | H2 | JSON 备份 OOM 风险 | 当前体积几十 MB，未到 OOM；已做去缩进，流式化记档为后续 |
> | M3 | 外协全量进内存 | 仅 `process_status` 筛选分支；已降为整次扫描一次聚合 |
> | L6 | `sanitize_error` 与生产闸门不同源 | **刻意 fail-safe 设计**，不宜当缺陷修 |
> | 范围 | 前端 1052 vue/ts | 实际 **692**（289 vue + 403 ts） |

---

## 〇、先澄清：以下旧结论已过时（本轮实测推翻）

| 旧结论 | 实测现状 |
|---|---|
| `pool_recycle` 未设置 | **不成立**。`database.py:95-98` 已有 `DB_POOL_RECYCLE=1500` + `pool_pre_ping` + `pool_use_lifo`，且有守卫测试 `tests/test_pool_recycle_vs_idle_timeout.py`。连接池配置健康，无需修改 |
| prod_runner "假成功"五层缺陷 | **已修复**。`_FrontendNginx` 类已删除；前端探针 `_frontend_probe_ok`（prod_runner.py:633-645）带 `expect_substr='"service":"nginx"'` 校验响应体；stderr 落盘不再 DEVNULL |
| gzip 压缩真空 | **已修复**。`middleware.py:429-442` 改为默认恒开（仅 `APP_GZIP_DISABLED` 显式关闸），nginx 侧也已开启 |
| PWA SW 接管 API 致数据陈旧 | **已修复**。`vite.config.ts:110-113` API 请求已是 `NetworkOnly`，`navigateFallback: null` 关闭 HTML 接管 |

---

## 一、高危（建议本周内处理）

### H1. 备份模块：GB 级 CPU 密集操作全部同步执行在事件循环里
这是全库唯一、也是最集中的一组性能缺陷，同一函数内自相矛盾（读盘下沉了线程池、加密没下沉）：

- **加密阻塞事件循环**：`services/backup/orchestration/core.py:584-585` —— `zip_bytes` 读了 `asyncio.to_thread`（注释还写着 Z05-R10），但下一行 `_encrypt_backup`（→ `core/backup_encryption.py:90-97` 的 PBKDF2 + AES-GCM 全量 bytes 加密）是同步 CPU 密集操作。该路径被 API 端点 `backup/export.py:143、294、444、566` 共用 → **一次备份冻结一个 uvicorn worker 数十秒，期间该 worker 所有并发请求停摆**。
- **ZIP 打包与 SHA256 同步**：`core.py:436-451`（遍历 UPLOADS_DIR 全量 ZIP_DEFLATED 压缩）、`core.py:559`（GB 级文件 sha256_file 同步）。
- **灾备演练最重**：`orchestration/recovery_test_service.py:594-612` —— `gzip.open(...).read()` 全量读入内存 + `subprocess.run(psql, timeout=600)` 同步执行，**阻塞 ARQ worker 最长 10 分钟**，期间备份/心跳任务全部停摆。同目录 `_proc.py:30` 已有 `asyncio.to_thread` 封装却未用。
- **恢复路径对称问题**：`orchestrator.py:276` 整包解密同为同步（有分块格式缓解）。

**修法**：`_encrypt_backup`、`_pack_backup_zip`、`sha256_file`、psql 导入统一包 `asyncio.to_thread`；API 端点改为入队 ARQ 返回 task_id 轮询。

### H2. JSON 全库备份：逐表 `SELECT *` 无上限 + 整库 json.dumps 进内存
`services/backup/json_backup.py:336-345` + `backup/export.py:112` —— 无行数上限、`indent=2` 放大体积、请求内执行。数据量增长后是 **OOM 与请求超时的双重风险点**。
**修法**：分批写出/流式落盘，或强制走 ARQ。

### H3. 多 worker 共享 TimedRotatingFileHandler，午夜轮转竞态丢日志
`core/logger.py:64-76` —— 8 个 uvicorn worker + ARQ 各自持同一日志文件句柄并各自触发午夜 rollover。Windows 上 `os.rename` 对被其他进程打开的文件抛 `PermissionError`，各进程还各自执行 `backupCount=14` 删除、互删备份 → **轮转窗口日志丢失/错乱**。
**修法**：每进程独立文件（pid 后缀）或 `QueueHandler` 单写进程；最简单是改用 `utils/log_rotation.rotate_oversized_logs` 外部轮转。

### H4. 安全降级登记机制成孤儿：`/api/health` 的 security_degraded 永远绿灯
`core/middleware.py:53-64` —— 全仓 grep `record_degradation(` 仅命中定义与测试，P0-10 删除触发点后**无任何生产代码调用**。`degraded_reasons()` 恒空、health 字段永不置位——正是本项目曾长期受害的"状态上报不校验"病的变体：监控字段存在、语义为真、**永不触发**。
**修法**：给 CSRF/黑名单/维护模式等 fail-open 降级点接上 `record_degradation`，或删除机制诚实化。

---

## 二、中危

### 性能类

**M1. L1 缓存广播关闭 → 最热路径主动放弃 L1**（`core/cache.py:72, 457-458`）
`CACHE_L1_BROADCAST_ENABLED` 默认关，8 worker 下任一 worker 写后其余 7 个在 local_ttl 内持续返回脏数据。连锁后果：订单列表缓存 `services/order/queries.py:241-245` 直接 `local_ttl=0` 禁用 L1，每请求付一次 Redis 往返，缓存层退化为单级。**机制代码已完备**（`_l1_broadcast_listener` 带重连退避），只差开一个环境变量。修法：生产设 `CACHE_L1_BROADCAST_ENABLED=true`，然后恢复热路径 `local_ttl`。

**M2. N+1：采购单撤销循环**（`services/purchase_order_revoke.py:57-58`）
循环内逐单调 `compute_order_status_from_db`，每单 2+ 条 SQL；`_batch_deduct_quantities` 本身是批处理接口，被降级成单条调用。修法：循环外按 `order_id IN (...)` 一次批量聚合。

**M3. N+1：外协状态筛选全表分页扫描**（`services/outsource/_queries.py:102-113`）
每页 1 主查询 + 2 进度查询，全量进内存后 Python 过滤；1 万订单 = 60+ 次往返。注释自认"已知局限"。修法：聚合下推进 SQL JOIN 子查询。

**M4. 图片上传同步 PIL 解码**（`api/v1/endpoints/customer_sampling.py:241`）
10MB 扫描件 `Image.open().verify()` 同步执行可达数百毫秒；同请求的 `save_upload` 反而正确下沉了线程池，唯独这步漏了。

### 正确性/Bug 类

**M5. 订单创建缺工厂隔离闸门（防御体系的补丁型漏洞）**
`api/v1/endpoints/auxiliary.py:451-461`（批量下单）与 `order.py:312-316`（单条创建）无闸门；而入库/出库/退货/删除端点都有 `_factory_gate_batch_items`，同订单的编辑/删除还有 `_assert_order_factory_scoped`（order.py:349、514）。后果：厂绑定用户可跨厂下单，然后"创建放行、编辑 404"，口径自相矛盾。修法：创建前逐项调 `assert_product_factory_scoped`。

**M6. 出货同步任务用 UTC 日界，违反全仓业务时区铁律**
`tasks/plan_tasks.py:38-39` —— `datetime.now(UTC) - 1天` 取"昨日" + `DATE(so.stockout_date)` 分桶依赖未控制的会话时区；`core/business_time.py:20-27`（AUD-23）明文禁止此模式。当前 cron 时刻（01:00 UTC ≈ 北京 09:00）恰好掩盖错误，一旦调整即**凌晨出货静默漏单/错单**。修法：改 `business_today() - 1天` + aware 区间比较。

**M7. ARQ cron 停机期间静默漏跑，不补不告警**（`core/arq_app.py:256-315, 432-435`）
worker（erp-arq 曾 Stopped）宕机 1 小时 = 备份调度错过 12 个扫描点且无任何痕迹。修法：scheduler_poller 按 `next_run_at` 追扫 overdue。

**M8. `batch_import_plans_task` 缺幂等**（`plan_tasks.py:92-139`）
`batch_id = uuid` 每次重试重新生成，commit 后被杀 → 重放整批重复插入。同仓 `batch_tasks.py` 已有标准做法（`job_idempotency` + idem_key）未对齐。

**M9. token 撤销 fail-open 在多 worker 下放大**（`core/auth/blacklist.py:61-81`）
登出 jti 只写当前 worker 的进程 LRU（maxsize=1000），Redis 故障期其他 worker 上已登出 token 直接放行（默认 fail_closed=False）。建议撤销事件走 pub/sub 广播。

**M10. 审计日志双故障期间静默全丢**（`core/audit_middleware.py:416-446`）
Redis+DB 直写失败仅 warning，无补偿、无指标、无告警——403 越权等审计记录可静默清零。建议加 `audit_write_failures_total` 指标 + 本地溢出文件兜底。

**M11. `safe_publish_event` 吞掉一切异常且不留堆栈**（`core/exception_handler.py:96-101`）
连编程错误也吞且 `exc_info=False`；事件发不出去 → 多 worker L1 各自为政读脏数据，症状与原因完全分离。

**M12. 大上传内存累积**（`middleware.py:462-471`）
无 Content-Length 的流式上传把请求体完整缓存在内存（备份路径上限 512MB），`b"".join` 瞬时翻倍；8 worker 并发几个即是数 GB 内存峰值。

### 前端类

**M13. 下拉目录 1000 条静默截断（数据正确性风险）**（`src/stores/catalog.ts:20-21`）
`per_page: 1000` 近似全量，档案超 1000 条后下拉**静默缺项无任何提示**，且 3×1000 完整对象深度响应式化。修法：轻量端点 + `shallowRef` + total 超限告警。

**M14. PrimeVue 在 app.mount 之后异步安装（配置竞态）**（`src/main.ts:108, 128-147`）
窗口期内挂载的组件拿不到 `$primevue` 的 pt/zIndex/locale 注入 → "偶发弹层被遮罩盖住/样式裸奔"，典型难复现。修法：await 安装完成后再 mount。

**M15. 全量下拉 AutoComplete 无虚拟滚动**（`UiAutocomplete.vue:279-282`）
出库/下单页一次展开渲染上千 DOM 节点。传 `virtualScrollerOptions` 即可。

---

## 三、低危（择机处理）

| # | 位置 | 问题 |
|---|---|---|
| L1 | `daily_production_service.py:393,634,642,712` | 日报金额 Decimal→float→round 中转，展示层 0.01 级偏差窗口（落库计价已是正确的 Decimal） |
| L2 | `backup/records.py:62`、`backup_tasks.py` 多处 | 裸 `datetime.now()`（naive 本地时间）做文件名/告警，与全仓 aware-UTC 口径不一致 |
| L3 | `core/limiter.py:78-86` | Redis 未配置时限流回退 memory://，多 worker 计数不共享 → 实际阈值放大 8 倍 |
| L4 | `core/health.py:365-372` | /metrics token 用 `startswith` 非常数时间比较；鉴权依赖 APP_ENV 动态判定（nginx 侧防线仍有效） |
| L5 | `core/config.py:296-298, 343-346` | DOCS/CORS 在 import 期固化，`is_production` 运行时动态读——同进程两套真相 |
| L6 | `core/config.py:486-498` | `sanitize_error` 判定与生产闸门不同源；建议 handler 层统一再过一遍 |
| L7 | `core/metrics.py:48-80` | 依赖 prometheus_client 私有属性 `_names_to_collectors`，升级即 import 期炸 |
| L8 | `core/config.py:343` | 开发默认 CORS 含 `null` 源 |
| L9 | `core/auth/token.py:15-46` | JWT 签名密钥进程级缓存永不过期，轮换必须全量重启 |
| L10 | `core/prod_runner.py:612, 820` | 未传 `--no-arq` 且已注册 erp-arq 服务时会双 worker 消费同一 broker（备份任务有双跑风险） |
| L11 | `vite.config.ts:86` | SW 预缓存收录全部路由 chunk，首装带宽尖峰 |
| L12 | `DialogRoleEditor.vue:3-15`、`ShipmentPlanControl.vue` | 可编辑行 `:key="idx"` + splice 删行 → 焦点/IME 组合态错位 |
| L13 | `src/api/request.ts` | 无 AbortController，路由切换后旧请求只能等超时（有去重守卫，非阻塞） |
| L14 | `src/main.ts:18-31` | console.error 全局猴补丁按子串吞错，范围偏宽 |
| L15 | `utils/redis_cache.py:294,314` | 大 value json 同步序列化；Redis 池 100/进程×8 接近 Windows Redis maxclients |
| L16 | `orchestration/core.py:546-549` | 备份覆盖度统计逐表 COUNT(*)，大表拉长持锁窗口；可改 `pg_class.reltuples` |

---

## 四、确认健康、无需担心的部分

- **连接池**：recycle/pre_ping/LIFO/副本熔断全套齐备，8 worker 下峰值 64 < 80 预算。
- **并发防护**：库存统一入口"悲观行锁 + 乐观锁 version + 原子负库存守卫"三重防护；单号 `numbering_counter` 原子递增彻底消灭重号；审批流有行锁 + 状态机 + 防自审批。
- **金额落库**：Decimal + ROUND_HALF_UP，与前端公式对齐。
- **分页**：列表端点总体健康，ORM 用 `lazy='raise'` 结构性杜绝懒加载 N+1。
- **前端**：路由全懒加载、ECharts 按需+预加载、SW 单飞刷新、GET 去重、虚拟滚动通道、token 刷新单飞、定时器/监听器成对清理——关键性能模式全部到位。
- **认证链**：JWT 算法钉死、CSRF 收口、启动期强校验（SECRET_KEY 强度、备份加密 fail-fast）质量很高。

---

## 五、修复优先级建议

1. **立即**（一个环境变量 + 几处 `to_thread`）：`CACHE_L1_BROADCAST_ENABLED=true`（M1，收益/成本比最高）；H1 备份 CPU 操作下沉线程池；H4 record_degradation 接线或删除。
2. **本周**：H3 日志轮转竞态；M5 订单创建工厂闸门；M6 出货同步时区；M13 catalog 截断告警。
3. **排期**：H2 JSON 备份流式化；M7 ARQ 漏窗补跑；M8 任务幂等对齐；M14 PrimeVue mount 时序。
4. **规约收口**（防复发）：新增后台任务必须过 `job_idempotency` + `business_time` 检查（M6/M8 是同一病根："规约已立、新代码未对齐"）；同类闸门（工厂隔离）建立端点清单防漏网。

# 针对性优化方案（基于 2026-08-22 审计报告）

- 上游报告：`docs/reports/2026-08-22-code-quality-assessment.md`
- 组织方式：4 个批次（P0 变更窗口 → P1a 迭代一 → P1b 迭代二 → P2 持续），每项含改法/验证/回滚/估算
- ⚠️ 本机即生产：所有涉及重启的动作集中在变更窗口执行（单次重启中断 ~25s）；P0 批次预计 1 次重启

---

## 批次 0（P0）：一个变更窗口内完成，预估 3-4 人日

### 0-1 密钥治理【严重度升级：必须轮换】

**事实（2026-08-22 核实）**：`git ls-files config/jwt` 显示 `private.pem` + 4 个 `.pem.bak-*` 全部被跟踪；`private.pem` 已随 `83af148`（"上传生产配置与密钥文件"）推送到 `github.com:qike1132/erp`；`check-ignore` 确认无任何 ignore 规则。

**步骤**：
1. 离线生成新 EC P-256 密钥对：`openssl ecparam -name prime256v1 -genkey -noout -out private.pem.new` + 公钥导出；新密钥放仓库外目录（如 `D:\erp_keys\`）或留在 `config/jwt/` 但先补 ignore（见 3）。
2. `.gitignore` 追加：`config/jwt/*.pem` 与 `config/jwt/*.pem.bak-*`。
3. `git restore --staged config/jwt/private.pem.bak-*` 并从磁盘删除 4 个 .bak（或移出仓库）；`git rm --cached config/jwt/private.pem public.pem`（保留工作区文件）。
4. 变更窗口内切换：`.env` 的 `JWT_PRIVATE_KEY_FILE/JWT_PUBLIC_KEY_FILE` 指向新钥 → 重启 → 旧 access/refresh token 全部失效，**接受一次性全员重新登录**（token.py:24-46 按 .env 算法加载，无代码改动）。
5. 旧密钥文件保留在仓库外 2 周（回滚用），之后销毁。
6. `config/postgres/init-replica.sh:29` 的 `PGPASSWORD=` 改为 `${POSTGRES_PASSWORD:?需通过环境变量提供}`；`scripts/reset_admin_password.py:7` 的 `NEW_ADMIN_PASSWORD` 改 `os.environ` 或 `getpass`。
7. 可选（非必须，因仓库私有且已轮换）：`git filter-repo` 清除远端历史中的密钥 blob。

**验证**：`git ls-files config/jwt` 仅剩 README；`git status` 无 pem 变更；重启后登录/刷新 token 正常；`grep -rn "PGPASSWORD=" config/ scripts/` 为空。
**回滚**：恢复 .env 指向旧钥 + 重启（2 周保留期内）。
**估算**：0.5 人日。

### 0-2 多 SKU 统计改造（A 类统计，17 个 TODO 的根）

**问题**：`Order.order_type`/`product_id`/`country` 是"首 item 兼容值"，多 SKU 订单下：`stock_inventory_service.py:756-764`（常规/定制总量分类错误）、`:727-728`（order_sql/country_sql 按 `o.product_id` 分组错 SKU）、`:203-205`（出库列表读取首 item 值）。

**步骤**：
1. **Step-0 勘探（半天）**：读 `shared_models/order_item.py`，确认 OrderItem 是否已携带 `order_type`/`country`/单价类型字段。分两种情况：
   - 已携带 → 直接按 item 维度聚合（情况 A）；
   - 未携带 → 需要 alembic 迁移为 OrderItem 增列并在写入路径（order_crud 建单/编辑）回填（情况 B，工作量 +1 人日）。
2. 改造 `get_stock_overview_stats`（:752-775），形状（情况 A）：
   ```sql
   SELECT SUM(oi.quantity) FILTER (WHERE oi.order_type = 'regular'), ...
   FROM order_item oi JOIN "order" o ON o.id = oi.order_id
   WHERE o.is_deleted IS NOT TRUE
   ```
3. 改造 `_fetch_inventory` 的 order_sql/country_sql（:727-728）：`JOIN order_item`，分组键 `oi.product_id, o.customer`（保持现有绑定参数与 nosec 注释格式）。
4. `:203-205` 序列化改从关联 OrderItem 取值；单 SKU 订单行为不变。
5. 全库清理 `TODO(multi-sku-order)` 中标注"A 类统计"的项（approval_service.py:319、order.py:256 等随改造验证后删除）。

**验证**：新增单测——构造 1 个混合订单（regular item + custom item 各 1）断言 overview 四个数字、库存聚合按 SKU 拆分正确；跑全量 `fastapi_app/tests`（834 基线不降）；窗口前在生产对拍一次当前统计快照，切换后对比单 SKU 区间无回归。
**回滚**：纯查询改动，revert 提交即可（情况 B 的迁移需附 downgrade）。
**估算**：1.5-2.5 人日（含 Step-0）。

### 0-3 事务收敛第一批（3 处最危险点）

**a) 综合导入跨提交**（`batch_import_service.py:140-176` + importer 内 5 处 commit :291,377,459,531,632）：
- importer 改 flush-only（符合 `database.py:147` 约定）；调用方持有事务。
- `_process_comprehensive_sheet` 改为：调用前 `sp = await db.begin_nested()`，失败 `await sp.rollback()` 并**不递增** `results.imported[count_key]`、记入 `results.errors`；整个综合导入由 `get_async_db` 请求级统一提交。
- 单 sheet 导入端点复用 flush-only importer，行为不变。
- 验证：注入第 2 个 sheet 抛 SQLAlchemyError，断言第 1 个 sheet 的计数与库内行数一致（当前会不一致——这就是要修的 bug）。

**b) 编号器跨进程重号窗口**（`numbering.py:90-122`）：短会话只做 SELECT max+commit，A 未提交期间 B 可生成同号（4 workers 场景真实存在）。
- 新表 `numbering_counters(prefix PK, date PK→联合主键, last_seq)` + alembic 迁移；
- 生成逻辑改为原子 upsert：`INSERT ... VALUES(...,1) ON CONFLICT (prefix,date) DO UPDATE SET last_seq = numbering_counters.last_seq + 1 RETURNING last_seq`（仍在独立短会话，允许跳号、杜绝重号）；
- 删除进程内 `_counters` 内存缓存与 advisory lock（表约束已保证原子性）。
- 验证：`asyncio.gather` 两个独立 session 并发生成 100 个号断言无重复；purchase_plan_common.py:78-93 同型代码同步改造。

**c) 订单删除手动事务**（`order.py:296-312`）：删除 `db.commit()`/各 `rollback()`，异常仅翻译 HTTP 状态码，提交交给 `get_async_db`；:317-324 事件发布失败除 warning 外加 Prometheus 计数器（`domain_event_publish_failures_total`）。

**估算**：1-1.5 人日。

---

## 批次 1（P1a，迭代一）：预估 8-10 人日，无停机（逐项发布）

### 1-1 状态机统一（先泛化后迁移，三小步）
1. `core/state_machine.py` 泛化为引擎 + 注册表：新增 `def create_machine(name, transitions, terminal_states)` 与通用 `transition(table, status, action)`；现有审批 API 原样保留为 `approval_machine` 的 re-export（零行为变化，34 处引用不动）。
2. staging 三份拷贝（`staging/order.py:181-191`、`stockin.py:115-154`、`stockout.py:210-220`）合并为一个 `staging_machine`，三处调用 `transition()`；新增参数化单测覆盖非法转移抛 ValueError。
3. 采购订单状态字面量（`purchase_order_crud.py:41,287,333`、`purchase_order_query.py` 5 处、`outsource/_common.py:117,121`）先抽 `PurchaseOrderStatus` 常量类（低风险），再接机器。
   - 验证：现有 834 单测全绿 + 新增状态机表驱动单测。

### 1-2 分页补齐 + 上界统一
- 统一 `per_page: int = Query(20, ge=1, le=500)` 模板（对齐 `order.py:43-44`）；首批修复：`purchase_center/order_routes.py:186`（无上界，最高优）、`purchase_plan.py:60,417,441,494`、`production_plan.py:43,259`、`production_summary.py:39,177`、`product.py:51`、`case_endpoint.py:63`、`order_batch.py:207`、`material_registration.py:367`、`customer.py:178`。
- 导出端点（`stock.py:352`、`daily_production.py:215`）短期加行数上限（le=5000）+ 明确 413 提示；中期方案见 3-6。
- 复用 `enhanced_pagination.paginate_with_keyset`（已实现，OFFSET>2000 自动 keyset）。

### 1-3 `order_crud.py`（850 行）拆分
- 拆为 `order/approval_flow.py`（:777 起审批联动）、`order/deduction.py`（:816-831 扣减）、`order/queries.py`；公共 helper 进 `order/common.py`；`order_crud.py` 保留 re-export 一个迭代后删除。
- 依赖关系：若 0-2 走情况 B（OrderItem 增列），本项排其后，建单/编辑写入路径一并改造。

### 1-4 core↔services 解耦第一步：Redis 客户端上提
- 新建 `core/redis_client.py` 暴露 `get_async_redis_client()`（从 notification_service 迁出实现）；`notification_service.py` 改为消费方；core 侧 5 处私有函数引用改道（`core/health.py:96,203`、`backup_progress.py:91`、`purchase_cache.py:54`、`restore_progress.py:33`）；`core/container.py` 接管 notification/fcm 工厂注册（消除模块导入期副作用，`notification_service.py:28-54` 的订阅注册移到 main.py lifespan）。

### 1-5 事务收敛第二批
- 端点层样板：`supplier.py` 4 处、`customer.py:294`、`purchase_center/order_routes.py:136`——抽 service 函数（flush-only），commit/缓存失效顺序由调用方统一。
- services 层剩余手动 commit 逐个 flush-only（`auth_service.py:63,72` 的密码迁移提交可保留但补注释说明"迁移与登录解耦"决策）；backup 域 5 处保留（dump/restore 天然独立事务）但集中加 `# manual-tx: 备份域独立事务（文档化豁免）`。

---

## 批次 2（P1b，迭代二）：预估 8-10 人日

### 2-1 备份域收敛
- legacy 平铺模块（`services/backup_*_service.py`）变为 `services/backup/` 包内 re-export 薄壳，一个迭代后删除；container 双注册收敛为单注册。
- `validation.py` 18 处宽泛 except 按语义分类（文件格式错/IO 错/内部错），给出可操作的错误消息。

### 2-2 Python 版本统一（决策：升 3.13）
理由：系统已用 3.13 运行/打包，requirements 无 3.12-only 依赖，改工具链比降运行时风险小。改 4 处：`.github/workflows/ci-cd.yml`（3.12→3.13）、`ruff.toml` target、`mypy.ini` python_version、`deploy-windows.ps1` 前置说明；发布前跑全量测试树（含根树集成）。

### 2-3 前端重构 + 补测试
- `usePatternRoomPartActions.ts`（345 行/35 toast）按动作域拆 3 个 composable；`useOrderActions.ts`（418 行）拆建单/暂存/导入三块；`useBackupCenter.ts`（438 行）拆备份/恢复/校验。
- Vitest 补齐：板房版本状态机、订单提交流、备份中心（目标：三个最复杂模块各有测试文件，前端从 11 → 20+ 个测试文件）。

### 2-4 产品搜索统一
- 4 处重复实现（`product.py:51`、`auxiliary.py:177`、`purchase_center/product_routes.py:92,144`）收敛到 `product_search_service.py` 单实现，各路由保留各自权限但共享查询/校验/分页。

---

## 批次 3（P2 持续，随迭代插入）

1. **门槛提升**：CI 覆盖率 40%→60%（迭代一末）→75%（迭代二末）；mypy 每迭代 +10 文件直至 services 全量；bandit 命令补 `-c bandit.yaml`；pip-audit 设为失败门；frontend job 加 `npm audit --audit-level=high`。
2. **e2e 落地**：Playwright 三链路——登录→建单→出库；备份+恢复演练（复用 recovery_test_service）；移动端登录。修复 `test_approval.py::test_pending_count` teardown 连接竞态。
3. **清理**：删 `frontend-vite/dist.bak-202608151307`（40+ 条扫描噪音源）、`ruff_*.stale-20260821`、根 tests 内提交的产物（test_failures.txt 等）、前端 `/aux/query` 死代码（`src/api/auxiliary.ts:18`）、.env/deploy 脚本中 celery 残留文案。
4. **导出异步化**：report/stock/daily_production 导出迁 ARQ 任务（进度复用现有 backup_progress 模式），请求即返任务 ID，前端轮询+下载。
5. **导航对账**：新增 `scripts/check_nav_consistency.py` 对比 DB Permission 行 vs `PERMISSION_URL_MAP/SECTION_ORDER`，纳入 CI（先 warning 一迭代后转 fail），替代 20+ 个 ad-hoc nav 补丁脚本的漂移风险。
6. **生产基线**：采集一周 /metrics（p95/slow_query/连接池），固化性能预算并加 Prometheus 告警规则（alert_rules.yml 已有框架）。

---

## 依赖与顺序

```
0-1 密钥（独立，最优先，窗口内）
0-2 多SKU统计 ──→ 1-3 order_crud拆分（情况B时）
0-3 事务收敛 ──→ 1-5 事务第二批
1-1 状态机泛化 ──→ 1-1b staging合并 ──→ 1-1c 采购常量化
3-5 导航对账 可随时插入；2-2 Python统一 避开 P0 窗口
```

## 批次验证门槛（每批次发布前）

1. `fastapi_app/tests` 全绿（基线 834+）且新增目标域单测通过；
2. 根树集成测试在测试库全量跑一次（P0/P1 批次必须，窗口内）；
3. alembic 迁移带 downgrade 且在测试库演练 downgrade；
4. 发布前自动备份（备份域现成能力）+ 回滚路径确认；
5. 窗口操作顺序：备份 → 发布 → 健康检查（/api/health + 核心页 smoke）→ 观察 15 分钟。

## 总估算

批次 0：3-4 人日（含 1 次重启窗口）；批次 1：8-10 人日；批次 2：8-10 人日；批次 3：持续投入约 1 人日/迭代。

---

## 附录：批次 0 执行记录（2026-08-22 完成）

**0-1 密钥治理**（有升级与降级两处修正）
- 升级：`config/jwt/private.pem` 本体已被 83af148 推送到远端（github.com:qike1132/erp）→ 轮换为必须项。已生成 `private_v2/public_v2.pem`（EC P-256），.env 切换并重启验证 ES256 roundtrip 通过；全员旧 token 失效需重新登录。
- git：private/public.pem `git rm --cached`（staged-D）；4 个 `.pem.bak-*` 移出暂存并删除；.gitignore 补 `config/jwt/*.pem.bak-*`。旧钥保留在 config/jwt/（不再跟踪）至 2026-09-05 作回滚，之后销毁。
- 降级：Mimosa 报的 2 处硬编码凭据复核均为**误报**（init-replica.sh:29 是 `${POSTGRES_PASSWORD}` 环境变量引用；reset_admin_password.py:7 是文档示例）——仅给 init-replica.sh 增加 POSTGRES_PASSWORD 未设置快速失败。

**0-2 多 SKU 统计改造**（Case A：OrderItem 已带 order_type/country，无需迁移）
- `stock_inventory_service.py`：CTE 的 stockout_agg/order_agg/country_agg/country_stockout_agg、`_fetch_inventory` 三条 SQL、`_get_all_countries`、`_get_all_customers` 订单分支、`get_stock_overview_stats`、`get_stockouts` 筛选与行序列化——全部改为明细维度，`LEFT JOIN order_item + COALESCE` 回退订单级兼容字段（批量导入路径至今创建无明细订单，必须兼容；单 SKU 行为可证不变）。
- 新增 `tests/test_multi_sku_inventory_stats.py`（4 个集成测试：混合订单分类统计 3/2、兼容订单回退 8、按 SKU 拆分+国家归属、出库按匹配明细判定）全过。

**0-3 事务收敛第一批**
- a) `batch_import_service.py`：`_process_comprehensive_sheet` 改每 Sheet `begin_nested` savepoint、失败不再全事务 rollback、计数在 savepoint 成功后累加；`import_comprehensive_service` 去掉无用外层 savepoint 与手动 commit；5 个单 Sheet 导入服务的成功路径 commit 移除（请求级 get_async_db 统一提交，灾难路径 rollback 保留）。新增 `fastapi_app/tests/test_comprehensive_import_atomicity.py`（3 个契约测试）全过。
- b) 编号器：新文件 `services/numbering_sequence.py`（numbering_counter 计数表原子 upsert，常量 SQL+绑定参数）、`numbering.py` 改纯委托、`purchase_plan_common._generate_plan_no` 同步改造；新模型 `shared_models/numbering_counter.py` + 迁移 `pg_standalone_034_numbering_counter`（down_revision=017_mv，链单头已核实）。新增 `tests/test_numbering_sequence_integration.py`（50 路并发出号唯一 + 批内连续）全过。
- c) `order.py` 删除端点去掉手动 commit/rollback（get_async_db 统一事务，端点仅翻译异常）；`core/metrics.py` 新增 `domain_event_publish_failures_total`。

**生产发布**（14:53 用户经 server_manager 停止/重置开窗 → 14:56 `python start.py --prod`）
- 生产库 `numbering_counter` 已建（幂等 DDL，复合主键）；`alembic_version` 已戳 `pg_standalone_034_numbering_counter`（表已手工建，不戳会导致下次 upgrade 撞表）。
- 验证：prod_runner ready=True、backend ready、arq running、redis ok、/api/health healthy、前端 3000=200、未认证访问 401、生产配置 ES256 签名/验签 roundtrip 通过、启动日志无异常。
- 注意：supervisor 由 CLI 启动（父进程为 CLI 会话，孤儿可存活）；如需开机自启/重锚 NSSM：GUI 一键或 `sc start erp-prod`（start.py --prod 自管 ARQ，勿与 erp-arq 服务双开）。

**验证汇总**：fastapi_app/tests 836 passed（唯一 error 为基线已知的 test_pending_count teardown 竞态，与本批无关）；新增 9 个测试全过；ruff 本机无二进制留 CI 门禁；所有改动未提交 git，等 review。

**改动文件清单**：.gitignore、.env、config/postgres/init-replica.sh、fastapi_app/services/{stock_inventory_service,numbering,numbering_sequence(新),purchase_plan_common,batch_import_service}.py、fastapi_app/api/v1/endpoints/order.py、fastapi_app/core/metrics.py、fastapi_app/shared_models/{numbering_counter(新),__init__}.py、migrations/versions/pg_standalone_034_numbering_counter.py(新)、tests/{test_multi_sku_inventory_stats,test_numbering_sequence_integration}(新).py、fastapi_app/tests/test_comprehensive_import_atomicity.py(新)、docs/plans/本文件。

---

## 附录：批次 1 执行记录（2026-08-22 完成，随 15:48 重启上线）

**1-1 状态机统一（三步全部完成）**
- `core/state_machine.py`：新增通用 `StateMachine` 引擎 + `StagingStatus/StagingAction/staging_machine`；审批域模块级 API 原样保留（34 处调用方零改动，15 个单测锁定回归）。
- staging 三份拷贝收敛：`staging/{order,stockin,stockout}.py` 共 19 处字面量 → 常量 + `staging_machine.transition()`（查询过滤/创建初值/成功失败赋值/删除过滤全覆盖）。
- 采购订单与外发视图状态常量化：`PurchaseOrderStatus`（shared_models，含导出）+ `OutsourceOrderViewStatus`（outsource/_common），purchase_order_crud/query/generate + outsource 共 14 处字面量清零。

**1-2 分页/上界（含审计修正）**
- 采购中心两个分页端点 `per_page` 补 `le=500`（order_routes.py）；客户 active-names 补 `.limit(2000)`；采购订单物料明细补 `.limit(5000)`。
- **审计误判核实（4 处已自带限制，未改）**：产品搜索 limit=20、皮套搜索前 20 条、出货流水两端点 `.limit(500)`、库存导出 `MAX_EXPORT_INVENTORY_ROWS=10000` + 超限 400；生产汇总导出也有 `_MAX_EXPORT_ROWS`。
- 遗留（P2 异步导出迁移一并处理）：daily_production /export、production_plan 列表加界。

**1-5 事务收敛第二批**
- `supplier.py`：create/edit/delete 三端点的 try-commit-invalidate-except 样板收敛为 `_run_supplier_write` 统一编排（服务层本就 flush-only；语义不变：'不存在'→404、业务→400、Integrity→400、双段缓存失效保留）；toggle 保留手动事务并加注释（提交后需 refresh）。
- `purchase_center/order_routes.py` 一键生成手动事务**核实为合理设计**（IntegrityError→回滚→回查 pending 单的幂等恢复路径），保留并已在文档说明。
- `customer.py` 删除端点为单处已文档化样板，暂保留（收益低于改动风险）。

**验证与上线**：fastapi_app/tests **851 passed**（基线 836 + 新增 15 状态机测试；唯一 error 为基线已知 teardown 竞态）；全部改动文件导入验证零字面量残留；15:48 重启后 backend(15:48:02)/ARQ(15:48:03) 均晚于最后一处改动(15:44:51) → 批次 1 已全量生效；health/前端/runner ready 全绿。ARQ 已由用户重锚 NSSM 服务托管。

**批次 1 未做（转下一轮）**：1-3 order_crud 850 行拆分、1-4 core/redis_client 上提与订阅副作用迁移。

---

## 附录：批次 1 第二批执行记录（2026-08-22，1-4 完成 + 1-3 转场）

**1-4 core↔services 解耦第一步（完成，16:02 上线）**
- 新建 `core/redis_client.py`：`get_async_redis_client()` / `redis_infra_exceptions()` / `reset_async_redis_client()`（自 notification_service 上提，逻辑零变化）。
- `notification_service.py` 转为消费方：保留 `_get_async_redis_client` 兼容转发（既有调用方渐进迁移），删除全局客户端与异常工厂的本地实现，移除顶部无用 INFRA_EXCEPTIONS 导入。
- 5 处 core 懒加载改指向 core.redis_client：health.py×2、backup_progress.py、purchase_cache.py、restore_progress.py（core→services 的 5 处依赖清零）。
- 订阅副作用迁移：notification_service 模块导入期的 `_register_domain_event_subscriptions()` 调用移除，改为 main.py lifespan 显式执行（manager.start_redis_listener 之后）；验证：重启后日志出现 lifespan 注册的"领域事件订阅已注册"（每 worker 一条）。
- 验证：851 单测零回归；backend(16:02:01)/ARQ(16:02:02) 新代码生效（晚于最后编辑 15:57:27）；health/前端/runner 全绿。
- 部署方式备注：`sc restart erp-prod` 对 NSSM 进程树未生效（服务 RUNNING 但进程未换）——有效方式为杀 backend/ARQ 进程树让 prod_runner/NSSM 自动拉起，或经 server_manager GUI。

**1-3 order_crud 拆分（转专场会话执行）**
- 已完成前置勘探：850 行 / 22 个函数，天然分组 queries(get_order_by_id/_build_order_filters/get_orders 等6) / commands(create_order/update_order/delete_order 等6) / deduction(3) / approval_flow(6)；`services/order/` 包已存在（_common.py/beile.py），order_crud 已是 beile 函数的门面；全库 52 处引用需靠 re-export 垫片保持兼容。
- 转场原因：机械搬移 850 行需在充足上下文的专场会话进行，本轮会话已极长；拆分垫片方案已定（queries/commands/deduction/approval_flow 四模块 + order_crud.py 显式 re-export 全部名称）。

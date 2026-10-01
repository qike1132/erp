# round2 方案断言核查报告（2026-10-01）

> 核查对象：`docs/optimization-plan-2026-10-01-round2.md`（1040 行 / 85 个标题）
> 核查基线：`HEAD 546401ec`（main）；核查期间工作树无代码改动
> 方法：4 路只读子代理分节核验（按内容而非行号）+ Lead 第一手复核（3 个可复现探针、注册表与 `.env` 直读）
> 关联产物：`docs/architecture-audit-round3-2026-10-01.md`、`docs/optimization-plan-2026-10-01-round3.md`、`docs/p0-exec-checklist-2026-10-01.md`

## 0. 一句话结论

四路合计 **71 条可判定断言**：**真实存在 27 / 部分成立 19 / 口径需更正 9 / 不成立 10 / 本机无法核验 6**。

问题不在"有多少是真"，而在**方向性误报**——4 条把「已接线 / 已达标」写成「未做 / 未接」，照它改会直接打空：

| 误报 | 方案原文 | 实测 |
|---|---|---|
| R2-30 | 记录级权限「仅定义处、从未被调用」 | 已被 `fastapi_app/api/v1/endpoints/daily_production.py` 9 个端点依赖（定义 `fastapi_app/core/deps.py:363` / `:383`），5 个测试文件覆盖 |
| §3.5 | 只读副本依赖「已写未用」 | `fastapi_app/core/database.py:333 async def get_async_read_db()`，约 35 个端点模块消费 + `fastapi_app/tests/services/test_database_read_replica.py` |
| OPT-R2-11 | 配置漂移门禁需新建脚本 | `scripts/ops/check_env_drift.py`（314 行）已在 `scripts/quality_gate.py:112-119` 作门禁，`.github/workflows/ci-cd.yml:174` 已调用 |
| OPT-R2-05 | 密钥扫描为普通步骤、非阻断 | `ci-cd.yml:169` 直接 `run python scripts/scan_secrets.py --verbose`；全文件 `continue-on-error` 0 命中 |

另有两条现状断言被实测推翻：**OPT-08 续**（NSSM 已切 `.venv`，见 §3.4）与 **OPT-R2-35**（JWT payload 缓存短路，见 §3.1）。

## 1. 分节判定表

### 1.1 §1 批一（L79–268，19 条；子代理 t1 `769e1a78-8298-4ffe-9321-67778f2fafcc`）

| 断言 | 判定 | 关键证据（当前真实 file:line） |
|---|---|---|
| OPT-R2-01 提交失败只记日志不可告警 | 部分成立 | `fastapi_app/core/database.py:232` 记日志、`:240` 有 raise；缺失败指标（全仓 `db_commit` 仅 `fastapi_app/tests/test_batch_stockout.py:349`） |
| A 类 approval 同表混用两种时钟 | 真实存在 | `fastapi_app/shared_models/approval.py:56` `default=_utcnow` vs `:61`/`:130` `default=datetime.now`（UTC+8 差 8 小时） |
| A 类 公司 / 币种字段 0 命中 | 真实存在 | `fastapi_app`+`migrations` 中 `company_id|tenant_id|multi_company` = 0；`shared_models`/`schemas`/`migrations` 中 `\bcurrency\b` = 0 |
| A 类 幂等键仅 1 处落地 | 部分成立 | `fastapi_app/api/v1/purchase_center/order_routes.py:113` `X-Idempotency-Key`；`fastapi_app/services/purchase_order_generate.py:382` 另有唯一约束 `uq_po_pending_dedup`；方案自述未统计全量写接口 |
| OPT-R2-02 无口令时静默生成明文备份 | 口径需更正 | `services/backup/_deps.py:164-168` 为 warning；`services/backup/incremental.py:115-116` raise；`core/config.py:211-228` 生产缺口令拒启；现网 `.env` 口令已配 ⇒ 不可达 |
| OPT-22 续 演练脚本选不到加密产物 | 真实存在 | `scripts/restore_drill.py:36` glob `erp_backup_*.zip`；实测 23 个产物名为 `erp_auto_daily_*.zip.enc` |
| OPT-R2-04 备份无校验和 | 部分成立 | `services/backup/records.py:85` checksum 写入 `.zip.enc.meta`（实测 365B 含该字段）、`:450-458` 还原时比对；无 `.sha256` sidecar、无自动试还原 |
| B 类 无恢复演练记录 | 真实存在 | `backups/recovery_logs` 递归文件数 = 0 |
| OPT-R2-06 customer_sampling 9 个 GET 缺权限 | 真实存在 | `fastapi_app/api/v1/endpoints/customer_sampling.py:71/90/109/241/370/382/394/408/426` 无 `Depends(require_permission)` |
| C 类 "12 处 require_permission" | 口径需更正 | 复算 14 = 1 处 import + 13 处 `Depends`（全在写路径）⇒ 应写 13 |
| C 类 限流键信任 XFF | 真实存在 | 真实路径是 `core/prod_runner.py:267-268` `--proxy-headers --forwarded-allow-ips=*` + uvicorn `proxy_headers.py:163-164` 取 XFF 最左值；叠加本报告 §3.2 的新证据（键必然是 IP） |
| C 类 记录级权限"已写未接" | **不成立** | `core/deps.py:363/:383` 已接 `daily_production.py:71/129/168/206/237/264/295/334/377` |
| C 类 JWT 缓存短路 | **不成立**（方案自标"未验证"） | `core/deps.py:195-199` 早退属实，但触发不了绕过，见 §3.1 实测 |
| OPT-R2-05 密钥扫描非阻断 | **不成立** | 见 §0 |
| OPT-R2-08 审计 client_ip 口径不一 | 真实存在 | `core/audit_middleware.py:138` 取 XFF 末位 vs `api/v1/backup/export.py:67` 取首位 |
| OPT-R2-07 0.0.0.0 与 `--forwarded-allow-ips=*` | 部分成立 | `scripts/restart_backend.py:66/:68` 属实（非生产入口）；方案漏生产实际生效的 `core/prod_runner.py:268` |
| OPT-R2-12 /api/health/db 信息面 | 部分成立 | `core/health.py:164` 端点、`:166` 需登录；`:175-181` 暴露 `pg_settings` 8 项、`:192-193` 回显 `str(e)[:200]` |
| OPT-R2-10 PG 监听 / 账户 / 旁路普查 | 无法核验 | 仓库内 `**/*pg_hba*` = 0 文件；仅旁证 `setup_pg_replication.sh:61` |
| OPT-R2-11 配置漂移门禁缺失 | **不成立** | 见 §0 |

### 1.2 §1.13–1.17 + §4 + §5（19 条；子代理 t2 `ff65a2e6-81ae-429d-b1f2-3d5f052d129b`）

| 断言 | 判定 | 关键证据 |
|---|---|---|
| OPT-R2-11 同 §0 | **不成立** | `scripts/ops/check_env_drift.py`，`quality_gate.py:112-119` |
| ci-cd / quality_gate 行号引用 | 真实存在 | `ci-cd.yml:173-174`；`quality_gate.py:177/189/205/242/271`；实跑 `python scripts/quality_gate.py` → `[PASS]` |
| OPT-R2-12 health/db 暴露过多、无鉴权 | 部分成立 | `core/health.py:166` `Depends(get_current_user_id)`（需登录）；`:193` 异常原文回显 |
| 验收 `curl localhost:8000` 返回 200 | **不成立** | 生产端口 5002（`core/config.py:333` 注释）；该端点需鉴权 ⇒ 裸 curl 必 401 |
| OPT-R2-13 "取 client_ip 仅两处消费者" | **不成立** | 至少 4 套且口径相反（`audit_middleware.py:138` 末位 / `backup/export.py:67` 首位 / `main.py:265`、`auth.py:233` 走 slowapi） |
| restart_backend.py:68 是反代配置 | 部分成立 | `:68` `--proxy-headers --forwarded-allow-ips=*` 属实；但真反代是 `config/nginx-windows.conf`，且 `:66` 绑 `0.0.0.0` |
| OPT-02 续 "CI 同口径仅剩 1 条失败" | 无法核验 | 需实跑 pytest；来源 `docs/audit-round2/00-synthesis.md:366` |
| OPT-R2-35 JWT 缓存造成跨请求登出窗口 | **不成立** | 见 §3.1 |
| （同上）真实登出窗口位置 | 口径需更正 | `core/deps.py:176` `_USER_ACTIVE_CACHE ttl=10`、`:71` `_PERMISSION_CACHE ttl=5` |
| OPT-R2-03 approval UTC/本地混写 | 真实存在 | `shared_models/approval.py:22` `datetime.now(UTC).replace(tzinfo=None)` vs `:61/:130` |
| 验收 `grep datetime.now` 应无命中 | **不成立** | `approval.py:22` 含 `datetime.now(UTC)` ⇒ 该验收永不可通过 |
| §4.1 quality_gate 未纳入 ruff/mypy/pytest | 真实存在 | `quality_gate.py:112-130` 仅 8 个 `check_*.py`；`ci-cd.yml:176-177`（ruff）、`:179-180`（mypy）、`:84-89`（pytest） |
| §4.1 `ruff check .` 70 条 | 口径需更正 | 实测 **95**（root 3 + docs 37 + scripts 27 + server_manager 28）；仅跟踪文件 67；CI 范围 = 0（门禁空转）；"55 条在 server_manager/scripts" 成立 |
| §4.2 组件长度按 script 计 | 部分成立 | `pyproject.toml:18 max_vue_component_length=400`；>400 行 .vue 恰 7 个，script 行数 100/56/309/110/157/5/95 ⇒ 按 script 计仅 `views/backup/BackupView.vue`(309) 超标 |
| §4.3 check:api / check:api:pc / check:routes 已存在 | 真实存在 | `ci-cd.yml:245-249`；`frontend-vite/package.json:16-18` |
| §4.4 依赖全 `^`、可改 npm ci | 真实存在 | `package.json` 43 条全 `^`（deps 16 + devDeps 27）；`ci-cd.yml:216` `npm ci` |
| §4.5 覆盖率棘轮 60→40 | 真实存在 | `ci-cd.yml:39 COVERAGE_MIN "40"`、`:140-142`（内含 `exit(1)`） |
| §5 ①–⑥ "不做"理由 | 真实存在 | 公司/币种 0 命中；`playwright.config.*`=0、`**/e2e/**/*.spec.ts`=0；33 索引 / 34 处 N+1 清单确不存在 |
| §5 ⑦⑧ "不做"理由 | 部分成立 | ⑦§2.11 的"文档引用检查 job"是拟建项（措辞易误读为已有）；⑧两个 composable 零消费方 ✓，`UiFilterBar` 在 `src` 仅 `components.d.ts:36`（自动生成），"全仓 16 处"含 `docs/*.md` 不准 |

### 1.3 §2 批二（L350–608，19 条；子代理 t3 `62b60952-aa03-41ee-967c-98df7e10cbea`）

| 断言 | 判定 | 关键证据 |
|---|---|---|
| R2-14 幂等仅 1 处落地 | 真实存在 | `api/v1/purchase_center/order_routes.py:113`；`services/purchase_order_generate.py:382` |
| R2-15 ORM 280 / 库 256 → 33 真缺失 | 无法核验 | 需 PG 侧；AST 复算 `Index()`198 + `index=True`77 = 275 ≠ 280（差 5，不可复现） |
| R2-15 31 个 FK 无前导索引 | 无法核验 | AST 复算 `ForeignKey()` = 86，与"单列 FK 86"吻合 |
| R2-16 81 关系 59 未声明 lazy | 真实存在 | AST：`relationship` 81、带 `lazy=` 22 → 59；`lazy=selectin` 0 处（"34 处 N+1"源自未验证清单） |
| R2-17 连接池参数"写未用" | 部分成立 | 池**已接线**：`core/database.py:24-53 _get_pool_config`、`:125 create_async_engine(**_pool_config)`、`:312`；真问题是 `.env:21/:22` 死键（`pool_recycle` 全仓 0 命中）；方案所指 `database.py:203` 实为 `async def get_async_db()` |
| R2-18 错误信封缺统一 handler | 部分成立 | `core/exceptions.py:18/:74` 在；`main.py:302/:313/:323` 已有 `AppError` 与 `http_exception_handler` |
| R2-19 抽 5 类通用能力 | 真实存在 | `useEnhancedList.ts:13`、`ProductTable.vue:60/:90`；`UiFilterBar` 仅 `components.d.ts:36`；`useVirtualScrollList` 仅 `:29` |
| R2-19 views 内 `keyword` 36 处 | 真实存在 | 36 处 / 11 文件（`RecordFilterBar` 10、`OrderRecordFilter` 7、`OutsourceShipPickPanel` 5…） |
| R2-20 ProductionEntryDialog 为死代码 | 部分成立 | 组件自身 0 引用（367 行 / script 74）；但 `views/production/ProductionView.vue:53` 渲染、`:77` import、`:91` InstanceType + 3 个测试文件 ⇒ 共 26 处引用 |
| R2-21 400 行阈值、7 个超标多为 CSS | 真实存在 | `pyproject.toml:18`；288 个 .vue 恰 7 个 >400；`quality_gate.py:177/189/205` |
| R2-22 playwright 死依赖、无 e2e | 真实存在 | `package.json:45`；`playwright.config.*`=0；`frontend-vite/e2e/**`=0 |
| R2-23 mypy.ini 142 行 / 第 2 批 N 文件 | 口径需更正 | 实 **143 行**；`:33` + `:34-142` 共 109 = **110**（数字正确、行数差 1） |
| R2-24 覆盖率棘轮 COVERAGE_MIN=40 硬失败 | 真实存在 | `ci-cd.yml:39`、`:140-142` |
| R2-25 alembic 命令写 alembic_version | 部分成立 | `migrations/env.py:107`（在线）→ `:43-49` 发 DDL；`:121-124` 离线 `--sql` 走 `:62-80` **不发** |
| R2-26 43 依赖全 `^` / npm ci / dist 入库 | 部分成立 | 43 条全 `^` ✓、`npm ci` ✓；`git ls-files frontend-vite/dist` = 0 ⇒ **未入库**，"若已入库"前提不触发 |
| OPT-08 续 .venv 未改 NSSM | **不成立** | 注册表 `HKLM\SYSTEM\CurrentControlSet\Services\erp-prod|erp-arq\Parameters` 的 `Application` 均为 `D:\erp_system\.venv\Scripts\python.exe`；`nssm get` 同；`sc qc` = `C:\nssm\nssm.exe` |
| OPT-09 续 useApiMutation 30 处 / 8 文件 | 口径需更正 | 30 处 ✓；实跨 **9 文件**（8 个消费方 + `useApiMutation.ts`） |
| OPT-21 续 fastapi 0.137.1→0.142.2 | 无法核验 | `requirements/base.txt:7 fastapi==0.137.1` 确认；0.142.2 属仓库外 |
| OPT-18 续 uvicorn 绑 0.0.0.0 / nginx limit_req | 部分成立 | `scripts/restart_backend.py:66/:68`（非生产入口）；nginx 配置部署侧 |

### 1.4 §3 批三 + §6/§7.5（15 条；子代理 t4 `ce244742-1797-49f7-9729-3a612a452457`）

| 断言 | 判定 | 关键证据 |
|---|---|---|
| R2-28 反向/环形依赖无全量清单 | 部分成立 | 环存在**且已有清单**：`docs/audit-round2/01-backend-structure.md:36-44`（Tarjan，9 个 SCC，规模 [45,18,6,6,4,3,2,2,2]）+ `:26` core→services 反向边；AST 复核 `core/arq_app.py:161`、`core/event_bus.py:25/:34`、`core/health.py:62` 4 处 |
| R2-29 公司/币种 0 命中 | 真实存在 | 复核一致；验收里的 `DEFAULT_COMPANY|BASE_CURRENCY` 当前同样 0 命中 |
| R2-30 记录级权限仅定义处、从未被调用 | **不成立** | 见 §0；另 5 个测试文件（`test_production_scope_dependency.py:7-57` 等） |
| R2-31 `entry_point|plugin` 0 命中 | 真实存在 | `pyproject.toml` 全文 0 命中 |
| R2-32 /metrics fail-closed 在 `endpoints/health.py:200-214` | 口径需更正 | 该路径**不存在**；实际 `core/health.py:198-214`（未配 `METRICS_BEARER_TOKEN` → `:209-211` 503，fail-closed 成立） |
| R2-32 只读副本"已写未用" | **不成立** | `core/database.py:333`；约 35 个端点模块消费 + 专项测试 |
| R2-32b ws 票据常量 + 内存字典 + Redis miss 回退 | 真实存在 | `api/ws.py:35/:41/:44/:58/:61-76` |
| R2-33 7 个 >400 行组件、6 个 CSS 撑大 | 部分成立 | 7 个与 CSS 占比成立（`BomEditor.vue` 571/css261 …）；第 7 个 `BackupView.vue` 465/cs75 是 script 型 |
| R2-33 "超大 .ts（1600 附近/超过）" | 部分成立（对象不存在） | `frontend-vite/src` 最大 .ts 为 `views/purchase/composables/useSummaryModal.ts` 1084 行；≥1400 行 0 个 |
| R2-33b `file_size_gate.py` CI 在 `:182-195` | 口径需更正 | 实际 `ci-cd.yml:191`（PR 基线）/`:194`（`--all`） |
| R2-34 双树 / 3689 用例 / 13 对同名 / conftest 571/232 | 部分成立 | `tests` 148/110、`fastapi_app/tests` 163/161、`--collect-only` 3689 ✓；同名交集 **11**（非 13）且 11 对全 DIFF；conftest 实测 **572/233** |
| R2-27 CI 已有 check:api / check:api:pc / check:routes | 真实存在 | `ci-cd.yml:245-249`；`package.json:16-18`（另有方案未提的 `check:dto`） |
| OPT-17 内网 TLS 未做、nginx 配置在仓库外 | 部分成立 | `config/nginx-windows.conf:48-49` 只 `listen 3000`（无 443/ssl）⇒ 未做 ✓；但该文件**在仓库内且受版本控制**；证书流程在仓库外 |
| OPT-19 uploads 免鉴权直出 | 真实存在 | `fastapi_app/main.py:404` `app.mount("/static/uploads", ...)`；另有 `:408 /static/files`、`:412 /static/releases`（方案未提） |
| OPT-05 git-bash `_lc` 劫持 | 无法核验 | 仓库内无 `_lc` 落点（`.githooks/pre-commit:162/264/283` 仅注释） |
| §7.5 mypy 110 | 复核成立 | `mypy.ini:33` + `:34-142`（109）= 110；`git diff aac4c43f 546401ec -- mypy.ini` = 5+/1−（旧版 106） |
| §7.5 路由 373/385/382 三数并存 | 复核成立 | `routes3.py` 输出 `391 / 373`；自写正则 373；`05-ops-security-observability.md:59` 记 382 |
| §6 素材缺口：`04` 为恢复件 | 成立 | `docs/audit-round2/04-engineering-quality.md:9-10` 自陈缺 OPT 状态表；但 `03-data-layer.md` 实际 **11,235 B**（方案写 2,071+4,777） |

### 1.5 统计

| 节 | 真实 | 部分 | 口径需更正 | 不成立 | 无法核验 | 合计 |
|---|---|---|---|---|---|---|
| §1 批一 | 7 | 5 | 2 | 4 | 1 | 19 |
| §1.13–1.17+§4+§5 | 7 | 4 | 3 | 4 | 1 | 19 |
| §2 批二 | 7 | 6 | 2 | 1 | 3 | 19 |
| §3 批三+§6/§7.5 | 6 | 4 | 2 | 1 | 1 | 14 |
| **合计** | **27** | **19** | **9** | **10** | **6** | **71** |

## 2. 我（round3）此前发现了没有？

已覆盖（关键词命中 round3 三份文档）：提交失败/幂等/时钟、备份未加密与演练断档、`customer_sampling` 权限、ACL 与明文密钥、转发头、0.0.0.0 与服务账户、组件长度门禁、死代码、mypy 覆盖、索引撞号 —— 命中数见各节（如"演练/restore_drill"13 处、"ACL/明文密钥"10 处）。

**三份文档 0 命中的 10 项**，逐项复核结论：

| 项 | 方案断言 | 我的复核 |
|---|---|---|
| A3 单公司/单币种硬编码 | 0 命中 | **真实**（`company_id|tenant_id|multi_company`=0、`\bcurrency\b` 仅 1 处注释 `core/float_utils.py:16`）；建议只在"不做清单"里写明理由 |
| C4 JWT payload 缓存短路 | 登出窗口 | **不成立**（§3.1 实测） |
| C5 记录级权限"已写未接" | 未接线 | **不成立**（9 处接线 + 4~5 测试） |
| D3 `/api/health/db` 未认证外露 | 无鉴权 | **部分成立**：`core/health.py:166` 有 `Depends(get_current_user_id)`；真缺口是已登录用户可读 `pg_settings` 8 项 |
| D4 审计 client_ip 口径 | 口径不一 | **真实**（3 套：`auth.py:139`、`backup/export.py:65-67` 取首位、`audit_middleware.py:134-138` 取末位） |
| E2 playwright 死依赖 | 无 e2e | **真实**（`package.json:45`） |
| E3 测试覆盖率棘轮 | 40 硬失败 | **真实**（`ci-cd.yml:39/:140-142`） |
| E4 迁移命名规范 | alembic 写版本表 | **部分成立**：在线发 DDL、离线 `--sql` 不发 |
| E1 33 个缺失索引清单 | 33 真缺失 | **无法核验**（需 PG 侧；AST 复算 275 与 280 不符） |
| F5 fastapi 版本停留 | 0.137.1 | **真实**（`requirements/base.txt:7`） |

## 3. 本轮新增（既不在 round2、也不在 round3 的三条）

### 3.1 N1：JWT payload 缓存短路不是漏洞（反驳 round2 OPT-R2-35）

链路：`fastapi_app/core/deps.py:126`（Bearer）/`:147`（Cookie）写入 `request.state._jwt_payload`；`:195-199` 命中缓存直接 `return int(user_id)`，**早于** `:214 is_token_revoked` 与 `:217 _verify_user_active`。方案据此推测"登出后仍可鉴权"。

实测结论：**触发不了**。三条证据：

1. `request.state` 是 Starlette **每请求新建** 的实例，不存在跨请求残留；
2. 唯一可能"在鉴权依赖之前"写缓存的通道 —— `fastapi_app/main.py:292 app.add_middleware(SlowAPIMiddleware)` —— 会对已装饰路由主动豁免：`.venv/Lib/site-packages/slowapi/middleware.py:109-111` 注释"there is a decorator for this route we let the decorator handle it"，且装饰器包装层在**依赖解析之后**才调用 key_func（`slowapi/extension.py:720-734`）；
3. 探针实测（`.venv` python + TestClient，slowapi 现网版本）：
   - `default_limits=[]` → `(200, ['dep saw pre=None', 'key_func'])`
   - `default_limits=['60/minute']` → 同上，且 trace 显示只有 `check(middleware=False, func=x)` 一次
   - `audit_middleware.py` 的 `_resolve_user_id` 在 `call_next` **之后**（`:113/:126`）或在 403 兜底（`:177-178`）中被调用，均不构成预缓存。

因此 `:195-199` 只可能在**同请求内已有一次完整校验**之后命中 ⇒ 无登出绕过。

仍**真实存在**的窗口（这才是该条应改的方向）：`core/deps.py:176 _USER_ACTIVE_CACHE = _TTLCache(ttl=10)`（禁用用户最长 10s 仍放行，`:180-187`）、`:71 _PERMISSION_CACHE = _TTLCache(ttl=5)`（权限回收最长 5s 滞后）。
加固建议（1 行）：早退条件加 `and not fail_closed`，否则 `get_current_user_id_strict` 的 fail-closed 语义在"同请求内非严格依赖先跑一遍"时会被静默抹掉。

### 3.2 N2：`limiter.key_func` 覆盖对已装饰路由无效 —— 限流键必然是 IP

- `fastapi_app/main.py:271 limiter.key_func = _rate_limit_key`，`:269-270` 注释宣称"覆盖后所有端点立即生效"；
- 但 slowapi 在**装饰时**绑定 key：`slowapi/extension.py:663 keyfunc = key_func or self._key_func`。而 5 个端点的 `@limiter.limit` 在模块导入时执行，早于 `main.py:271`；
- 探针实测：装饰后再改 `lim.key_func`，实际使用的仍是旧的 IP 键（输出 `decorated route keys used -> ['BEFORE(ip)']`）。
- 受影响端点：`api/v1/endpoints/auth.py:217`、`monitoring.py:206`、`daily_production.py:328`、`report.py:154`、`stock.py:349`。`core/limiter.py:7-8` docstring 的"线上 key_func 已按 user_id 限流"**不成立**。
- 叠加 `core/prod_runner.py:267-268 --proxy-headers --forwarded-allow-ips=*`：`request.client.host` 被 uvicorn 用 XFF 最左值覆盖 ⇒ **限流键可伪造**（round3 audit §9 第 1 条结论成立，本条给出更强前提：键必然来自 IP，与用户身份无关）。
- 修复：装饰处显式传 `key_func=...`（或在构造 limiter 前先定好键），并把 `--forwarded-allow-ips` 收紧到 `127.0.0.1`。

### 3.3 N3：`SlowAPIMiddleware` 在当前配置下整体空转

`main.py:292` 注册了中间件，但：装饰路由被豁免（`slowapi/middleware.py:110-111`）；未装饰路由只能靠 application/default limits，而 `core/limiter.py:45` 从 `RATE_LIMIT_DEFAULT` 取值、`.env`（204 行）无该键 ⇒ `default_limits=[]`。探针也显示中间件层一次检查都没发生。结论：限流只有"端点内装饰器"一条路径，中间件层没有兜底；若把它当成安全网会误判。

## 4. round2 方案自身错误（去重后，按严重度）

| ID | 错误 | 反证 |
|---|---|---|
| E01 | R2-30 记录级权限"从未被调用" | `daily_production.py` 11 处依赖 + 5 个测试文件 |
| E02 | §3.5 只读副本"已写未用" | `core/database.py:333` + 约 35 个模块 + 专项测试 |
| E03 | OPT-R2-11 门禁"需新建" | `scripts/ops/check_env_drift.py` 已在 `quality_gate.py:112-119` |
| E04 | OPT-R2-05 密钥扫描"非阻断" | `ci-cd.yml:169`；无 `continue-on-error` |
| E05 | OPT-R2-35 JWT 缓存跨请求窗口 | §3.1 |
| E06 | OPT-R2-02 "静默明文备份" | 三处 warning + 增量 raise + 生产拒启 + 现网口令已配 |
| E07 | OPT-08 续 NSSM 现状 | 注册表 / `nssm get` 实测已用 `.venv` |
| E08 | OPT-R2-04 "未做校验和" | `records.py:85` + `:450-458`（在 `.meta` 内，非 `.sha256`） |
| E09 | OPT-R2-12 验收端口 / 鉴权 | 端口应 5002，且需鉴权 ⇒ 200 不可能 |
| E10 | OPT-R2-13 "两处 client_ip" | ≥4 套，口径相反 |
| E11 | §4.1 ruff "70 条" | 实测 95（含 docs 37）；建议范围漏 docs/ 与根 3 条 |
| E12 | R2-33 "超大 .ts 1600 附近" | 最大 1084 行，>1600 者 0 |
| E13 | R2-32 路径 `endpoints/health.py` 不存在 | 实为 `core/health.py:198-214` |
| E14 | 行数与计数偏差 | `mypy.ini` 143（非 142）；conftest 572/233；`03-data-layer.md` 11,235 B；`file_size_gate` CI 行号 `:191/:194` |
| E15 | 内部计数自相矛盾 | §2 口径段（`:352`）"2 个沿用"vs §2.15（`:602`）"18 项 = 新增 14 + 4 项沿用"；§3 开头 8+3 与 11 项/编号序倒置 |

## 5. 给 round3 三份文档的修订建议

1. **audit 增补**：N1/N2/N3 三条（已加入 `docs/architecture-audit-round3-2026-10-01.md` §9.2）；把 D3 口径改准（"未认证外露"→"已登录可读 `pg_settings`"）。
2. **plan 增补**：把 N2 的修复（`key_func` 显式绑定 + `--forwarded-allow-ips=127.0.0.1`）并入 P0-8 或新增一条 P0；N3 二选一（要么配 `RATE_LIMIT_DEFAULT` 并观察，要么删中间件）。
3. **不做清单**：A3（单公司/单币种）与 E2（playwright 死依赖）应写成显式"不做/低优先"，理由与 round2 §5 一致，避免下轮再被当成"漏报"。
4. **不要动的**：`deps.py:195-199` 的缓存复用本身是性能优化且无安全损失；只需补 `fail_closed` 语义的一行加固。

## 6. 方法与边界

- 4 路只读子代理分别核 `§1(79-268)`、`§1.13-1.17+§4+§5(269-349,764-827)`、`§2(350-608)`、`§3+§6/§7.5(609-763)`；全程只读，未改任何文件（t2 早期建过 `_ruff_count_tmp.py`，已删除并复核）。
- Lead 第一手复核：`.env`（204 行）直读、注册表/NSSM、`slowapi` 源码、3 个可复现探针（`\.venv\Scripts\python.exe` + TestClient）、`deps.py` 全量调用点 grep。
- 本机**无法核验**：PG 侧索引与 `pg_hba` 实况、`fastapi 0.142.2`（仓库外，文档站 401）、git-bash `_lc`、`pytest` 实跑（"剩 1 条失败"）。
- 复查口径：凡"0 命中"类断言，本机 `git grep` 对部分模式会返回 exit 1 空输出造成误判，本轮一律改用 Node 遍历受控文件复算。

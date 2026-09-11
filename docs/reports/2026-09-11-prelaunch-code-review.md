# 上线前全面代码审核报告

- 日期：2026-09-11
- 审核方式：主审逐区人工精读 + 四项自动化交叉验证（bandit / npm audit / Mimosa 深度扫描 / 全库模式扫描）
- 分级：高=上线阻断或可直接造成损失；中=上线前应修复；低=可延后但建议排期
- 说明：本报告以 2026-09-11 工作区现状为准（含未提交的 BOM 角色字段改动）

---

## 一、审核范围与覆盖

| 区域 | 覆盖内容 | 方法 |
|---|---|---|
| 后端核心 | core/ 全部 46 文件（config/security/deps/database/middleware/auth 等）、main.py、start.py、api/v1/router.py | 逐文件精读 |
| 后端端点 | 372 条路由全量鉴权覆盖扫描；备份模块 36 条路由细粒度权限核验；auth/user/permission/monitoring 抽查 | 脚本扫描+精读 |
| 后端服务 | fifo_allocation、numbering_sequence、order_deduction_service、purchase_order_generate、stock_inventory_service（bandit 定位点）等核心逻辑 | 精读 |
| 前端 | 安全模式全库扫描（v-html/innerHTML/eval/localStorage/console）；5 个定时器文件清理核验；api/request.ts、router/index.ts、vite.config.ts | 扫描+精读 |
| 配置/部署/迁移 | .env 系列、config/、alembic 迁移链（77 版本）、deploy/restart 脚本、server_manager_config.json | 精读+扫描 |
| 自动化 | bandit：70,497 行，1 Medium+14 Low；Mimosa 深扫：397 发现、862 依赖包（离线 CVE 0 匹配）；npm audit：8 漏洞（全部 devDependencies） | 全库 |
| 依赖 CVE | pip-audit 扫描 requirements.txt 全量依赖：**No known vulnerabilities found**；npm audit 仅 devDependencies 8 项（见 M5） | 全库 |

---

## 二、问题明细

### 高风险（上线阻断级）

#### H1 【安全】真实生产凭据提交进 git 仓库，且数据库密码为 6 位弱密码
- 位置：`config/.env.production:9`（DB_PASSWORD，6 位纯数字）、`:22`（SECRET_KEY 实值）、`:28` 与 `:31-37`（REDIS_PASSWORD 及含密码的 REDIS_URL 连接串）
- 描述：根目录 `.env.production` 是安全的 `${VAR}` 占位模板，但 `config/.env.production` 是含**实值**的副本且被 git 追踪（`git ls-files` 确认）。仓库已推送远端（erp/main），任何有仓库访问权的人可获得生产 PostgreSQL、Redis 凭据与 SECRET_KEY。DB 密码仅 6 位数字可被瞬间爆破。文件本身在 .gitignore 忽略清单里（`.env.production` 模式），但"已追踪文件不受 gitignore 影响"导致继续入库。
- 修复：
  1. 立即轮换全部三项凭据（DB、Redis、SECRET_KEY——SECRET_KEY 轮换会使现有 JWT 全部失效，需安排在停机窗口）；
  2. `git rm --cached config/.env.production` 并提交；
  3. 用 `git filter-repo`/BFG 清理历史中的该文件（或至少确认远端仓库可见范围仅限内部）；
  4. DB 密码改为 20+ 位随机串（内网部署同样要求，本机即生产机，风险面更大）。

#### H2 【逻辑/配置】`.env` 的 ALLOWED_HOSTS 值格式错误，下次以生产模式重启将直接启动失败
- 位置：`.env:45`（`ALLOWED_HOSTS=["*"]`）；`fastapi_app/core/config.py:111`（逗号分隔解析）、`config.py:140-144`（生产校验）；`start.py:89`（`APP_ENV` setdefault "production"）
- 描述：`start.py --prod` 会设置 `APP_ENV=production`，此时 config.py:140 的生产强校验 `"*" in ALLOWED_HOSTS` 判定为真，抛 `RuntimeError` → 服务无法启动。而若 APP_ENV 未按 production 启动，则 docs 端点（`/api/docs`）保持开启且 TrustedHost 通配——两种结局都不可接受。当前服务能运行大概率是因为"校验逻辑上线后未重启过"，属于**下次重启必然触发的延迟引爆点**。
- 修复：`.env:45` 改为逗号分隔的具体主机名（内网直连场景如 `ALLOWED_HOSTS=localhost,127.0.0.1,192.168.x.x` 或实际访问用主机名）；改完在停机窗口用 `python start.py --prod --check` 做一次自检验证。

#### H3 【流程】核心功能改动未提交未固化，上线版本不可复现
- 位置：8 个已修改文件（`fastapi_app/services/bom_service.py`、`fastapi_app/shared_models/product.py`、`fastapi_app/schemas/purchase_center.py`、`fastapi_app/api/v1/endpoints/purchase_center/schemas.py`、`frontend-vite/src/views/product/components/BomEditor.vue`、`.../useProductListActions.ts`、设计文档、测试）+ 未提交迁移 `migrations/versions/pg_standalone_039_product_default_bom_label.py`
- 描述：BOM 角色字段功能横跨模型/迁移/前后端，处于半提交状态。若以此状态打包上线，产物与 git 历史不一致，出问题无法回溯；迁移 039 也可能漏执行。
- 修复：完成该功能的回归测试后提交推送；部署清单中明确包含 alembic 升级至 `pg_standalone_039` + 前端重新 build。

### 中风险（上线前应修复）

#### M1 【逻辑】请求级事务提交发生在响应发送之后，commit 失败时客户端已收到成功
- 位置：`fastapi_app/core/database.py:147-169`（`get_async_db` 在 yield 后统一 commit）
- 描述：FastAPI 0.106+ 依赖收尾在响应发出后执行。若 commit 失败（连接闪断、约束冲突），用户已看到"保存成功"，数据实际未落库，仅留日志。这是全局性的一致性/体验风险，尤其在备份恢复（rebuild_pool）窗口期。
- 修复（渐进）：① 对 commit 失败路径加 ERROR 级告警（当前仅 warning/raise，客户端无感知）；② 对资金/库存类关键写接口改为端点内显式提交后再返回；③ 部署后关注该日志的出现频率。

#### M2 【逻辑】出货写入不失效 FIFO 缓存，采购计划完成度最长 30 分钟显示过期
- 位置：`fastapi_app/services/fifo_allocation.py:36-37`（TTL 1800s）与 `:70-77`（缓存读取）；失效仅挂在采购计划变更路径 `fastapi_app/services/purchase_plan_common.py:50`
- 描述：`plan_fifo:{month}` 缓存只被计划侧写入失效；`stock_out_service` 等出货路径不清理。录完出货单后，FIFO 分配结果（已出货量/计划完成度）最长 30 分钟保持旧值。
- 修复：出货/退货落库后按相关计划月份调用 `_invalidate_fifo_cache(plan_month)`（月份可从受影响计划的 plan_month 得到；或改用版本号键）。

#### M3 【规范】APP_ENV 判断语义分散且互相矛盾
- 位置：`fastapi_app/core/config.py:46,89,127`（接受 `prod|production`）；`fastapi_app/core/middleware.py:102,127,196,261,307`、`api/v1/endpoints/auth.py`（仅 `== "production"`）；`fastapi_app/main.py:331`（`== "production"`）、`main.py:415`（仅 `== "prod"`）
- 描述：`python main.py` 直连启动且 `APP_ENV=production` 时，main.py:415 的 `== "prod"` 判断失败，默认绑定 `::`（全接口）而非设计的 127.0.0.1。同类不一致还会影响 CSRF secure、CSP 模式等开关的语义一致性。
- 修复：Settings 增加 `is_production` 属性，全库统一引用；消除裸 `os.getenv("APP_ENV")` 比较（可全局 grep 清零）。

#### M4 【安全】备份加密密码支持通过 URL query 参数传递，会落入访问日志
- 位置：`fastapi_app/api/v1/endpoints/backup/_deps.py:80-104`（`_get_encryption_password` 优先级 1 为请求参数 `password`）
- 描述：审计中间件不记录 query，但 uvicorn/nginx 访问日志默认记录完整 URL（含 query）。加密密码一旦走 query 参数会以明文进入日志文件（日志保留期内可读）。
- 修复：端点移除 query 形式的 `password` 参数，仅保留 `X-Backup-Password` 请求头与环境变量两种来源；发布说明中提示前端同步改法。

#### M5 【安全/依赖】npm 依赖 8 个漏洞（3 high），全部位于 devDependencies
- 位置：`frontend-vite/package.json` 依赖树（browserslist≤4.28.6 OOM/原型污染、fast-uri 3.0.0-3.1.5、js-yaml 4.0.0-4.3.1、vitest 2.x 链路径穿越等）
- 描述：全部经 dev 工具链引入，vite 生产构建产物不包含，上线运行时风险≈0；但属于工程卫生欠账，且 `npm ci` 环境的可信度受影响。
- 修复：上线后执行 `npm audit fix`（或最小化升级 browserslist/fast-uri/js-yaml）并在 CI 加 `npm audit --audit-level=high` 门禁。

### 低风险（建议排期，不阻断上线）

| # | 位置 | 问题与建议 |
|---|---|---|
| L1 | `core/deps.py:186-223` | 每请求最多 3 次 JWT 解码（`_resolve_user_id`→`_authenticate_user_id` 二次解码→`_resolve_token_jti` 三次）。复用首次 payload 即可，热路径性能小优化。 |
| L2 | `services/fifo_allocation.py:74` | 缓存脏数据时 `{int(k) for k in cached}` 抛未捕获 ValueError → 500。用 try/suppress 视为缓存未命中。 |
| L3 | `scripts/reset_admin_password.py:7` | docstring 示例含真实样式密码片段，Mimosa 误报为硬编码凭据；建议改为 `<your-password>` 占位。 |
| L4 | `docs/ui-redesign/_v2check.js:4` | `new Function()` 动态执行（原型校验工具，非生产代码）；建议文件名去掉 `_` 前缀移入 tools/ 并加注释，避免扫描器长期误报。 |
| L5 | services 多处（如 `daily_production_service.py:145,258`） | `float()` 用于 `Numeric(10,2)` 价格属展示层换算，当前可接受；长期建议金额求和路径迁移 Decimal。 |
| L6 | 全库 56 处 `#nosec` | 抽查核验均有真实理由（quote_table 白名单、常量片段+绑定参数），bandit 报的 `stock_inventory_service.py:683` B608 为误报；建议 CI 增加 nosec 总量阈值防滥用。 |
| L7 | `core/deps.py:72-73` | 权限缓存 TTL 5s / 用户状态 TTL 10s：禁用用户最长 10 秒后失效（设计取舍，需知悉）。 |
| L8 | `main.py:62`、`middleware.py` 等多处 `except: pass`（带 defensive 注释） | bandit 14 Low 主体；注释充分、影响面小，维持现状可接受。 |

### 自动化扫描误报澄清（已人工核验排除）
- bandit Medium（B608 `stock_inventory_service.py:683`）：pid_clause 为模块级常量片段，值经 `ANY(:pids)` 绑定参数，无注入。
- Mimosa HIGH `config/postgres/init-replica.sh:31`：实际为 `: "${POSTGRES_PASSWORD:?...}"` 强制环境变量注入，无硬编码。
- Mimosa HIGH `scripts/reset_admin_password.py:7`：docstring 示例文本，见 L3。
- `backup/export.py:174` 下载接口：`Path(filename).name` 等值校验 + 权限 + 审计，无路径穿越。

---

## 三、整体质量评估摘要

### 按维度统计（人工核验后的有效发现）

| 维度 | 高 | 中 | 低 | 说明 |
|---|---|---|---|---|
| 安全 | 1（H1，含弱密码） | 2（M4、M5） | 2（L3、L4） | 认证/CSRF/CSP/权限体系本身设计良好 |
| 逻辑缺陷 | 2（H2、H3） | 2（M1、M2） | 1（L2） | H2 属"延迟引爆"配置错误 |
| 性能与资源 | 0 | 0 | 2（L1、L5） | 未发现 N+1/泄漏级问题；池管理(LIFO/pre_ping)、超时保护到位 |
| 规范与可维护性 | 0 | 1（M3） | 3（L6、L7、L8） | 防御性注释、nosec 纪律、命名整体优良 |
| 合计 | **3** | **5** | **8** | |

### 分模块评价

- **认证与安全核心（core/auth、deps、security、middleware）**：优秀。Argon2id+旧哈希兼容、JWT 算法白名单+type claim+jti 黑名单（fail-closed 可选）、CSRF 双重提交+Origin 校验、CSP nonce+安全头。发现的问题集中在配置层而非实现层。
- **路由与权限**：优秀。372 条路由中除刻意公开的（login/logout/refresh/health/vitals 上报）外全部经 router 级登录鉴权；备份模块 36 条路由 100% 挂细粒度权限（read/create/restore/delete/manage）；用户/权限管理接口有 superuser 校验。
- **业务服务核心**：良好偏优。编号分配（原子 upsert 短事务，杜绝重号）、订单抵扣（`with_for_update` 行锁）、采购生成（唯一约束+幂等键+pending 清理三层防重）、FIFO（超时保护+纯函数+显式失败）均为教科书式实现。缺口为 M2 缓存失效。
- **备份域**：良好。路径穿越防护、fail-closed 加密、恢复前重建连接池（带锁）完备；主要风险是 M4 日志泄漏面。
- **前端**：优秀。XSS 攻击面≈0（v-html 仅 1 处且净化+常量校验）、token 不入 localStorage、定时器/监听器全部清理、401 单飞刷新+防重入、生产构建 drop console、路由守卫完整。
- **数据库迁移**：健康。77 版本单 head 无分叉；039 迁移幂等性依赖 alembic 版本表， downgrade 正常；无未备份的破坏性升级操作。
- **部署脚本**：干净。无凭据硬编码（仅文档行占位符）；restart_prod.ps1 有 `$ErrorActionPreference=Stop` 与 .env 加载。

### 测试与工程化观察
- 后端双测试树（fastapi_app/tests + 根 tests），核心算法（FIFO 纯函数、编号、备份 P0）有针对性测试；`test_bom_role.py` 覆盖当前 WIP 功能。
- 慢查询监听、Prometheus 指标、审计缓冲刷写、优雅关闭超时保护等运行时可观测性设施齐全。

---

## 四、上线前重点修复清单（按优先级排序）

> **状态更新 2026-09-12：清单已全部执行完毕**，逐项修复与验证记录见文末「修复执行记录」。

| 优先级 | 项 | 动作 | 预估工作量 |
|---|---|---|---|
| P0（阻断） | H2 ALLOWED_HOSTS 格式 | 改 `.env:45` 为逗号分隔主机名；`python start.py --prod --check` 验证后重启 | 10 分钟 |
| P0（阻断） | H1 凭据入库 | 轮换 DB/Redis/SECRET_KEY → `git rm --cached config/.env.production` → 提交 → 历史清理决策 | 0.5 天（含停机窗口） |
| P0（流程） | H3 未提交改动 | 完成 BOM 角色回归 → 提交推送 → 部署含迁移 039 + 前端 build | 按回归进度 |
| P1（应修） | M1 commit 后置 | 加 commit 失败告警；关键写接口评估显式提交 | 0.5 天 |
| P1（应修） | M2 FIFO 缓存失效 | 出货/退货路径补 `_invalidate_fifo_cache` | 2 小时 |
| P1（应修） | M4 加密密码走 query | 端点移除 password query 参数，保留 Header/环境变量；前端同步 | 1-2 小时 |
| P2（建议） | M3 APP_ENV 统一 | Settings.is_production 属性 + 全库替换 | 2 小时 |
| P2（建议） | M5 npm 漏洞 | `npm audit fix` + CI 门禁 | 1 小时 |
| P3（排期） | L1-L8 | 见低风险明细表 | 各 0.5-2 小时 |

**结论**：代码实现层的工程质量显著高于同规模 ERP 项目的平均水平，安全架构（认证/权限/CSRF/CSP）与并发正确性（锁/幂等/原子序号）经得起检验。真正会出事的三个点全部在**配置与发布流程**层：弱密码凭据已入 git、ALLOWED_HOSTS 格式错误将在下次重启引爆、工作区未固化。修完 P0 三项即可具备上线条件。

---

## 五、修复执行记录（2026-09-11/12，全部完成）

| 项 | 修复内容 | 验证方式 | 结果 |
|---|---|---|---|
| H2 | `.env:45` 改为 JSON 数组格式真实主机名（localhost/127.0.0.1/::1/192.168.0.95/DESKTOP-11111） | `APP_ENV=production` 下实例化 Settings + `start.py --prod --check` | ✅ 生产校验通过、docs 关闭 |
| H1 | ① PostgreSQL 四角色轮换（erp_app/postgres/erp_readonly/replicator，旧 110110 弱密码）② 从库 `ALTER SYSTEM SET primary_conninfo` + reload + walsender 重连 ③ Redis 双实例 runtime CONFIG SET + NSSM 注册表参数 + 服务重启 ④ SECRET_KEY 轮换（ES256 下零会话影响）⑤ 15 个含凭据文件脱敏/改环境变量注入，`.env.development`+`config/.env.production` 退出版本库 ⑥ 陈旧 rediserp 服务降为手动启动 ⑦ 后端+ARQ 以新凭据重启 | psycopg 新密码回验；redis-cli PING（新过/旧拒）；`pg_stat_replication=streaming`；`/api/health` 200；git grep 六组旧凭据零残留 | ✅ 提交 6164a72（已推送） |
| H3 | BOM 角色功能 8 文件 + 迁移 039 提交推送；前端 build | `test_bom_role.py` 21 passed；`npm run build` 22.95s 含类型检查 | ✅ 提交 f3838b3（已推送） |
| M1 | `get_async_db`/`get_async_db_context` 拆分 yield 与 commit：commit 失败记 ERROR 告警（响应已发、数据未落的静默丢失风险显性化） | pytest -k database/session：7 passed | ✅ |
| M2 | 新增 SQLAlchemy 会话事件集中钩子（fifo_allocation.py）：before_commit 检测 StockOut 变更 → after_commit 全清 `plan_fifo:*`（Redis PATTERN + 本地 L1）。覆盖出货/退货/修改/删除/批量导入全部现在与未来写路径 | pytest -k fifo/purchase_plan：39 passed | ✅ |
| M4 | `validation.py GET /validate/{filename}` 移除 Query 密码（改 X-Backup-Password 头）；/save 与 _deps docstring 同步更正；全库 grep 确认无 Query 形式密码；前端本就不经 URL 传密码 | pytest -k backup：115 passed | ✅ |
| M3 | `Settings.is_production` 动态 property（兼容测试 monkeypatch）；middleware×6、main×2、health×1 统一替换；main.py:415 `=="prod"` 漏判修复 | pytest -k security/middleware/health/config：78 passed | ✅ |
| M5 | `npm audit fix`：8→3；剩余 3 项全部为 vitest 工具链（dev-only，需跨大版本 2→4），记为上线后处理 | `npm audit`；`npm run build` 成功 | ✅（3 项记录在案） |
| L1 | deps.py 单次解码：`_resolve_*` 暂存 payload 至 request.state，`_authenticate_user_id` 复用（每请求 3 次解码→1 次） | pytest -k auth/deps/token：通过 | ✅ |
| L2 | FIFO 缓存脏键 int() 转换 try/except → 视为未命中并清除 | fifo 测试通过 | ✅ |
| L3 | reset_admin_password.py docstring 示例改 `<your-strong-password>` 占位 | — | ✅ |
| L4 | `_v2check.js` 重写为纯静态检查（去除 new Function 动态执行，Mimosa 高危清零）迁至 `docs/ui-redesign/tools/prototype_check.js` | 写入经 Mimosa 钩子通过 | ✅ |
| L6 | 新增 `scripts/check_nosec_budget.py`（预算 70，生产代码口径 70/70），可接入 CI 门禁 | 运行 OK | ✅ |
| L7 | deps.py 两处 TTL 文档值修正（30s→10s、10s→5s 实际值对齐） | — | ✅ |
| L5 | **豁免**：float() 仅用于 Numeric(10,2) 展示层换算，上线前不做 Decimal 重构（回归风险>收益） | 评估记录 | 维持现状 |
| L8 | **豁免**：防御性 except:pass 均带理由注释、影响面小，维持现状 | bandit 14 Low 复核 | 维持现状 |

**遗留用户决策项**：
1. **git 历史清理**（H1）：旧凭据仍在历史提交中。轮换已使旧凭据全部失效，风险已消除；如需彻底抹除历史，用 `git filter-repo`/BFG 清理后 force-push（会改写全部提交哈希，需协调所有克隆）。
2. **NSSM Redis 服务**：本轮以手动进程承接、注册表参数已更新为新密码；**下次整机重启**后 NSSM 服务将以新参数自动接管（或手动 `net start erp-redis` 验证）。
3. **vitest 大版本升级**（M5 余量 3 个 moderate，dev-only）：上线后执行。

---

*附：自动化扫描原始产物 — `temp/prelaunch_bandit.txt`、`temp/prelaunch_npm_audit.json`、`temp/prelaunch_pip_audit.txt`（结论：No known vulnerabilities found）、Mimosa 封印报告 `~/.mimosa/security-scans/project-2d23cc09849589f81d4aaf4e/scan-2026-09-11T15-15-46.316Z-4eadc7171319/`（seal: sha256:f057ed…45d7315）。Mimosa 离线库 862 包 0 匹配，与 pip-audit 结果互相印证。*

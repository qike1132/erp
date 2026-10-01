# 优化方案审计报告——问题真实性验证与方案修订

- **审计对象**：`docs/optimization-plan-2026-10-01.md`（OPT-01~22）
- **审计日期**：2026-10-01
- **审计方法**：不采信任何转述，全部用"打开文件读行 / 独立重跑命令 / 只读查库 / 查注册表"级证据复核；按 BLOCKER / SUGGESTION / NIT 分级。
- **审计边界**：只读，未修改任何业务代码与服务。

---

## 0. 审计结论 TL;DR

**问题大多真实存在（22 项中 14 项属实），但方案不是万无一失：4 项需要修正方向，其中 3 项是 BLOCKER 级——直接照原方案执行会出错或撞车。** 同时有 1 个关键好消息：OPT-08（venv 隔离）最危险的前提"requirements 是否完整"已验证通过。

| 判定 | 数量 | 项 |
|---|---|---|
| ✅ 问题属实、方案可行 | 12 | OPT-01*、02*、03、04、05、06、07、08、12*、13、17、18、21、22（*带数字/表述修正） |
| ⚠️ 问题属实但程度/数字偏差 | 5 | OPT-09（被低估）、OPT-19（风险被高估）、OPT-11（被高估）、OPT-20（大半不成立）、OPT-16（认知过时） |
| ❌ 方案本身有错，必须改 | 3 | **OPT-14（命令不可行）、OPT-15（前提过时）、OPT-10（方向错误）** |
| 🔴 BLOCKER | 3 | OPT-14、OPT-16、OPT-10（见 §2） |

**方法论教训（写给我们自己）**：第一轮评估的 5 处"端点事务违规"有 4 处是把 **docstring 注释**当成了违规代码；"usePagedSearch 10 处引用"实测业务引用为 **0**。转述型探查会产出"看似有据"的误报——本次审计 100% 以逐行实证推翻或确认，今后凡写入方案的行号必须先读文件。

---

## 1. 逐项验证矩阵

| OPT | 声称的问题 | 判定 | 关键证据 | 方案处置 |
|---|---|---|---|---|
| 01 | 22 个 WIP 未提交 | 属实，数字偏差 | `git status --porcelain` 实际 24 行（docs/outsource/ 折叠）；mockups/ 已跟踪 21 文件、新 html 未跟踪；components.d.ts 已跟踪 | 拆 4 提交微调：docs/outsource 3 文件并入外发提交，mockup html 并入客户订单提交 |
| 02 | 6 个 pytest 失败 | 属实，诊断已完成 | **孤立复现 46 过 / 1 败**：`test_database.py::TestBatchInsert::test_insert_100_products` 孤立仍败（测试库残留 product 数据撞 `product_name_key` 唯一键）——1 个真实测试隔离缺陷；其余 5 个确认为顺序污染 | 方案有效且省一步：直接修测试库清理夹具；非业务 bug，但也不是"环境噪音" |
| 03 | ruff 145 错 / 78 可自动修 | 精确属实 | `--statistics` 复核：145 errors、78 fixable，Top 规则一致 | 不变 |
| 04 | useListQuery、api/v2 死代码 | 属实 | grep 全仓 0 引用（仅自身定义）；api/v2 无 .py、全仓无 api.v2 导入 | 不变 |
| 05 | git-bash `_lc` 劫持 | 属实 | 本次审计期间再次实时干扰 ruff/pytest 调用（exit 127） | 不变，优先级提高 |
| 06 | 根目录草稿堆积 | 属实 | `_qa_tmp/`、`_ops/audit_scratch/` 等未跟踪草稿存在 | 不变 |
| 07 | web_vital 4,147 条未分析 | 属实 | DB 只读实测 | 不变 |
| 08 | 生产跑全局 Python | **属实且前提已证** | 注册表实证：erp-prod/erp-arq 的 Application = `...\Python313\python.EXE`（全局）；**requirements 完整性差集 = 0**（95 个顶层第三方包全部有声明，PIL/dotenv/cv2/botocore 假阳性已排除）；test.txt 含全部 pytest 插件 | 方案成立，补 2 条注意事项（见 §3-S1） |
| 09 | 66 个 view 直呼 @/api | **属实且被低估** | 实测 **113-123 个文件** import @/api；其中**写类调用 27 个文件**（API 层为对象导出，按 `Api.post/put/delete...` 方法统计）；useApiMutation 仅 4 处、直用 useMutation 1 处、eslint 无禁入规则——全部属实 | 优先做 27 个写类文件；查询类直呼属 vue-query 合理模式，不强制迁移 |
| 10 | 三套列表 composable 并存（usePagedSearch×10） | **方向错误** | CustomerTable 247 / SupplierTable 285、均不用 UiDataTable——属实；但 **usePagedSearch 业务引用 = 0**（3 文件=定义+2 测试）、useEnhancedList 业务引用 = **1**（ProductTable） | 重做：不是"收敛到 usePagedSearch"，而是①删两套基本死代码 ②先调研 113 个文件实际的列表模式再定统一目标 |
| 11 | 5 处端点内事务违规 | **大部不成立** | 仅 `order.py:335-405` delete_order 属实（:364 `await db.commit()`、:382 post-commit、:388 publish_domain_event）；customer.py:114/302 与 purchase_plan.py:112/529 是 **docstring**；auxiliary.py:275/288 是 `commit=False`；order_routes.py:98 是 `_auto_commit=False`——4 文件 5 处全部误报 | 缩为 1 处，工作量 2-3d → **0.5d** |
| 12 | config 静默降级不加密 | 部分属实 | `@field_validator`=0 属实；但"静默"不成立：`crypto.py:57-69` 有 warning 日志、`config.py:211-225` 启动即校验告警 | 保留，表述改为"告警不阻断 → 改阻断（fail-fast）" |
| 13 | mypy 覆盖 106/536 | 属实（小偏差） | mypy.ini 显式列表实测 106 条 ✓；services 84 非 82；536 口径含 tests | 不变 |
| 14 | 迁移 4 根，用 alembic merge 修复 | **问题属实、方案不可行** | AST 实测：4 根 ✓、唯一 head ✓、**99/99 文件全部收敛到唯一 head** → merge 只能合并并行 head，此处无对象；同号 017 实为 **3 个**非 2 个 | 🔴 BLOCKER：删除修复动作，降级为"ADR 文档说明，勿动" |
| 15 | echarts 仅报表页用，可动态加载 | **前提不成立** | echarts 被 **7 个文件**引用：dashboard 图表区、production 趋势、login 预载等；且动态 import 封装**已存在**（`utils/echartsPreload.ts` 的 ensureEcharts/preloadEcharts） | 重做：真问题是 **manualChunks 把 echarts 静态归入共享 vendor chunk，使既有动态加载失效**——先跑 visualizer 验证，再从 manualChunks 移除 echarts 规则 |
| 16 | PG 无从库，整机单点 | **认知需修正** | **主机存在 `postgresql-replica` 与 `postgresql-x64-18` 两个 Windows 服务**；`replicator` 角色（rolreplication=true）；主库有持久 walreceiver 连接（client_addr/state 全空、unix-socket 本地连接特征）；但 replication_slots=0、无 streaming 状态行 → **半成品副本，未在流式工作** | 🔴 BLOCKER：从"从零部署"改为"先盘点半成品"——查该服务的数据目录/启动参数/失败原因，确认无人依赖后再决定续建或拆除 |
| 17 | 无 TLS | 属实 | nginx 仅 listen 3000，grep ssl = 0 | 不变 |
| 18 | 无 limit_req | 属实 | grep limit_req = 0 | 不变 |
| 19 | uploads 免鉴权直出 | 属实，风险高估 | nginx alias 直出属实（main.py:404/408/412 后端挂载）；但落盘名 = `日期/uuid4.hex`（`storage_service.py:165`）**不可枚举**——实际风险是"链接被分享泄露"，不是"扫描枚举" | 降级：移到 P2 末位，或并入"可选加固" |
| 20 | 进程内状态阻碍多实例 | **大半不成立** | WS 票据虽写内存（ws.py:41,54）但**同时写 Redis，且读路径内存 miss 后回退 Redis（ws.py:64-73）→ 多实例安全**；权限 L1 缓存广播默认关属实（`core/cache.py:56`，env 默认空），但 ttl 仅 **5 秒**，多实例下最多 5s 权限陈旧 | 降级：撤销 WS 票据子项；L1 广播并入"双实例检查清单"；真正阻碍只剩本地文件存储（uploads/files/releases） |
| 21 | fastapi 0.137.1 落后 | 属实 | requirements pin 实证；PyPI 最新 0.142.2 | 不变 |
| 22 | 备份演练缺解密验证 | 属实 | `scripts/restore_drill.py` 全文 56 行：仅 ZipFile+restore，**无解密、无校验和**；`_constants.py:41-42` 有 2026-08-23 事故注释（"随机密钥无人能找回，曾产出永久不可还原的 .zip"） | 不变 |

---

## 2. BLOCKER 详述（原方案照做会出错的三处）

### B1 · OPT-14 的 `alembic merge` 命令不可行 🔴

`alembic merge` 只能合并**并行的多个 head**；AST 实测 4 个根的全部 99 个迁移**已经收敛到唯一 head** `pg_standalone_060_fix_updated_at_varchar_columns`——图是连通的，merge 无对象，命令会直接报错。更危险的是，若有人据此升级为"重建基线/squash"，会破坏所有已应用环境的 `alembic_version` 表，导致 drill/生产环境无法 upgrade。
**修订**：从优化计划中**删除修复动作**；改为在 `docs/adr/` 记录一条决策："4 根为历史外观问题，图已单 head 收敛，任何人不做修改"。同号 017（实为 3 个）同样只记录不改名。

### B2 · OPT-16 假设"从零部署"，实际是"接手半成品" 🔴

原方案：备机 docker 起副本/同机建第二实例。实测：主机已有 `postgresql-replica` Windows 服务、`replicator` 复制角色、一个持久的 walreceiver 连接（无复制槽、无 streaming 状态）。**存在一个未完成且状态未知的副本环境**——可能是某人排障中的工作现场。原方案任何"清理残留/初始化"动作都可能破坏它。
**修订**：OPT-16 增加强制前置步骤：① 查 `postgresql-replica` 服务配置（数据目录、启动参数、依赖）；② 查其错误日志确认失败原因；③ 与团队确认归属（是否有人在管）；④ 之后再选择"续建收尾"或"拆除重来"。该前置调查本身列为 P0 末尾的**只读调查项**（OPT-16a，0.5d）。

### B3 · OPT-10 的收敛方向建立在错误统计上 🔴

原方案："usePagedSearch 用得最多（10 处），把其余两套迁过去"。实测：usePagedSearch **业务引用 0**、useEnhancedList **1 处**——按原方案执行等于"把 1 个使用者迁到一个 0 使用者上"，两套照旧死代码，真正的 113 个文件的列表模式未被触及。
**修订**：① 直接删除 useListQuery（原 OPT-04）+ usePagedSearch（保留其测试一并删）；② useEnhancedList 待 ProductTable 迁移后删；③ UiDataTable 迁移照做（CustomerTable/SupplierTable 属实）；④ 新增 0.5d 调研：统计 113 个文件的列表实现模式分布，再决定是否值得立"统一列表层"专项——很可能结论是"vue-query 直用已是事实标准，只需文档化约定"。

---

## 3. SUGGESTION（应修正）

- **S1 · OPT-08 venv 的两条补充**：① 确认所有启动入口——`start.py`、`server_manager`（PyInstaller 入口）、`.githooks` 里兜底的 python 绝对路径，切换 venv 后都要检查；② `requirements/test.txt` 的 pytest 插件必须装进 venv，否则验收步骤"venv 内 pytest 全绿"无从执行。建议 OPT-08 与 OPT-21（fastapi 升级）合并到同一个低峰窗口，一次重启完成两件事。
- **S2 · OPT-15 的正确切入点**：echartsPreload 动态加载已存在，而 vendor-echarts 557KB 仍常驻——最大嫌疑是 `vite.config.ts` 的 manualChunks 把 echarts 强制归入共享 chunk，使动态 import 失效。先跑 visualizer 确认，再只改 manualChunks 一行级规则，收益可能即 557KB。
- **S3 · OPT-09 的范围口径**：迁移对象是"27 个含写类调用的文件"，不是 113 个；查询类保持 vue-query 直用（这是合理模式），只在 decisions/ 文档化约定 + 加 warn 级 eslint 规则防劣化。
- **S4 · OPT-02 直接进入修复**：孤立复现已完成，失败根因已定位（测试库 product 残留 + 顺序污染），无需再走方案的"先诊断"步骤，预计 0.5d 内完成。

## 4. NIT（表述修正）

- OPT-01：WIP 实际 24 行（展开 26 文件）；mockups/ 目录是既有跟踪惯例（已有 21 个文件），新 mockup html 应随对应功能提交，不是"杂项"。
- OPT-12：问题表述由"静默降级"改为"有告警但不阻断"。
- OPT-19：风险表述加"文件名 uuid4 不可枚举，风险面为链接分享泄露"。
- OPT-20：删除"WS 票据"子项；补充"本地文件存储是多实例的唯一实质阻碍"。

## 5. 值得表扬的发现（审计中的正面证据）

- customer.py / purchase_plan.py 等端点的 **docstring 明确声明事务模式**（"commit/rollback 由 db_transaction 统一执行"）——纪律本身是好的，也正因如此误报能被快速证伪。
- `ws.py` 的票据设计（Redis 权威 + 内存加速 + miss 回退）**本来就是多实例友好的**，第一轮评估低估了它。
- requirements 的完整性（95 个顶层包零缺失声明）在无 venv 的环境下维持住了——依赖纪律好。
- `storage_service.py` 的 uuid4 落盘命名使上传 URL 不可枚举。

## 6. 修订后的计划影响

| 项 | 原估 | 修订后 | 变化 |
|---|---|---|---|
| OPT-11 | 2-3d | 0.5d | 5 处 → 1 处 |
| OPT-10 | 2-3d | 1d + 0.5d 调研 | 删死代码为主，迁移照做 |
| OPT-14 | 1d | 0.2d（仅 ADR 文档） | 删除修复动作 |
| OPT-15 | 1-2d | 0.5-1d | 聚焦 manualChunks 一处 |
| OPT-09 | 4-6d | 3-5d | 27 个写类文件优先 |
| OPT-19/20 | 2d/1-2d | 可选/并入检查清单 | 降级 |
| OPT-16 | 2-3d | +0.5d 前置调查（OPT-16a，提为 P0） | 接手半成品，不从零开始 |
| **P1 合计** | 15-22d | **约 10-14d** | ↓ |
| **P2 合计** | 8-10d | **约 6-8d** | ↓ |

P0 七项全部经审计站得住（OPT-02 的诊断还提前完成了），可立即执行。

## 7. 审计方法与局限

- 证据类型：逐行读文件（带行号引用）、独立重跑（ruff --statistics、pytest 孤立复现、grep 计数）、只读 SQL（pg_stat_replication/pg_stat_activity/pg_roles）、Windows 注册表（NSSM 服务指向、服务枚举）、AST 脚本（迁移图可达性）。
- 局限：`postgresql-replica` 服务的内部状态（数据目录、日志）未深入——它本身就是 OPT-16a 的前置调查对象；`postgresql-x64-18` 的 hba 文件因权限未读取（erp_app 无 pg_read_all_settings）。
- 本审计未修改任何文件（除本报告与临时验证脚本于系统 Temp 目录）。

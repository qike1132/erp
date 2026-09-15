# ITER-3 · 全球开源 ERP 对标与架构重构路线图

> 完整版（含五维对比矩阵、Gap 热力图、许可证边界）：`.workbuddy/artifacts/erp-benchmark-and-roadmap.html`
> 本文为决策记录（ADR 风格浓缩版）。

- **日期**：2026-09-14
- **范围**：`fastapi_app`（89,762 行）+ `frontend-vite`（63,348 行）
- **决策输入**：技术栈 = FastAPI + Vue3/Vite7 + Tkinter；痛点 = 性能 / 后端分层与 API 契约 / 前端架构与组件化 / 代码质量与测试文档（全选）；改造力度 = **允许大重构**；抄代码边界 = 以"功能成功、后端逻辑正确"为准
- **状态**：待执行

---

## 0. 必须先处理（Severe，0 行代码）

**5002 当前是 dev 单进程模式，ARQ 定时任务完全未运行。**

实测（2026-09-14 08:34）：

| 证据 | 值 |
|---|---|
| 监听 `0.0.0.0:5002` 的进程 | PID 16708，启动于 `2026-09-13 15:17:59` |
| 其 cmdline | `python.EXE -u -m uvicorn fastapi_app.main:app --host 0.0.0.0 --port 5002 --log-level info --reload --reload-dir fastapi_app` |
| 判定 | 含 `--reload`、**无** `--workers` → **dev 单 worker** |
| 全机进程扫描 | 无 `prod_runner` / `nssm` / ARQ worker 进程 |
| `logs/prod_runner.json` | 记录 backend pid=**9232**（已不存在），mtime 停在 `2026-09-12 08:53`，其中 `workers: 4` 为失效声明 |

**后果**：并发能力仅设计值 1/4；备份/告警等 ARQ 定时任务全部不执行（**数据安全事件，非性能问题**）；`--reload` 附带文件监控开销。

**处置**：恢复 `erp-prod`（NSSM）托管，确认进程链为 `services.exe → nssm → prod_runner → uvicorn(--workers 4)` 且 ARQ 在跑。需人工执行（沙箱非提权）。

---

## 1. 决策：重构策略采用「骨架级重排 + 按域割接」，不采用停机重写

**理由**：生产机 192.168.0.95 跑着真实业务，沙箱无提权、启停需人工。允许"大重构"不等于要停机。每个阶段可独立上线、可回滚。

**铁律：重构不改行为。** 先用测试固化现有行为，再等价改写。禁止趁重构顺手改业务逻辑。

**支持性事实**（这不是"屎山"，是"长太快、边界没跟上"）：
- 前端类型化纪律优秀：`defineProps<T>` 197 处 / 运行时 props 0 处 / `@ts-ignore` 0 处 / 显式 `any` 仅 3 处
- 数据获取已收敛 TanStack vue-query（60+ 文件）、请求层有单飞刷新与 GET 去重、路由全懒加载、manualChunks 已手工分包
- 后端 eager loading 196 处、连接池按环境动态计算 + `pool_pre_ping`、读写分离双引擎
- 后端测试 1,146 用例 / service 层覆盖 69%

**真正的病灶是边界缺失**：`services/` 内跨服务顶层 import **229 处**（69 个目标模块），而 `services/` 内 `Depends(` = **0**（`core/container.py` 已建但没人用）。

---

## 2. 参考清单（GitHub API 实时取数，2026-09-14）

| 项目 | Star | 许可证 | 可抄性 |
|---|---:|---|---|
| odoo/odoo | 54,320 | LGPL-3.0 | 只借语义（权限双层、addons 组织） |
| frappe/erpnext | 39,167 | GPL-3.0 | 只借语义（**Document 状态机**、台账汇总表） |
| YunaiV/ruoyi-vue-pro | 39,247 | **MIT** | **可直抄**（统一响应/分页/异常、前端 useTable） |
| nocobase/nocobase | 24,185 | AGPL-3.0 | 谨慎（元数据驱动，牺牲类型安全） |
| aureuserp/aureuserp | 11,907 | **MIT** | 可直抄（域目录组织） |
| Dolibarr/dolibarr | 7,601 | GPL-3.0 | 只借语义（模块目录 checklist） |
| ever-co/ever-gauzy | 5,047 | AGPL-3.0 | 只借语义（Clean Architecture 分层命名） |
| metasfresh/metasfresh | 2,421 | 无 SPDX | **不建议抄** |
| tryton/tryton | 221※ | GPL-3.0 | 只借语义（模块显式依赖宣言，代码质量范本） |

※ GitHub 仅镜像，主库在 code.tryton.org，星数不具代表性。

**技术栈同构补充（真正可直抄的三个，全 MIT）**：

| 项目 | Star | 用途 |
|---|---:|---|
| fastapi/full-stack-fastapi-template | 45,539 | `Depends` 注入 / 泛型 CRUD / CI / Playwright e2e |
| vbenjs/vue-vben-admin | 33,436 | schema 驱动表单 / 请求层 / 表格封装 |
| frappe/frappe | 10,745 | **Document 生命周期钩子 / 查询构建器 / `@redis_cache`**（注意：框架本体 MIT，ERPNext 本体 GPL） |

### 许可证判定
GPL/AGPL 的传染义务只在「分发」时触发，本地自用不分发 → 法律风险≈0。
**但仍建议分栏执行**：MIT 直接复制；GPL/AGPL 只抄语义。理由是成本不对称——将来若要交付同行/客户，GPL 系代码是必须返工的负债，而"抄语义"成本几乎为零。

---

## 3. 最该抄的三条主线（按本地自用场景裁剪）

高 Star 项目约 65% 的工程投入（多租户 / SaaS 计费 / 插件市场 / 水平扩展 / 灰度升级）对本地自用**收益≈0**，抄了只会背上抽象复杂度。

| 优先 | 主线 | 为什么 |
|---|---|---|
| ① | **数据一致性**：单据状态机 + 事务边界 + 反冲机制 | 已因此吃亏（P0-02 `shipped_qty` 静默不一致） |
| ② | **单机性能**：批量写 / 消灭 N+1 / 汇总表 | 单机场景下唯一决定"卡不卡"的三件事 |
| ③ | **单人可维护性**：组件复用 / 类型 / 契约测试 / 显式边界 | 一人维护 15 万行，决定项目还能活几年 |

---

## 4. 分阶段路线图

### P0（0–2 周）止血与建基线 · 零业务风险
1. **恢复 prod 运行模式**（见 §0）
2. 加 `pyproject.toml` + 依赖锁，统一 ruff/mypy 配置入口（当前无 `pyproject.toml`）
3. **OpenAPI 契约落盘入仓 + CI diff 断言**（当前 0 个契约文件 → 已踩过"后端改字段、前端静默空白"）
4. **打性能基线**：开 `pg_stat_statements` 抓 TOP30 慢 SQL；20 个高频接口记 P50/P95
5. 根目录 39 个 `_*.py`/`_*.txt`/`_*.log` 归档至 `scripts/legacy/`

**验收**：进程链确认为 nssm→prod_runner→uvicorn(--workers 4) 且 ARQ 在跑；契约入 CI 并能拦截改动；输出慢 SQL TOP30 + 接口基线表。

### P1（2–6 周）后端骨架重排
1. `ApiResponse[T]` / `PageResult[T]` / `BizError` 异常树 + 全局异常处理器（**先加，不动旧返回**，按域灰度）
2. 扩展 `core/container.py`：`get_xxx_service()` 全覆盖，替换 229 处顶层 import（目标 ≤30）
3. 工作单元：事务边界收回 service 层，API 层 6 处 `commit()` 归零
4. `shared_models/` → `models/`（旧路径保留 re-export，不停机）
5. services 按域切子包 + Facade `__all__`（9/172 → 覆盖全部对外入口）

**验收**：跨服务 import ≤30；API 层 0 处 DB 操作；371 个 endpoint 响应体契约唯一；全量 pytest 无新增失败。

### P2（与 P1 并行，2–6 周）前端去重复
1. `useErpForm(schema)` 统一表单与校验（抄 vben schema 思路）
2. `UiDialog`/`UiDataTable`/`UiFilterBar` 强制复用：39/13/9 → ≤3/≤2/≤3
3. 令牌化：1,468 处 hex → 令牌（脚本半自动 + 人工复核）
4. store 边界重划：72 个视图级 composable 中的共享态上移至 12–15 个域 store
5. `AbortController` 透传 axios → vue-query（当前 0 处）
6. 全局 loading / 骨架屏三级编排（当前 0 处）

**验收**：自写弹窗/表格 ≤3；硬编码 hex ≤150；`vue-tsc -b` 与 vitest 全绿；关键页 E2E 截图与改造前 1:1 核对。

### P3（6–12 周）性能与一致性 · 收益最大、风险最高
1. 批量导入：182 处 `.add()` → `executemany` + `ON CONFLICT DO NOTHING`（含 ITER-2 遗留的 conflict note）
2. N+1 清除：145 处候选逐点确认 → eager loading / 循环外批量取
3. 汇总表：BOM 用量 / 库存余额 / 采购汇总由实时聚合改增量维护 + **全量重算入口**
4. `@redis_cached(key, ttl, group)` 统一 91 处手动缓存，失效按组
5. **`DocumentMixin` 状态机**：出货/采购/生产单据统一 草稿→提交→取消（不可逆 + 反冲钩子）

**验收**：5,000 行导入耗时对齐 P0 基线显著下降；慢 SQL TOP30 清零 ≥80%；汇总类接口 P95 进目标；状态机覆盖 ≥3 类单据且反冲用例全绿。

### P4（持续）质量闸门
1. 类型注解 32.7% → ≥70%（mypy 渐进：新代码 strict，存量按域回补）
2. `except Exception` 234 → ≤60（保留最外层兜底）
3. 测试金字塔：service 单测（已有基础）→ 补 API 契约测试 + Playwright e2e 8 条主流程
4. CI 门禁 ruff / mypy / vue-tsc **diff 零新增**
5. 大重构决策落 `docs/adr/`

### 顺序约束
- P0-4（性能基线）是 P3 的前置条件——没有基线，"提升多少"永远是猜
- P1 与 P2 无依赖，可并行（前后端不同仓）
- P1-1 必须按域灰度，每批 5–8 个路由文件前后端同批上线
- P3-5（状态机）最后做，依赖 P1 的事务边界与 P3-3 的汇总表能力

---

## 5. 量化基线（可复现）

| 指标 | 现状 | 目标 | 变化 |
|---|---:|---:|---:|
| services 跨服务顶层 import | 229 | ≤30 | −87% |
| API 层直接 DB 操作 / `commit()` | 14 / 6 | 0 / 0 | −100% |
| 全仓 `commit()` 分散度 | 40 处 / 3 层 | service 层唯一 | 边界唯一化 |
| 逐行 `.add()` vs 批量写 | 182 : 6 | ≤60 : ≥40 | 主流程全批量 |
| 疑似 N+1 | 145 | ≤30 | −79% |
| 类型注解覆盖 | 32.7% | ≥70% | +114% |
| `except Exception` | 234 | ≤60 | −74% |
| `import *` | 26 | 0 | −100% |
| 最大单体文件 | 1,353 行 | ≤400 行 | −70% |
| Facade `__all__` | 9 / 172 | 100% 对外入口 | 约定成型 |
| 前端自写弹窗/表格/筛选栏 | 39 / 13 / 9 | ≤3 / ≤2 / ≤3 | −92%/−85%/−67% |
| 硬编码 hex | 1,468 / 159 文件 | ≤150 | −90% |
| Pinia store | 5 / 678 行 | 12–15 个按域 | 边界明确 |
| `AbortController` | 0 | 100% 列表请求 | 全覆盖 |
| 前端单测 | 16 文件 / 116 用例 | ≥60 文件 | +275% |
| e2e | 0 | 8 条主流程 | 0 → 8 |
| 根目录临时物 | 39 | 0 | −100% |

**运行时性能（推算，需 P0 基线校准）**：
- 批量导入（数千行）：耗时 **−60%~−85%**（2.5×~6.6×）
- 命中 N+1 的接口：P95 **−30%~−60%**
- BOM/采购/库存汇总类接口：P95 **−50%~−90%**（随数据量增长差距扩大）
- 前端可交互时间：感知提升 > 实测提升，**−20%~−35%**（TTFB 基本不变）
- 深分页：**≈0**（无 `offset ≥ 1000` 使用，keyset 分页不必做）

**工程效率（推算）**：
- 新增一个业务域的文件数：**−40%~−50%**
- 改一次 UI 交互的改动点：39 处 → 1 处
- 根因定位时间：**−50%+**（234 处宽泛捕获收窄后）

---

## 6. 风险与坑

| 风险 | 规避 |
|---|---|
| 统一响应体打断前端（371 个 endpoint） | 按域灰度，先加兼容开关再切默认 |
| 静态门禁误判为回归 | ruff 在 HEAD 已有 **185** 个告警；全量 pytest 有 **12 项既有失败**（含 conftest event loop 污染）→ 门禁只按「diff 无新增」用，改前先 `git stash push -- <改动文件>` 取基线 |
| 汇总表导致账实不符 | **先写"全量重算"入口 + 只读对账脚本**，再上增量路径 |
| 状态机冲击存量数据 | 先做存量回填 + 双读校验（新老逻辑并行比对），无差异后再切 |
| 生产重启需人工 | 把重启清单写成脚本 + 人工确认；禁用 `nssm restart` 套短 timeout（优雅停止 >60s 会留孤儿进程） |
| 并行改动归属不明 | `core/backup_encryption.py`、`numbering_sequence.py` 等时间戳 00:06–00:37 的改动来源未确认，动手前先梳理 |
| 把"重构"做成"重写" | 铁律：重构不改行为；每阶段先用测试固化行为 |

---

## 7. 待用户决策

1. **P0-1（恢复 prod 模式）何时执行**——需要人工重启，是本报告最高性价比动作
2. P3-3 汇总表改造范围：仅 BOM 用量 / 或含库存余额与采购汇总（后者风险更高）
3. 是否接受在 P2 引入 vben 的 schema 思路自研 `useErpForm`（不引入其 monorepo）

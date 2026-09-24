# 全面工程审查报告 · fastapi_app 全库 + 未提交变更集

**日期**：2026-09-24
**工作流**：工作流 1 · 全面代码审查
**范围**：`D:\erp_system\fastapi_app`（479 个 `.py`）+ 130 个未提交变更文件
**参与成员**：⚠️ **本次调度 4 位成员（Cody / Archi / Tessa / Rex）全部因基础设施故障未能产出** —— 模型网关 502（`connect ECONNREFUSED 127.0.0.1:7863`），4 位成员在同一时刻以同一错误失败。**全部结论由主理人甄宇航自行取证完成，未代写任何成员产出。**

---

## 📌 TL;DR（执行摘要）

- **整体结论：生产运行态健康，但工作区存在一处「门禁回归 + 未验证变更」的组合风险，不建议直接提交发布。**
- 关键发现：前一会话执行「CI lint 门禁归零」（见未跟踪交付物 `p0-2-lint-gate-verify-20260923.html`）时，`ruff --fix` 触发 **RUF100 陷阱**，把全库 `# noqa: BLE001 - <理由>` 当作「未使用的 noqa」删除 —— 而这正是项目质量门禁 `check_bare_except.py` 要求的**审计豁免凭证**，导致 `quality_gate.py` **从 9 处回退到 11 处宽泛 except，门禁 FAIL**。
- 严重度分布：🔴严重 0 项 / 🟠高 1 项 / 🟡中 3 项 / 🟢低 3 项
- **阻塞 / 非阻塞**：🟠 高项（门禁红灯）**阻塞 CI 与发布**；其余为非阻塞。
- 好消息：扫荡的**机械正确性经 7 项独立验证全部通过**（ruff F821 零命中、载荷式导入顺序契约完好、导入烟测 IMPORT_OK、回归测试 28 passed、零断言放宽）。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟡 **有条件通过**（代码正确性通过；门禁与发布纪律不通过） |
| 阻塞项数量 | **1**（质量门禁 FAIL） |
| 关键行动项 | 6 条（P0×2 / P1×2 / P2×2） |
| 建议下一步 | 先修 6 处豁免标记 → 门禁转绿 → 提交入库 → 再重启后端（重启是这批改动首次被执行） |
| 生产运行态 | 前端 nginx+dist 生产托管 ✅ / 后端 `/api/health` healthy ✅ / ARQ `j_failed=0` ✅ |
| 未提交变更 | 130 文件（416+/398−）+ 3 个未跟踪交付物 + 1 个未跟踪运维脚本 |

---

## 🔍 审查发现（按严重度排序）

| # | 严重度 | 类别 | 文件:行 | 问题描述 | 证据 | 建议修复 |
|---|--------|------|---------|---------|------|---------|
| 1 | 🟠高 | 工程纪律 | `core/database.py:111,116`<br>`services/order/beile.py:232`<br>`services/outsource/_shipments.py:228,401`<br>`services/purchase_order_sku.py:86` | **6 处宽泛 except 的审计豁免标记被剥离**，质量门禁由 9 处回退至 11 处 → `quality_gate.py` FAIL | 见 §1 根因分析；`check_bare_except.py` 输出 11 处 / 5 文件 | 把 `# noqa: BLE001 - <理由>` 改为 `# defensive: <理由>`（门禁接受、RUF100 不再触碰） |
| 2 | 🟡中 | 发布风险 | `logs/prod_runner.json` + 进程表 | **130 文件未提交变更压在生产机工作区，且运行中的后端未加载它** | 后端 pid 8748 创建于 `2026-09-23 22:08:39`；源文件 mtime 为 `23:23:46–23:40:04`（晚 1h15m）；`_cmd_uvicorn` 无 `--reload` | 提交入库并在受控窗口重启；重启前先跑导入烟测 |
| 3 | 🟡中 | 运维安全 | `scripts/phase1_switch.ps1`（未跟踪） | 未入库的**破坏性运维脚本**：按端口 `Stop-Process -Force`（3000/5002）后启 NSSM 服务；未受仓库「零删除原语」纪律约束 | 脚本 L8–L17 | 纳入版本控制并评审，或明确 ignore + 加安全护栏 |
| 4 | 🟡中 | 交付物治理 | `deliverables/*-20260923.html` ×3（未跟踪） | 前一会话的 3 份验证报告未入库，证据链与代码脱节 | `git status` 显示 `??` | 一并提交，避免证据与代码版本错配 |
| 5 | 🟢低 | 架构债 | `services/backup/dump.py:158` 等 | 超长函数存量（门禁口径 **52 处**，与基线一致，非回归）；最严重 `restore_database_via_psql` 293 行 | `quality_gate.py` 输出；`_solid_scan.json` | 分批拆分，先动 top 5 |
| 6 | 🟢低 | 架构债 | `bom_service.py`(1011) / `recovery_test_service.py`(1355) 等 8 个文件 | 单文件 >800 行（门禁口径：前端巨型组件 7 处，与基线一致） | `_solid_scan.json` | 按领域拆包 |
| 7 | 🟢低 | 安全 | `stock_inventory_service.py:688` 等 | bandit 2 MEDIUM（B608 字符串拼接 SQL）+ 10 LOW（B110/B404/B603） | `_bandit.json`；**0 HIGH** | B608 已在 `ruff.toml`/`bandit.yaml` 登记豁免，维持现状 |

---

## §1 根因分析：质量门禁为何从 9 回退到 11（核心发现）

### 1.1 机理（已用受控实验证实）

项目 `ruff.toml`：

```toml
[lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "SIM", "C4", "S", "RUF"]   # ← 含 RUF，不含 BLE
```

`RUF100`（unused-noqa）在 `select` 中含 `RUF` 时即生效。而 `BLE001`（flake8-blind-except）**未启用**，于是 ruff 把 `# noqa: BLE001` 判定为「指向未启用规则的冗余指令」，并作为 **safe fix** 自动删除。

**受控实验**（`_qa_tmp/_ruf100_probe.py`，ruff 0.16.8，项目默认配置）：

```
_qa_tmp\_ruf100_probe.py:11:24: RUF100 [*] Unused `noqa` directive (non-enabled: `BLE001`)   ← 会被删
_qa_tmp\_ruf100_probe.py:16:5:  SIM105 ...                                                    ← S110 的 noqa 未被报
```

对照：`# noqa: S110 - <理由>` **未**被判冗余（S110 已启用且确实触发 → noqa 有用 → 保留）。这完美解释了为何 `# noqa: S101`（`core/database.py:105`）幸存、而 `# noqa: BLE001` 全数消失。

### 1.2 双重门禁的错配

| 门禁 | 工具 | 豁免凭证要求 |
|------|------|-------------|
| lint 门禁 | `ruff` | `noqa` 必须**指向已启用规则**，否则视为冗余并删除 |
| **质量门禁** | `scripts/check_bare_except.py` | 明确接受 `# defensive: <理由>` / `# broad-except: <理由>` / `noqa: <CODE> - <理由>` |

→ 前一阶段的「lint 归零」**只优化了第一个门禁，却摧毁了第二个门禁的凭证**。这正是该仓库既有的 `erp-ruff-gate-remediation` 技能所警告的第一个陷阱：「**RUF100 在受限 `--select` 下会删光全库 noqa**」。

### 1.3 账目核对（完全闭合）

`scripts/check_bare_except.py` 当前输出（11 处 / 5 文件）：

```
core\database.py (2)                    L111, L116        ← 失标记 +2
services\backup\records.py (5)          L612,651,663,677,681
services\order\beile.py (1)             L232              ← 失标记 +1
services\outsource\_shipments.py (2)    L228, L401        ← 失标记 +2
services\purchase_order_sku.py (1)      L86               ← 失标记 +1
```

- **−4**：`services/backup/records.py` 原有 9 处宽泛 except，其中 4 处被改写为 `contextlib.suppress(Exception)` → 不再构成 `ExceptHandler` → 违规消除（**这是真实改善**）
- **+6**：上述 4 个文件共 6 处 `except Exception:` 的 `# noqa: BLE001 - ` 前缀被剥离，只剩中文理由 → 门禁正则 `noqa:\s*[A-Z]+\d+\s*-\s*\S` 不再匹配 → 计为违规
- 净变化 `+2`：基线 9 → 当前 11 ✅ **与门禁报告完全一致**

### 1.4 现场证据

`fastapi_app/core/database.py:109-117`（当前工作区）：

```python
        try:
            await stale.dispose(close=False)
        except Exception:  # 旧 loop 引擎清理失败不应影响当前请求     ← 原为 "# noqa: BLE001 - 旧 loop 引擎..."
            logger.debug('旧事件循环引擎清理失败（已忽略）', exc_info=True)
        if stale_read is not None:
            try:
                await stale_read.dispose(close=False)
            except Exception:  # 同上，尽力而为                      ← 原为 "# noqa: BLE001 - 同上，尽力而为"
                logger.debug('旧事件循环只读引擎清理失败（已忽略）', exc_info=True)
```

### 1.5 修复建议（推荐方案）

**不要**原样恢复 `# noqa: BLE001 - <理由>` —— 下次 `ruff --fix` 会再次删除，形成循环。应改用门禁接受的、且 RUF100 不触碰的标记：

```python
except Exception:  # defensive: 旧 loop 引擎清理失败不应影响当前请求
```

根治层面二选一（建议同时做）：
1. 在 `ruff.toml` 增加 `lint.external = ["BLE001"]`，使 ruff 不再把 `# noqa: BLE001` 判为冗余；
2. 全库统一改用 `# defensive: <理由>` 作为宽泛 except 的唯一豁免语汇。

---

## §2 变更集机械正确性验证（7 项独立验证，全部通过）

| # | 验证项 | 方法 | 结果 |
|---|--------|------|------|
| 1 | **悬空引用（最硬判据）** | `ruff check --select F821`（undefined-name）全库 | ✅ `All checks passed!` —— **0 处未定义名称** |
| 2 | 全量 lint | `ruff check` 项目配置全库 | ✅ 0 违规 |
| 3 | 导入变动归类 | AST 解析 `git diff` 的 ± 导入行 | 43 文件有导入变动 = **22 个真删除（29 个名字）** + 21 个仅重排 |
| 4 | 语法完整性 | 逐文件 `ast.parse` | ✅ 0 语法错误 |
| 5 | **载荷式导入顺序契约** | 核对 `services/backup/__init__.py` | ✅ `from .restore import (...)` 仍在 `from .verify import *` 之后，顺序未变 |
| 6 | 该契约的守卫测试 | `pytest ...::TestSourceGuards::test_package_restore_lock_resolves_to_redis_version` | ✅ **PASSED**（0.34s） |
| 7 | 循环依赖 / 启动可用性 | 独立进程 `import fastapi_app.main` | ✅ **IMPORT_OK**，3.3s，`/api/health` 与 `/api/health/arq` 均已注册 |

**回归测试**（单文件运行，遵循 conftest event loop 污染约束）：

| 测试文件 | 结果 |
|---------|------|
| `fastapi_app/tests/test_backup_p0.py` | ✅ **20 passed** |
| `fastapi_app/tests/test_arq_worker_health.py` | ✅ **8 passed** |

### 2.1 方法学自我纠正（两次假阳性，均已排除）

诚实记录：本次审查中我的两个自建启发式各产生过假阳性，均通过更权威手段证伪，**未进入结论**：

- **v1 脚本**：未区分「重排」与「删除」，报 30/43 文件"危险" → 修正后 22 个真删除。
- **v2 脚本**：未建模「名字是否仍被其它作用域的导入绑定」，误报 `services/order/deduction.py:53`（`StockIn`）与 `tests/test_backup_m1.py:11`（`Path`）两处。实查 diff：两者被删的都是**函数内冗余局部导入**，模块级早已绑定 → **安全**。
- **`--select RUF100` 单跑**：该参数会**替换**整个规则集，使所有 noqa 都被判「non-enabled」，报出的 129 条是运行产物而非真实状态 → 已弃用，改用受控实验（§1.1）。

---

## §3 架构影响评估（由主理人代行，原调度成员失败）

**SOLID 硬上限（门禁权威口径）**

| 指标 | 值 | 判定 |
|------|-----|------|
| 后端超长函数 | 52 处 | ✅ 与基线一致（非回归） |
| 前端巨型 Vue 组件 | 7 处 | ✅ 与基线一致 |
| service 层手动 `commit()` | 9 处 | ✅ 与基线一致 |
| N+1 查询 | 0 处 | ✅ 与基线一致 |

> 口径说明：我自建脚本按「>80 行」扫出 **85** 个函数，门禁口径为 **52**；差异源于门禁 `check_function_length.py` 的作用域/阈值不同。**以门禁为准**，我的口径不作为结论。

**单文件 >800 行（8 个，架构债）**

| 文件 | 行数 | 超出 |
|------|------|------|
| `fastapi_app/tests/test_purchase_center.py` | 1555 | +755 |
| `fastapi_app/services/backup/orchestration/recovery_test_service.py` | 1355 | +555 |
| `fastapi_app/services/bom_service.py` | 1011 | +211 |
| `fastapi_app/tasks/backup_tasks.py` | 963 | +163 |
| `fastapi_app/core/prod_runner.py` | 853 | +53 |
| `fastapi_app/services/stock_inventory_service.py` | 840 | +40 |
| `fastapi_app/api/v1/endpoints/backup/validation.py` | 835 | +35 |
| `fastapi_app/services/backup/cleanup/service.py` | 809 | +9 |

**超长函数 Top 5**

| 文件:行 | 函数 | 行数 |
|---------|------|------|
| `services/backup/dump.py:158` | `restore_database_via_psql` | 293 |
| `services/backup/orchestration/core.py:148` | `_do_create_full_backup` | 288 |
| `services/dashboard/mobile.py:41` | `fetch_mobile_dashboard` | 283 |
| `services/bom_service.py:643` | `copy_bom` | 256 |
| `core/health.py:54` | `register_health_routes` | 253 |

**导入图与循环依赖**：未发现因重排引入的新环（判据 = §2 第 7 项导入烟测通过）。完整依赖图与分层违规清单**未产出**（原调度成员失败）。

---

## §4 测试覆盖评估（由主理人代行，原调度成员失败）

**测试改动性质判定**（44 个测试文件被改）

| 指标 | 结果 |
|------|------|
| 断言净减少的文件 | **0** |
| 新增 `skip` / `xfail` | **0** |
| `pytest.raises` 捕获范围变化 | **0** |
| 涉及断言/标记改动的文件 | 6 |
| 标记为「可疑」的文件 | 3 —— 全部为 `contextlib.suppress(Exception)`（SIM105 等价改写） |

**等价性抽验**：

- `tests/conftest.py:226,246`：`try: await stale.dispose(...) except Exception: pass` → `with contextlib.suppress(Exception):` —— **语义等价**；且 `os.environ["APP_ENV"] = "test"`（L54）仍**先于** `fastapi_app.core.config` 导入，**载荷约束保住**
- `tests/e2e_api/test_auth_flow.py:238`：同上，且「清理尽力而为」注释保留
- `fastapi_app/tests/test_backup_p0.py:335`：同上，且守卫测试断言未动

**结论**：**未发现任何「为绿灯而放宽断言」的迹象**。测试改动全部是跟随源码的机械调整。

**未完成部分**：关键路径（auth / backup / order / purchase / outsource / BOM）的**逐条测试覆盖映射**与「无法捕获回归的测试」清单**未产出**（原调度成员失败）。当前仅有 2 个文件的实跑结果。

---

## §5 部署与回滚（由主理人代行，原调度成员失败）

### 5.1 关键判定：变更是否已被生产加载

| 对象 | 时间 |
|------|------|
| 后端 uvicorn 进程（pid 8748）创建 | **2026-09-23 22:08:39** |
| prod_runner 监督器（pid 8140）创建 | 2026-09-23 22:08:38 |
| nginx（pid 9840）创建 | 2026-09-23 22:08:40 |
| `main.py` mtime | 2026-09-23 23:23:46 |
| `core/deps.py` mtime | 2026-09-23 23:25:25 |
| `core/health.py` mtime | 2026-09-23 23:29:54 |
| `core/database.py` mtime | 2026-09-23 23:34:17 |
| `services/backup/__init__.py` mtime | 2026-09-23 23:40:04 |

`_cmd_uvicorn()`（`core/prod_runner.py:214-227`）参数为 `--workers 8 --host 127.0.0.1`，**无 `--reload`**。

> **结论：运行中的后端执行的是「扫荡前」代码。这批 130 文件改动尚未在生产上执行过一次 —— 风险是潜伏的。下次服务重启即为它的首次运行。**

### 5.2 迁移状态

| 项 | 值 |
|----|-----|
| `alembic current` | `pg_standalone_049_stockin_soft_delete (head)` |
| `alembic heads` | `pg_standalone_049_stockin_soft_delete (pg_standalone) (head)` |

✅ **无待执行迁移、单头无分叉**。`migrations/alembic.ini` 的改动（`script_location = .` → `%(here)s`）是一处**正确修复**，并自带 ASCII-only 警示注释，与「Alembic 以系统 locale（GBK）读取该文件」的约束一致。

### 5.3 回滚方案（仅描述，未执行）

1. **仅回滚工作区**：`git checkout -- <路径白名单>`（**禁止 `git add -A` / `git add .`**，会毁文档树）
2. **若已被加载且需回退**：严格按「停服务 → 回滚源码 → 起服务」顺序。⚠️ 爆炸半径提示：本机 nginx 为全机共用，`taskkill /F /IM nginx.exe` 会波及线上前端
3. ⛔ **禁止对 `.git` 做批量删除型操作**（`repack`/`gc`/`prune`/`clean -fdx`）：本环境删除被重定向进回收站，历史实测 `git repack -ad` 曾使整个 `.git` 被送进回收站、仓库随即不可用
4. 数据侧：本次无待执行迁移，**无需数据回滚**

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|---------|--------|---------|
| 1 | 将 6 处 `# noqa: BLE001 - <理由>` 改为 `# defensive: <理由>`（`core/database.py:111,116`、`services/order/beile.py:232`、`services/outsource/_shipments.py:228,401`、`services/purchase_order_sku.py:86`），然后重跑 `python scripts/quality_gate.py` 至绿 | 后端负责人 | **P0** | 当轮 |
| 2 | 在 `ruff.toml` 加 `lint.external = ["BLE001"]`，从机制上阻止 RUF100 再次删除该豁免；并把「改门禁必跑 `scripts/_selftest_gate.py`」写入 CI | 后端负责人 | **P0** | 当轮 |
| 3 | 按**路径白名单**提交这 130 文件 + 3 份交付物（禁 `git add -A`）；提交前跑 `git diff HEAD --stat` **逐文件核**是否存在「工作区反修复」 | 版本管理员 | **P1** | 当轮 |
| 4 | 重启后端前，先执行本次给出的两项前置验证：① 独立进程 `import fastapi_app.main` 烟测；② 关键单文件 pytest。重启安排在受控窗口 | SRE | **P1** | 下一窗口 |
| 5 | 把 `scripts/phase1_switch.ps1` 纳入版本控制并评审（或明确 ignore + 加安全护栏），消除未跟踪破坏性脚本 | SRE | **P2** | 本周 |
| 6 | 收敛超长函数：先拆 `services/backup/dump.py:158`(293) 与 `services/backup/orchestration/core.py:148`(288)；同步拆分 `bom_service.py`(1011) 与 `recovery_test_service.py`(1355) | 架构负责人 | **P2** | 本迭代 |

---

## ⚠️ 待完善 / 已知局限

1. **本次 4 位成员全部因基础设施故障失败**（模型网关 `502 / ECONNREFUSED 127.0.0.1:7863`），因此以下专业产出**缺失**，本报告中的对应章节由主理人代行、覆盖面较窄：
   - Cody：全库安全/性能四维审查（本报告仅覆盖 bandit + ruff-S，未做逐点人工安全走查）
   - Archi：完整分层依赖图、服务间顶层互 import 违规清单、循环依赖环检测
   - Tessa：关键路径测试覆盖映射、「无法捕获回归的测试」清单
   - Rex：Go/No-Go 清单的团队评审版、回滚演练
2. **未执行全量 pytest**：受 conftest event loop 污染约束只能单文件运行，本次仅实跑 2 个文件（28 passed），**不能代表全量绿灯**。
3. **未执行前端类型门禁**（`vue-tsc -b`）与前端测试。
4. **未验证前端 dist 与源码的一致性**：本次仅确认 `:3000` 由 nginx+dist 承载，未比对 dist 产物是否包含工作区最新源码（记忆库要求：判 dist 陈旧须在产物里 grep 独有字符串）。
5. 门禁口径与我自建脚本口径存在差异（超长函数 52 vs 85），本报告**一律以门禁为准**。

---

## 📚 数据来源 & 成员产出索引

**⚠️ 成员产出索引：无。** 本次调度的 4 位成员（code-reviewer / architect / testing-expert / sre-engineer）均因模型网关故障（`502 ECONNREFUSED 127.0.0.1:7863`）在运行约 4 分 17 秒后失败，**未产生任何专业产出**。本报告不含、也不代表任何成员的结论。

**本报告全部结论的原始证据（均为本轮实测，可复核）：**

| 证据 | 位置 / 命令 |
|------|------------|
| ruff F821 全库零命中 | `ruff check --select F821 --no-cache fastapi_app` → `All checks passed!` |
| ruff 全量零违规 | `ruff check --no-cache --statistics fastapi_app` |
| 导入变动归类（22 真删除 / 29 名字） | `_qa_tmp/_removed_import_audit_v2.json` |
| 宽泛 except 门禁 11 处 | `scripts/check_bare_except.py` → `_qa_tmp/_bare_except.txt` |
| **质量门禁 FAIL（9→11）** | `python scripts/quality_gate.py` → `_qa_tmp/_gate.txt` |
| RUF100 机理受控实验 | `_qa_tmp/_ruf100_probe.py` + `_qa_tmp/_ruff_settings.txt` |
| 进程创建时间 | `Get-CimInstance Win32_Process` → `_qa_tmp/_proctime.txt` |
| 载荷式导入顺序守卫测试 | `pytest ...::TestSourceGuards::test_package_restore_lock_resolves_to_redis_version` → PASSED |
| 导入烟测 | `import fastapi_app.main` → `IMPORT_OK` |
| 回归测试 | `_qa_tmp/_tests_run.txt` → 20 passed + 8 passed |
| bandit | `_qa_tmp/_bandit.json` → 0 HIGH / 2 MEDIUM / 10 LOW |
| 测试断言改动判定 | `_qa_tmp/_test_assert_diff.json` |
| SOLID 扫描 | `_qa_tmp/_solid_scan.json` |
| 迁移状态 | `alembic current` / `alembic heads` |
| 生产模式四判据 | `_qa_tmp/_prod_mode_probe.py` → `PROD (built assets)` |

**生产运行态快照（2026-09-24 08:27）**：前端 `:3000` → 200（`/assets/index-BrN34KwG.js`，无 `/@vite/client`）；后端 `:5002/api/health` → `{"status":"healthy"}`；`/api/health/arq` → `running`（`j_complete=46 j_failed=0 j_retried=0`）。

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。

# 滨发 ERP 上线前代码审核报告（精简版）

**日期**：2026-09-05
**场景**：上线前检查（代码质量 + 发布就绪）
**参与成员**：主理人沽思航直接执行（安全官/排障手/质量门神因子 Agent 通道 429 限流（inference TPM 耗尽）多次中断，应用户要求取消安全审计专项，其余由主理人以精简抽查方式完成）

---

## 📌 TL;DR

- 整体结论：🟡 **有条件通过** —— 核心工程质量良好，无阻塞性高危缺陷；主要是发布物料清洁度与若干超限文件需处理
- 阻塞项数量：0（无 P0 阻塞项）
- 下一步：清理 6 个前端旧 dist 目录与 .bak 残留，处理 3 个超 800 行文件，确认迁移多基线是否有意为之

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| Go / No-Go | 🟡 条件 Go（清理物料 + 确认迁移基线后可上线） |
| 严重度分布 | 🔴 0 / 🟠 3 / 🟡 5 / 🟢 6 |
| 关键行动项 | 5 条 |
| 建议负责人 | 后端负责人 + 运维 |

---

## 1. 各维度核心结论

### 🔧 代码质量与缺陷（排障手职责，主理人代执行）
- **异常处理**：全仓 `except Exception` 共 60+ 处抽查命中，**全部**带 `broad-except` 注释与正当降级理由（WebSocket 容错、熔断器、缓存降级、端点兜底），未发现裸 `except: pass` 吞异常。质量高。
- **调试残留**：`print()` 仅存在于 `core/prod_runner.py`（CLI 守护工具，属合理用法）；但存在 `.bak_ipv6` 备份残留（见发现表）。
- **SQL 注入面**：所有动态 SQL（f-string 拼表名）均带 `nosec B608` 注释且表名经 `quote_table` 白名单校验，参数走绑定变量。备份/恢复域的逐表循环已标注 `batch-loop` 说明（业务必要）。
- **空指针/并发**：抽查未发现典型未判空崩溃路径；库存扣减与编号生成走独立事务/锁（编号双实现为有意设计，未误报）。

### ✅ 发布就绪（质量门神职责，主理人代执行）
- **部署脚本**：`deploy_nginx.ps1` / `deploy-windows.ps1` / `release.bat` / `build_*.bat` 未检出 `rm -rf` / `Remove-Item -Recurse -Force` / `del /f` 等危险命令。
- **配置治理**：`.gitignore` 覆盖完善（JWT/备份密钥/keystore/环境文件/日志/nul/query 均已排除）；CORS 区分 dev/prod、生产强制 `ALLOWED_HOSTS` 非空校验、生产自动关闭 Swagger/docs 端点。
- **依赖**：`requirements.txt` 为 shim 引用 `requirements/base.txt` 等分拆文件，非漂移，属有意设计。
- **硬编码密钥**：全仓 password/secret/token 命中均为测试文件与审计脚本自身的测试样例，未发现生产代码/配置中的明文密钥。

### 📊 性能
- API 层（`fastapi_app/api/`）未检出任何裸 `.all()` 无分页返回（0 命中），列表接口均有分页。
- 备份/恢复域存在逐表 `SELECT *` 循环（已注释 `batch-loop`，业务必要，数据量大时需关注内存）。

---

## 2. 综合审查发现（按严重度排序）

| # | 严重度 | 类别 | 位置 | 问题描述 | 建议 |
|---|--------|------|------|---------|------|
| 1 | 🟠 | 发布物料 | `frontend-vite/dist.bak-20260824`、`dist.bak-20260829`（含嵌套 dist/）、`dist.bak-20260829-2`、`dist_prev_20260829_164650`、`dist_prev_20260829_180908` | 5 个历史前端构建备份目录残留，合计约 26MB，且 `dist.bak-20260829` 内嵌套一层旧 dist；`.gitignore` 未覆盖 `dist.bak-*`/`dist_prev_*`，有误提交/误部署风险 | 确认无回滚需要后删除；在 `.gitignore` 增加 `frontend-vite/dist.bak*/`、`frontend-vite/dist_prev_*/` |
| 2 | 🟠 | 迁移健康 | `migrations/versions/` | 检出 **4 个** `down_revision = None` 的基线迁移，存在多 head/多根风险，新服务器 `alembic upgrade head` 可能失败或只升单链 | 上线前执行 `alembic heads` 确认；若为历史多根需合并或文档化说明 |
| 3 | 🟠 | 规范超限 | `tasks/backup_tasks.py`(962行)、`api/v1/endpoints/backup/validation.py`(836行)、`services/stock_inventory_service.py`(827行) | 超出项目 ≤800 行约定（SOLID-S），backup 域为超限重灾区 | 按既有拆分流水线（函数边界提取→Facade）渐进治理；`stock_inventory_service.py` 另有 770+ 行超长 SQL 拼接段建议抽离 |
| 4 | 🟡 | 发布物料 | `fastapi_app/core/prod_runner.py.bak_ipv6`、`fastapi_app/main.py.bak_ipv6`、`server_manager.py.bak-20260822_135022` | 源码目录内 `.bak` 残留，可能被 PyInstaller spec 误打包 | 删除或移出源码树 |
| 5 | 🟡 | 发布物料 | 根目录 `_dbg_customers.py`、`_shoot_p6.py`、`_p6.log`、`analyze_ruff.py`、`one_click_action.py` | 调试/一次性脚本残留于仓库根（`analyze_ruff.py` 等已在 gitignore 覆盖与否需确认） | 移入 `scripts/dev/` 或删除；发布包脚本排除 |
| 6 | 🟡 | 架构约定 | `fastapi_app/services/` 全域 | 服务间模块顶层 import 约 211 处（粗略统计），与「禁止服务间顶层互 import」约定存在张力，可能含大量域内 Facade 合法用例 | 抽样复核非域内、非延迟 import 的部分，列入渐进治理 backlog（不阻塞上线） |
| 7 | 🟡 | 可维护性 | fastapi_app 全域 | TODO/FIXME 分布于 23 个文件共 20+ 处 | 上线前过一遍，把影响功能的转 issue，其余标注排期 |
| 8 | 🟡 | 磁盘运维 | `logs/`(16MB)、`backups/`(59MB)、`build/`(24MB) | 本地体量可控，但需确认生产服务器日志轮转与备份保留策略已生效（`prod_runner` 已有轮转逻辑） | 上线后验证日志轮转与 backups 保留策略实际运行 |
| 9 | 🟢 | 测试 | `fastapi_app/tests` + `tests/` | 测试文件 141 个，覆盖面可观；已知全量 pytest 有 conftest event loop 污染（已记录为已知问题） | 上线前按文件分批跑通核心域测试（backup/stock/auth/order） |

---

## ✅ 行动清单（上线前）

| # | 行动 | 负责方 | 紧急度 |
|---|------|--------|--------|
| 1 | 删除/归档 `frontend-vite/` 5 个旧 dist 目录，`.gitignore` 补 `dist.bak*/` `dist_prev_*/` | 前端/运维 | P0 |
| 2 | 执行 `alembic heads` 确认 4 个基线迁移是否有意多根；无意则合并 | 后端 | P0 |
| 3 | 删除 `*.bak_ipv6` 与 `server_manager.py.bak-*` 源码残留，确认 PyInstaller spec 不含它们 | 后端 | P1 |
| 4 | 根目录调试脚本（_dbg/_shoot/_p6/analyze_ruff）移出发布面 | 后端 | P1 |
| 5 | 分批跑通 backup/stock/auth/order 核心域测试，记录基线 | QA | P1 |

### 上线后 30 分钟冒烟清单
1. `GET /api/health` 返回 200（prod_runner 健康门依赖）
2. 登录 → 下单 → 审批 → 出库全链路一单走通
3. 采购计划三段式导入（upload→validate→confirm）小批量验证
4. 手动触发一次备份任务并验证进度键与产物生成
5. 确认 `/api/docs` 在生产环境 404（文档端点已关闭）

### 回滚预案要点
- 数据库：上线前用既有备份子系统做一次全量 `.envbak` 备份并验证恢复演练（recovery_test_service 已具备测试库恢复能力）
- 代码：保留当前 `frontend-vite/dist` 与后端镜像快照；Nginx 配置回滚到上一版本
- 服务：NSSM 服务可快速切回旧版本目录

---

## ⚠️ 待完善 / 已知局限

- **本次为精简抽查而非逐行全审**：因子 Agent 通道 429 限流，安全官（OWASP+STRIDE 专项）、排障手、质量门神均未能完成独立深度审查，本报告由主理人以约 10 轮定向 grep/抽样完成，覆盖高风险面但非穷尽。
- **安全审计未执行**：JWT 强度、权限校验端点覆盖、zip slip、依赖 CVE 等专项未做，建议额度恢复后补一轮安全官专项。
- 并发竞态、N+1 查询未做调用链级验证，仅模式级抽查。
- 211 处服务间 import 未逐条甄别合法性。

---

## 📚 成员产出索引

- gstack-security-officer：❌ 两次因 429 中断，无产出（用户已决定取消安全专项）
- gstack-investigator：❌ 两次因 429 中断，无产出（职责由主理人精简代执行）
- gstack-qa-lead：⏸️ 未启动（职责由主理人精简代执行）

---

> 本报告由软件工坊 AI 协作生成（限流降级为主理人直接执行版），关键决策请由工程负责人复核。额度恢复后建议补跑安全专项与深度 QA。

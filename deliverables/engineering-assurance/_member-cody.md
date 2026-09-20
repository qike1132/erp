# _member-cody.md — 代码质量与安全性审查（Code Reviewer · Cody）

- 仓库：`D:/erp_system`（git，HEAD=`351c822`）
- 审查方式：**全部结论均为实测**（ruff 实跑 / `python -m` 实导入 / git ls-files 实查 / 脚本实跑），命令与原始输出见文末《证据索引》
- 已排除的误报见《误报排除》

---

## Code Review: 滨发 ERP 代码质量与安全性（Task #1）

### 概要
整体健康度**中上**：工程纪律明显好于同规模项目（`.gitignore` 密钥覆盖齐全、宽泛 except 普遍带降级理由注释、生产切换有显式禁用护栏）。但存在 **1 个必须立刻处理的安全级问题（完整 Edge 凭据库入库）** 与 **1 个潜伏的迁移致命缺陷**；ruff F821/F823 实测仅 20 处且多无害。

### 严重问题

| # | 文件 / 范围 | 位置 | 问题 | 严重度 |
|---|------|------|-------|---------|
| 1 | `docs/ui-redesign/v4/_edge_profile_{ov,sv}/**` | 428 个被 git 跟踪 | **整套 Edge 浏览器配置库被提交入库**，含 `Login Data`(51200B)、`Login Data For Account`(51200B)、`Network/Cookies`(20480B)、`Network/Trust Tokens`(36864B)、`Vpn Tokens`(28672B)、`Web Data`(223232B)、`History`(204800B)、`Local State`(11167B，含 DPAPI 包裹的 `os_crypt.encrypted_key`)。`Login Data` + `Local State` 同机可解密 → **等于把完整账号密码库 + 会话 Cookie + 浏览历史入库**。 | 🔴 |
| 2 | `migrations/versions/pg_standalone_006_add_material_production_indexes.py` | L17–31 | 文件**完全缺失 `from alembic import op`**（全文 32 行无任何 import）。实测调用 `upgrade()` 直接抛 `NameError: name 'op' is not defined`。该 revision 位于迁移链 005→006→007→…→010 中间，**任何全新安装 / 灾备全量恢复 / downgrade 后 upgrade 都会在此 revision 崩溃**。 | 🟠 |

### 改进建议

| # | 文件 | 行 | 建议 | 类别 |
|---|------|------|------|------|
| 3 | `server_manager_v8/adapters/process_win.py` | 339, 354 | 类型标注残留旧名 `PortOccupier`，而本模块实际类为 `PortOccupierInfo`（L100 定义、L373 构造）。因 L46 有 `from __future__ import annotations`，**运行期安全**；但 `typing.get_type_hints(port_occupiers)` 会 `NameError`（实测 `hasattr(m,'PortOccupier')==False`）。改为 `PortOccupierInfo`。 | 正确性/可维护性 |
| 4 | `fastapi_app/services/ocr_service.py` | 11, 20 | 同一 `IMAGE_EXTENSIONS` 从同一模块**重复导入**两次（re-export 垫片），删掉 L20。 | 可维护性 |
| 5 | `fastapi_app/services/order/deduction.py` | 53, 81 | 模块级 `from fastapi_app.shared_models import ... StockIn`（L53）被子函数内 `from ... import StockIn`（L81）遮蔽 → 模块级绑定成为**死导入**（ruff F811）。二者同对象，无功能影响，清理其一即可。 | 可维护性 |
| 6 | `scripts/switch_env.py` | 17 | `project_root = Path(__file__).parent` 指向 `scripts/`，而真实 `.env*` 全在**仓库根**。导致脚本两模式均失效（见下「③ 结论」）。若将来修正路径，须同时保留「生产禁用」护栏，否则 dev 分支 `copy2` 会真的覆盖根 `.env`。 | 正确性 |
| 7 | `deliverables/audit-2026-09-17/_slowapi_extension.py` | 332, 333 | `F821 Undefined name 'app'`（审计临时产物，非产品码）。 | 可维护性 |
| 8 | `scripts/check_spec_sync.py` | 388 | `F811` 重复定义 `main`（L167 的定义被弃用/死代码）。 | 可维护性 |
| 9 | `.env.example` | L500–501 | `S3_ACCESS_KEY=minioadmin` / `S3_SECRET_KEY=minioadmin` 为 MinIO 默认弱口令。示例文件可接受，但需在部署检查中显式确认生产未沿用。 | 安全（低） |

### 做得好的地方
- **密钥治理到位**：`.gitignore` 显式覆盖 `.env`/`.env.production`/`.env.development`/`.env.backup`、`config/jwt/*.pem|key`、`backups/.backup_encryption.key`、`config/redis.production.conf`、Android keystore。实测 `git ls-files ^\.env` **只跟踪 `.env.example` 与 `.env.production.example` 两个模板**——真实 `.env*` 未入库（✅ 有效）。
- **宽泛 except 有纪律**：全仓 751 处 `except Exception`（应用面 ~229 处）**绝大多数带明确降级理由注释**（"探活失败即视为不可用"、"rollback 失败不应掩盖原异常" 等），`except ...: pass` 的静默吞噬子集经逐点核查均为合理防御（见下「④ 结论」）。
- `scripts/switch_env.py` 对生产切换的**显式禁用 + 原因说明**是一处很克制的护栏设计。
- `ruff.toml` 的 ignore 项均附逐条理由注释，非无脑关闭。

---

## 逐项结论（对 team-lead 四项最高优先级）

### ① `ruff --select F821,F823` 实测 —— 共 20 处，仅 2 处有实义
命令：`uvx --from ruff ruff check --no-cache --select F821,F823,F811 --output-format concise .`
（pip `ruff` 包 0.15.11 的二进制缺失，`python -m ruff` 报 `RuffNotFound`；改用 `uvx` 拉取 ruff 0.16.8 实跑成功，exit=1）

- **F823：0 处**（无「引用前赋值」缺陷）。
- **F821（未定义名）8 处**，其中真正有价值 2 组：
  - 🔴→🟠 `migrations/.../pg_standalone_006...py` L17–31 `op` ×12 → **见严重问题 #2**（已实测 `upgrade()` 抛 NameError）。
  - 🟡 `server_manager_v8/adapters/process_win.py` L339/354 `PortOccupier` → 运行期安全（PEP 563），仅类型标注错名。
  - 🟢 `deliverables/.../\_slowapi_extension.py` L332–333（临时产物）。
- **F811（重复定义/死导入）4 处**：`ocr_service.py`、`deduction.py`、`check_spec_sync.py`、`test_backup_m1.py`（均无功能影响，见建议 #4/#5/#8）。

> 结论：F821/F823 作为「性价比缺陷探针」在本仓**命中率低但确有 1 个真弹**（迁移 op），值得纳入 CI 门禁。

### ② 凭据 / 敏感文件是否入库 —— 命中 1 个 🔴
命令：`git ls-files | Select-String '\.env|\.pem$|\.key$|\.p12$|\.pfx$|id_rsa|secret|credential|password|\.sqlite|\.db$|backup|token|\.pwd$'`
- 🔴 **`docs/ui-redesign/v4/_edge_profile_ov/**` 与 `_edge_profile_sv/**` 共 428 个文件被跟踪**（见严重问题 #1；磁盘实测 `Login Data`=51200B、`Local State`=11167B 等均非空）。
- ✅ 真实 `.env*` 未入库；仅 `.env.example` / `.env.production.example` 两个**模板**被跟踪。
- ✅ 无真实私钥入库：`git grep -l "BEGIN .*PRIVATE KEY"` 唯一命中 `scripts/prod_audit/tests/test_self_audit.py:46`，经查为**脱敏扫描器的测试夹具字符串**（`"private key: -----BEGIN RSA PRIVATE KEY-----"`），非真钥 → 误报，不报。
- 处置建议：`git rm -r --cached docs/ui-redesign/v4/_edge_profile_ov docs/ui-redesign/v4/_edge_profile_sv` + `.gitignore` 增补 `_edge_profile_*/`、`*.db-journal`；鉴于 `Login Data`+`Local State` 可解密，**建议按凭据泄露事件评估是否轮换相关账号口令/会话**。

### ③ `scripts/switch_env.py production` copy2 覆盖 `.env` 爆炸半径 —— 实测「不可复现」
命令：实跑 `python scripts/switch_env.py production` 与 `... development`
- `production` → 打印「生产环境切换已禁用」，**在任何 copy 之前 `return False`**（源码 L25–32）。
- `development` → 报「配置文件不存在: `D:\erp_system\scripts\.env.development`」——因 `project_root=Path(__file__).parent`=`scripts/`，而 `.env.development` 在仓库根（实测 `scripts/.env.development`=False、`/.env.development`=True）。
- **结论：当前代码两条路径都无法触碰根 `.env`，team-lead 担忧的「双配置源爆炸半径」在当前 HEAD 不成立（已被显式禁用 + 路径错位双重封堵）。** 残留为建议 #6 的潜伏路径缺陷。

### ④ 宽泛 `except Exception` 逐处判定 —— 实际 751 处，远超「9 处」
命令：`git grep -o "except Exception" -- "*.py"` → **751 处 / 253 文件**；`fastapi_app` 非测试 **229 处**。
- **不存在「9 处」这一口径**——请以上游 team-lead 核对是否指某单文件/某单次扫描；按全量看，逐处判定不具可操作性。
- 按风险分类后，全部**未见「危险吞噬」**：
  - **可接受防御（绝大多数）**：显式「降级/旁路/容错」语义并带理由注释，如 `audit_middleware`（审计失败不影响主请求）、`circuit_breaker`（须全捕以计失败数）、`exceptions.py`（必须全捕以保证任何失败路径都 rollback）、备份子系统（自愈/局部失败不阻断整体）。
  - **静默 `except: pass/continue` 子集（实测共 7 处）经逐点核查均可接受**：
    - `fastapi_app/services/backup/records.py:188/654/668/684` — 告警/rollback 失败，注释明示不阻塞主流程。
    - `server_manager_v8/adapters/process_win.py:241/247` — 枚举子进程/`kill` 的**尽力而为**语义（残留扫描文档「宁可漏杀，不可误杀」）。
    - `server_manager_v8/adapters/process_win.py:594` — 残留扫描单条解析失败 `continue`（同上约定）。
    - `server_manager_v8/adapters/health_http.py:153` — `response.close()` 资源清理吞异常，不改变判定。
- 唯一**需盯**的一点：备份/恢复/验证链大量依赖 `except Exception → 返回安全默认值`（如 `ro_grants.py:49` 降级为「需修复」、`backup_progress` 读取失败「按无密码处理」），需确保这些降级**都会落 ERROR 日志/告警**，否则复现历史「WAL 备份假成功」类事故。建议 `scripts/check_bare_except.py` 把这些纳入门禁。

---

## 误报排除（不予上报）
- 内网 HTTP 下 CSRF Cookie 无 `Secure` → 正确行为。
- `/docs` 404 → 有意关闭。
- 编号双实现 → 有意设计。
- `test_self_audit.py` 的 `BEGIN RSA PRIVATE KEY` → 脱敏测试夹具，非真钥。
- `server_manager_v8/adapters/process_win.py` F821 → 因 PEP 563 **运行期不抛错**（已实测 import OK），故降级为 🟡 而非 🔴。

---

## 结论
**Request Changes（附 1 项 🔴 需立即处置）**：优先 `git rm --cached` 那 428 个 Edge 配置文件并按凭据泄露评估轮换；同步补 `pg_standalone_006` 的 `from alembic import op`（否则灾备/全新部署必炸）。其余为可排期清理项。整体工程纪律良好，无系统性崩溃风险。

---

## 证据索引（原始文件均在 `deliverables/engineering-assurance/`）
| 证据文件 | 内容 |
|---|---|
| `_ev_ruff.txt` | `uvx ruff check --select F821,F823,F811` 原始输出（20 findings，exit=1） |
| `_ev_git.txt` | `git ls-files` 敏感路径命中、`.gitignore` 全文、tracked `.env` 实测 |
| `_ev_sens.txt` | 428 个 edge-profile 跟踪清单、`.env.example` 内容、真钥扫描 |
| `_ev_edgesize.txt` | `Login Data`/`Local State`/`Cookies` 等磁盘实测体积 |
| `_ev_import.txt` | `import server_manager_v8...process_win` → `IMPORT_OK` + `hasattr(PortOccupier)=False` |
| `_ev_mig.txt` | 加载 `pg_standalone_006` 调 `upgrade()` → `NameError: name 'op' is not defined` |
| `_ev_count.txt` | `except Exception` 计数(751/229)、`switch_env.py` 两模式实跑输出 |
| `_ev_except.txt` | 全仓 `except Exception` 逐行清单 |

### 关键命令（可复核）
```bash
# ① ruff F821/F823（pip 二进制缺失，走 uvx）
uvx --from ruff ruff check --no-cache --select F821,F823,F811 --output-format concise .
# ② 迁移真弹（无 DB）
python -c "import importlib.util as u;p=r'migrations/versions/pg_standalone_006_add_material_production_indexes.py';s=u.spec_from_file_location('m',p);m=u.module_from_spec(s);s.loader.exec_module(m);print(hasattr(m,'op'));m.upgrade()"
# ③ switch_env 爆炸半径
python scripts/switch_env.py production ; python scripts/switch_env.py development
# ④ 计数
git grep -o "except Exception" -- "*.py" | wc -l
# ⑤ 入库存疑
git ls-files "docs/ui-redesign/v4/_edge_profile_*" | wc -l      # -> 428
```

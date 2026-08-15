---
design_type: feature
created_at: 2026-08-15
---

# ERP 项目根目录清理设计

## Intent Contract

```
intent: 清理 d:\erp_system 根目录的垃圾文件（临时产物、散落日志、缓存、AI 工具残留、打包残留、误创建文件），使项目结构清晰且系统可正常启动运行。
constraints:
  - 不触碰运行必需路径：fastapi_app/、frontend-vite/、utils/、migrations/、scripts/、config/、.env*、requirements*
  - 不删除 run.py（server_manager.py 调试模式引用）、start.py、server_manager.py、打包/部署脚本（build_*.bat、release.bat、deploy-*.ps1、*.spec）
  - 所有删除一律先移入隔离区 .archive/cleanup-20260815/，不做永久删除
  - dist/ 仅归档旧版本 exe（保留最新 v5.21 与 erp_project_path.txt）
  - 不修改任何 Python/Vue 业务代码
success_criteria:
  - 根目录散落文件（非目录）数量从 ~70 降至 ~30
  - erp-prod 服务可启动且 GET /api/health 返回 200
  - pytest 测试收集无 ImportError
  - git status 无意外丢失的被跟踪文件（移动的被跟踪文件以 rename/deleted+added 形式呈现并在提交中体现）
risk_level: medium（批量文件操作不可逆，但通过隔离区过渡 + 启动验证缓解）
```

## Verification Contract

```
verify_steps:
  - run tests: pytest tests/ --collect-only -q（确认无 ImportError，收集成功）
  - check: nssm 启动 erp-prod 后 GET http://127.0.0.1:5002/api/health
  - confirm: 返回 200 且 status=ok；验证后服务恢复原 stopped 状态
  - check: git status 对比清理前后，被跟踪文件仅出现在本次计划清单内
  - check: frontend-vite/dist/index.html 存在且未被修改（前端托管产物完整性）
```

## Governance Contract

```
approval_gates:
  - 隔离区移动完成后、永久删除前：用户确认系统运行正常
  - git 提交前：向用户展示变更摘要
rollback: 从 .archive/cleanup-20260815/ 按原路径移回（隔离区保留原始相对路径结构）；git 提交可 revert
ownership: 用户拥有最终删除决定权；本次会话仅执行到"隔离区+验证"为止，永久删除留待用户确认
```

## Scope

| In | Out |
|---|---|
| 根目录临时文件/误创建文件移入隔离区 | 永久删除任何文件 |
| 根目录散落日志移入隔离区 | fastapi_app/、frontend-vite/、utils/ 内部清理 |
| 缓存目录（.mypy_cache 等）移入隔离区 | logs/、backups/ 目录内容清理 |
| AI 工具残留目录（~15 个）移入隔离区 | tests/ 目录清理 |
| build/ 打包中间产物、dist/ 旧版 exe 移入隔离区 | 数据库/Redis/NSSM 配置变更 |
| 一次性诊断脚本移至 scripts/archive/，运维工具移至 scripts/ | 业务代码修改 |
| 安全报告移至 docs/ | node_modules、venv 处理 |
| .gitignore 补充规则并 git 提交 | 递归清理子目录内 __pycache__（仅根级） |

## Decisions

| # | 决策 | 选择 | 否决的替代方案 |
|---|---|---|---|
| 1 | 删除安全机制 | 隔离区 .archive/cleanup-20260815/ 过渡，验证后用户确认再永久删 | 直接永久删除（不可逆）；回收站（大量小文件慢且不可脚本化恢复） |
| 2 | 清理范围 | 标准清理（垃圾+AI残留+脚本归位） | 深度清理（动 backups/logs 轮转，风险高收益低） |
| 3 | utils/ 去留 | 保留（fastapi_app/schemas 引用 utils.sanitizer） | 归档（会破坏生产导入链） |
| 4 | run.py 去留 | 保留（server_manager.py 两处调用） | 归档（GUI 调试模式失效） |
| 5 | 散落脚本处置 | 一次性诊断→scripts/archive/；常用运维→scripts/；报告→docs/ | 全部进隔离区（丢失有用工具）；留在根目录（继续乱） |
| 6 | dist/ 处置 | 归档 v5.19/v5.20.1 旧 exe 与 dump.rdb 副本 | 整目录归档（丢失在用 exe）；全保留（旧版本无用） |
| 7 | .gitignore | 补充根目录日志/缓存/临时输出规则 | 不改（垃圾会再次积累且被 git 跟踪） |

## Surface

**文件系统（移入 .archive/cleanup-20260815/，保留相对路径）**：
- 误创建：`tapi_app...print('ok')`（长名文件）、`qc`、`query`、`queryex`
- 临时输出：`backend-check.out`、`bench_result.txt`、`beile_diff.txt`、`tc-output2.txt`、`test-err.txt`、`type-check-output.txt`、`_ruff_output.json`、`_vue_tsc_all.txt`、`_vue_tsc_errors.txt`、`req1.err`、`req2.err`、`.coverage`
- 调试截图：`debug_login.png`、`debug_page.png`、`frontend-access-ok.png`
- 散落日志：`uvicorn_outsource.err.log`、`uvicorn_outsource.log`、`uvicorn_restart.log`、`vite_dev.err.log`、`vite_dev.log`、`server_log.txt`、`build_pyinstaller.log`
- 缓存目录：`.mypy_cache`、`.pytest_cache`、`.ruff_cache`、`__pycache__`（根级）、`pytest-cache-files-f4pbu0gf`、`$tmpPath`、`.tmp_analysis`
- AI 工具残留目录：`.freebuff`、`.codeartsdoer`、`.codebuddy`、`.comate`、`.arts`、`.gstack`、`.lean-ctx`、`.learnings`、`.workbuddy`、`.agents`、`agents`、`skills`、`memory`、`shots`、`playbooks`、`cli`、`design-system`、`dashboard-preview`
- AI 配置残留：`.claude.json`、`.windsurfignore`、`setup-claude-code.ps1`
- 打包残留：`build/`、`dist/ERP服务器管理器_v5.19.exe`、`dist/ERP服务器管理器_v5.20.1.exe`、`dist/dump.rdb`

**重定位（不进隔离区）**：
- → `scripts/archive/`：`check_users.py`、`clear_business_data.py`、`diag_heads.py`、`diag_inv.py`、`reset_admin.py`、`verify_beile_data.py`、`validate_supreme_directive.py`、`apply_missing_ddl.py`、`apply_material_trgm_indexes.sql`、`start_production_optimized.py`、`_tmp_verify_user.py`
- → `scripts/`：`restart_backend.py`、`switch_env.py`、`upload_nginx.py`
- → `docs/`：`blue-team-security-review-20260605-001.md`、`red-team-vulnerability-report-20260605-001.md`

**配置**：`.gitignore` 追加根目录垃圾模式（`/*.log`、`/*.out`、`/*.err`、`/_vue_tsc_*.txt`、`.mypy_cache/` 等，具体以现有文件内容查缺补漏为准）

**git**：一次提交包含全部移动 + .gitignore 变更

## Risks & Open Questions

- **风险 1**：某散落脚本被外部计划任务/快捷方式引用。缓解：移动而非删除，隔离区与 scripts/archive/ 保留原文件名，可按名找回；验证步骤包含服务启动。
- **风险 2**：`memory/`、`.learnings/` 等目录可能含用户想留的 AI 学习记录。缓解：仅移入隔离区不删除，用户可在永久删除前翻查。
- **风险 3**：pytest 全量收集可能因环境依赖报错（与清理无关的历史问题）。处理：仅关注 ImportError 类失败是否由本次移动引起。
- **开放问题 1**：`dist/dump.rdb` 是 Redis 快照副本，当前 erp-redis 服务数据目录不在 dist/，按副本归档——永久删除前需用户知悉。
- **开放问题 2**：erp-prod/erp-arq 当前处于 stopped 状态（非本清理所致），验证后将恢复该状态；后续是否启动由用户决定。

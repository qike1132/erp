---
intent: 清理 d:\erp_system 根目录垃圾文件（临时产物、散落日志、缓存、AI 工具残留、打包残留、误创建文件），全部移入隔离区可恢复，系统启动验证通过
success_criteria: 根目录散落文件从 ~70 降至 ~30；erp-prod 启动后 GET /api/health 返回 200；pytest 收集无 ImportError；git 提交仅含本次清理相关路径
risk_level: medium
auto_approve: true
branch: new-main
worktree: false
dirty_worktree: allow
---

## Steps

- [ ] **Step 1: 创建隔离区目录结构**
action: 在 d:\erp_system 下创建 `.archive/cleanup-20260815/` 主隔离目录及子目录 `root-files/`、`cache-dirs/`、`ai-tool-dirs/`、`build-artifacts/`。所有后续移动保留原相对名，便于按原路径回滚。
loop: false
verify:
  type: artifact
  path: .archive/cleanup-20260815
  assert:
    kind: exists

- [ ] **Step 2: 移动根目录散落文件（误创建+临时输出+截图+日志）到隔离区**
action: 在 d:\erp_system 下将下列文件移动到 `.archive/cleanup-20260815/root-files/`：误创建 4 个（长名文件 `tapi_app.services.daily_production_service import export_records, get_daily_summary; print('ok')`、`qc`、`query`、`queryex`）；临时输出 12 个（`backend-check.out`、`bench_result.txt`、`beile_diff.txt`、`tc-output2.txt`、`test-err.txt`、`type-check-output.txt`、`_ruff_output.json`、`_vue_tsc_all.txt`、`_vue_tsc_errors.txt`、`req1.err`、`req2.err`、`.coverage`）；调试截图 3 个（`debug_login.png`、`debug_page.png`、`frontend-access-ok.png`）；散落日志 7 个（`uvicorn_outsource.err.log`、`uvicorn_outsource.log`、`uvicorn_restart.log`、`vite_dev.err.log`、`vite_dev.log`、`server_log.txt`、`build_pyinstaller.log`）。逐项 `Test-Path` 后移动，容错单个不存在（记录跳过）。
loop: false
verify:
  type: shell
  command: powershell -Command "$missing=@('tapi_app.services.daily_production_service import export_records, get_daily_summary; print(''ok'')','qc','query','queryex','backend-check.out','bench_result.txt','beile_diff.txt','tc-output2.txt','test-err.txt','type-check-output.txt','_ruff_output.json','_vue_tsc_all.txt','_vue_tsc_errors.txt','req1.err','req2.err','.coverage','debug_login.png','debug_page.png','frontend-access-ok.png','uvicorn_outsource.err.log','uvicorn_outsource.log','uvicorn_restart.log','vite_dev.err.log','vite_dev.log','server_log.txt','build_pyinstaller.log') | Where-Object { Test-Path ('d:\erp_system\'+$_) }; if ($missing) { $missing -join ','; exit 1 } else { 'ROOT_CLEAN' }"

- [ ] **Step 3: 移动缓存目录到隔离区**
action: 在 d:\erp_system 下将 7 个缓存目录移动到 `.archive/cleanup-20260815/cache-dirs/`：`.mypy_cache`、`.pytest_cache`、`.ruff_cache`、`__pycache__`、`pytest-cache-files-f4pbu0gf`、`$tmpPath`、`.tmp_analysis`。
loop: false
verify:
  type: shell
  command: powershell -Command "$dirs=@('.mypy_cache','.pytest_cache','.ruff_cache','__pycache__','pytest-cache-files-f4pbu0gf','$tmpPath','.tmp_analysis') | Where-Object { Test-Path ('d:\erp_system\'+$_) }; if ($dirs) { $dirs -join ','; exit 1 } else { 'CACHE_MOVED' }"

- [ ] **Step 4: 移动 AI 工具残留目录到隔离区**
action: 在 d:\erp_system 下将 17 个 AI 工具/历史残留目录移动到 `.archive/cleanup-20260815/ai-tool-dirs/`：`.freebuff`、`.codeartsdoer`、`.codebuddy`、`.comate`、`.arts`、`.gstack`、`.lean-ctx`、`.learnings`、`.workbuddy`、`.agents`、`agents`、`skills`、`memory`、`shots`、`playbooks`、`cli`、`design-system`；另将 `dashboard-preview` 也移入该子目录。同时移动 3 个 AI 配置残留文件（`.claude.json`、`.windsurfignore`、`setup-claude-code.ps1`）到 `.archive/cleanup-20260815/root-files/`。
loop: false
verify:
  type: shell
  command: powershell -Command "$dirs=@('.freebuff','.codeartsdoer','.codebuddy','.comate','.arts','.gstack','.lean-ctx','.learnings','.workbuddy','.agents','agents','skills','memory','shots','playbooks','cli','design-system','dashboard-preview','.claude.json','.windsurfignore','setup-claude-code.ps1') | Where-Object { Test-Path ('d:\erp_system\'+$_) }; if ($dirs) { $dirs -join ','; exit 1 } else { 'AI_DIRS_MOVED' }"

- [ ] **Step 5: 移动打包残留到隔离区**
action: 在 d:\erp_system 下移动：`build/` 整目录 → `.archive/cleanup-20260815/build-artifacts/build`；`dist/ERP服务器管理器_v5.19.exe`、`dist/ERP服务器管理器_v5.20.1.exe`、`dist/dump.rdb` → `.archive/cleanup-20260815/build-artifacts/`。保留 `dist/ERP服务器管理器_v5.21.exe` 与 `dist/erp_project_path.txt` 不动。
loop: false
verify:
  type: shell
  command: powershell -Command "if ((Test-Path 'd:\erp_system\build') -or (Test-Path 'd:\erp_system\dist\dump.rdb') -or (Test-Path 'd:\erp_system\dist\ERP服务器管理器_v5.19.exe')) { exit 1 }; if (-not (Test-Path 'd:\erp_system\dist\ERP服务器管理器_v5.21.exe') -or -not (Test-Path 'd:\erp_system\dist\erp_project_path.txt')) { exit 2 }; 'BUILD_ARTIFACTS_OK'"

- [ ] **Step 6: 脚本与文档归位**
action: 在 d:\erp_system 下创建 `scripts/archive/`（若不存在），然后移动：11 个一次性诊断文件（`check_users.py`、`clear_business_data.py`、`diag_heads.py`、`diag_inv.py`、`reset_admin.py`、`verify_beile_data.py`、`validate_supreme_directive.py`、`apply_missing_ddl.py`、`apply_material_trgm_indexes.sql`、`start_production_optimized.py`、`_tmp_verify_user.py`）→ `scripts/archive/`；3 个运维工具（`restart_backend.py`、`switch_env.py`、`upload_nginx.py`）→ `scripts/`；2 个安全报告（`blue-team-security-review-20260605-001.md`、`red-team-vulnerability-report-20260605-001.md`）→ `docs/`。移动前若 `scripts/` 下已存在同名文件则保留隔离区路径 `.archive/cleanup-20260815/root-files/` 而非覆盖。
loop: false
verify:
  type: shell
  command: powershell -Command "$root=@('check_users.py','clear_business_data.py','diag_heads.py','diag_inv.py','reset_admin.py','verify_beile_data.py','validate_supreme_directive.py','apply_missing_ddl.py','apply_material_trgm_indexes.sql','start_production_optimized.py','_tmp_verify_user.py','restart_backend.py','switch_env.py','upload_nginx.py','blue-team-security-review-20260605-001.md','red-team-vulnerability-report-20260605-001.md') | Where-Object { Test-Path ('d:\erp_system\'+$_) }; if ($root) { $root -join ','; exit 1 }; if (-not (Test-Path 'd:\erp_system\scripts\archive\check_users.py') -or -not (Test-Path 'd:\erp_system\scripts\switch_env.py') -or -not (Test-Path 'd:\erp_system\docs\blue-team-security-review-20260605-001.md')) { exit 2 }; 'RELOCATED_OK'"

- [ ] **Step 7: 修正 .gitignore**
action: 读取 d:\erp_system\.gitignore 现有内容，查缺补漏追加以下模式（已存在的跳过）：`/*.log`、`/*.out`、`/*.err`、`/_vue_tsc_*.txt`、`/debug_*.png`、`/.coverage`、`.mypy_cache/`、`.pytest_cache/`、`.ruff_cache/`、`__pycache__/`、`/pytest-cache-files-*`、`/.tmp_analysis/`、`/build/`。保存前确认不误伤 `docs/`、`logs/` 下正常内容（规则用前导 `/` 锚定根目录）。
loop: false
verify:
  type: shell
  command: powershell -Command "git check-ignore -q uvicorn_restart.log; if ($LASTEXITCODE -ne 0) { exit 1 }; git check-ignore -q .coverage; if ($LASTEXITCODE -ne 0) { exit 1 }; 'GITIGNORE_OK'"

- [ ] **Step 8: pytest 收集验证**
action: 运行 pytest 测试收集（不执行测试），确认无 ImportError/CollectionError。若出现与本次文件移动无关的历史性收集错误，记录并继续（仅当错误指向被移动路径时视为失败）。
loop: until 收集成功或确认错误与清理无关
max_iterations: 3
verify:
  type: shell
  command: python -m pytest tests/ --collect-only -q 2>&1 | Select-Object -Last 5

- [ ] **Step 9: 启动 erp-prod 验证 /api/health 后恢复原状**
action: 通过 `Start-Service erp-prod` 启动后端，轮询 `http://127.0.0.1:5002/api/health`（最多 90 秒，每 5 秒一次）直到返回 200；记录响应体；验证通过后 `Stop-Service erp-prod` 恢复服务原有 stopped 状态（erp-arq 保持 stopped 不动；erp-redis 全程不动）。若健康检查失败：立即 Stop-Service 并从隔离区回滚被移动的 git 跟踪文件重试一次；仍失败则报告用户。
loop: until /api/health 返回 200
max_iterations: 3
verify:
  type: shell
  command: powershell -Command "Start-Service erp-prod; $ok=$false; 1..18 | ForEach-Object { Start-Sleep 5; try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:5002/api/health' -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -eq 200) { $ok=$true; $r.Content; break } } catch {} }; Stop-Service erp-prod -ErrorAction SilentlyContinue; if ($ok) { 'HEALTH_200_OK' } else { exit 1 }"

- [ ] **Step 10: git 提交本次清理变更**
action: 先输出 `git status --short` 变更摘要向用户展示，然后仅添加本次清理相关路径：`.gitignore`、`.archive/cleanup-20260815/`（若未被 ignore 则加入，隔离区应加入 .gitignore 排除规则 `/.archive/` 后不提交其内容）、`docs/designs/2026-08-15-project-cleanup-design.md`、`docs/plans/2026-08-15-project-cleanup-workflow.md`、`docs/blue-team-security-review-20260605-001.md`、`docs/red-team-vulnerability-report-20260605-001.md`、`scripts/archive/`、`scripts/restart_backend.py`、`scripts/switch_env.py`、`scripts/upload_nginx.py`，以及被移动原位置的删除记录（git add 对应旧路径）。绝不使用 `git add -A` 或 `git add .`（工作树存在 317 个存量未提交变更不得混入）。提交信息：`chore: 清理根目录垃圾文件并归档（隔离区过渡，详见 docs/designs/2026-08-15-project-cleanup-design.md）`。
loop: false
gate: human
verify:
  type: shell
  command: git log -1 --stat --format=%s | Select-Object -First 1

- [ ] **Step 11: 输出最终报告**
action: 生成清理报告：根目录清理前后文件数对比、隔离区完整清单（按子目录分组）、永久删除操作指引（确认系统运行 1-2 天后可删除 .archive/cleanup-20260815/）、回滚指引（按隔离区相对路径移回原位）。报告直接输出到对话，不创建额外文件。
loop: false
verify:
  type: human-review

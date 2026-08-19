---
intent: 执行代码质量评估报告中的 5 项 P0 修复（P0-1 多SKU仅出方案不动代码，P0-2 备份去重，P0-3 模板修复，P0-4 异常审计，P0-5 进度条颜色）
success_criteria: 全部 P0 步骤完成且验证通过；P0-1 产出设计文档；删除 backup _dir 冗余副本后无残留 import；MaterialView.vue aria-label 修复；batch_import_service 8 处静默异常加日志；8 处进度条颜色改为橙色；后端测试与前端构建通过
risk_level: medium
auto_approve: false
branch: hotl/p0-p1-fixes
worktree: false
dirty_worktree: allow
---

## Steps

- [ ] **Step 1: 编写多 SKU 迁移方案设计文档**
action: 在 docs/designs/2026-08-19-multi-sku-migration-design.md 编写设计文档。内容必须包含：1) 现状：OrderItem 模型已存在、Order.items 关系已就绪、order_batch_create.py 已按 SKU 写入；2) 13 处仍读"首 item 兼容值"的消费方清单（order_crud.py L693/L705、order.py L256、purchase_order_query.py L185/L466/L774/L871、order_batch_service.py L3、stock_service.py L491/L1407、approval_service.py L7/L321、order.py shared_models L32）；3) 每处的迁移方案（改为遍历 order.items）；4) 迁移顺序与回归测试计划；5) 待业务方确认的 spec 问题清单。不修改任何业务代码。
loop: false
verify:
  type: artifact
  path: docs/designs/2026-08-19-multi-sku-migration-design.md
  assert:
    kind: exists

- [ ] **Step 2: 删除 backup orchestration_dir 冗余副本**
action: 删除 D:\erp_system\fastapi_app\services\backup\orchestration_dir\ 目录（含 core.py、policy_service.py、recovery_test_service.py 三个文件，约 2044 行）。已确认系统实际使用 fastapi_app.services.backup.orchestration 无_dir版本，orchestration_dir 无任何 import 引用。
loop: false
verify:
  - type: shell
    command: Select-String -Path "fastapi_app\**\*.py" -Pattern "orchestration_dir" | Measure-Object
  - type: shell
    command: Test-Path "fastapi_app\services\backup\orchestration_dir"

- [ ] **Step 3: 删除 backup verify_dir 冗余副本**
action: 删除 D:\erp_system\fastapi_app\services\backup\verify_dir\ 目录（含 core.py、health_check_service.py、query_service.py 三个文件，约 955 行）。已确认系统实际使用 fastapi_app.services.backup.verify 无_dir版本，verify_dir 无任何 import 引用。
loop: false
verify:
  - type: shell
    command: Select-String -Path "fastapi_app\**\*.py" -Pattern "verify_dir" | Measure-Object
  - type: shell
    command: python -m pytest tests/test_backup.py fastapi_app/tests/test_backup_validation_helpers.py -q 2>&1 | Select-Object -Last 3

- [ ] **Step 4: 修复 MaterialView.vue 第 7 行 aria-label 污染**
action: 编辑 D:\erp_system\frontend-vite\src\views\material\MaterialView.vue 第 7 行，将 aria-label="来料进度 0' :class='['notification-badge', a" 修正为 aria-label="来料进度"。
loop: false
verify:
  type: shell
  command: (Get-Content "frontend-vite\src\views\material\MaterialView.vue")[6] | Select-String -Pattern 'aria-label="来料进度"'

- [ ] **Step 5: batch_import_service 静默异常加日志（数量/价格转换）**
action: 编辑 D:\erp_system\fastapi_app\services\batch_import_service.py，为以下 4 处静默异常块增加结构化日志（logger.warning + 行号上下文）：L195-198（initial_stock 转换失败返回0）、L200-203（price 转换失败返回0）、L254-259（订单数量转换失败 return False）、L341-346（备货数量转换失败 return False）。使用文件内已存在的 logger（如 from fastapi_app.core.logger import logger 或现有 import）。
loop: false
verify:
  type: shell
  command: python -m pytest tests/test_batch.py fastapi_app/tests/test_batch_import_service.py -q 2>&1 | Select-Object -Last 3

- [ ] **Step 6: batch_import_service 静默异常加日志（出货/导入行异常）**
action: 编辑 D:\erp_system\fastapi_app\services\batch_import_service.py，为以下 4 处异常块补充日志记录（若已有 logger 调用则补充 exc_info 或上下文信息）：L420-423（出货数量转换 return False）、L779-783（订单导入子函数 except）、L788-792（备货导入子函数 except）、L797-801（出货导入子函数 except）。
loop: false
verify:
  type: shell
  command: python -m pytest tests/test_batch.py -q 2>&1 | Select-Object -Last 3

- [ ] **Step 7: 进度条颜色修复（组件 + 产品模块）**
action: 编辑以下 3 个文件，将非完成状态进度条颜色从蓝色改为橙色：
1. D:\erp_system\frontend-vite\src\components\ui\UiProgressBar.vue L25：variant: 'primary' → variant: 'warning'
2. D:\erp_system\frontend-vite\src\views\product\components\BomEditor.vue L306：linear-gradient 蓝色渐变改为 var(--color-warning-400/600) 橙色渐变
3. D:\erp_system\frontend-vite\src\views\product\components\BomCopyDialog.vue L191：同上
loop: false
verify:
  type: shell
  command: Select-String -Path "frontend-vite\src\components\ui\UiProgressBar.vue" -Pattern "variant: 'warning'"

- [ ] **Step 8: 进度条颜色修复（外发模块）**
action: 编辑以下 2 个文件：
1. D:\erp_system\frontend-vite\src\views\outsource\components\OutsourceOrderTab.vue L337：var(--color-primary-400) → var(--color-warning-400)
2. D:\erp_system\frontend-vite\src\views\outsource\composables\useOutsourceProcess.ts L90：progressVariant(0) 返回 'primary' → 返回 'warning'
loop: false
verify:
  type: shell
  command: Select-String -Path "frontend-vite\src\views\outsource\composables\useOutsourceProcess.ts" -Pattern "return 'warning'"

- [ ] **Step 9: 进度条颜色修复（来料登记 + 出货计划）**
action: 编辑以下 3 个文件：
1. D:\erp_system\frontend-vite\src\views\material\components\ProgressTab.vue L234：var(--color-primary-500) → var(--color-warning-500)
2. D:\erp_system\frontend-vite\src\views\material\components\MaterialDetailDialog.vue L120：同上
3. D:\erp_system\frontend-vite\src\views\purchase-plan\components\PlanDetailCardList.vue L200：蓝色渐变改为橙色渐变
loop: false
verify:
  type: shell
  command: Select-String -Path "frontend-vite\src\views\purchase-plan\components\PlanDetailCardList.vue" -Pattern "warning"

- [ ] **Step 10: 后端全量测试验证**
action: 运行后端测试套件验证 P0 修复未引入回归。若测试时间过长，可先运行与改动相关的子集（tests/test_backup.py、tests/test_batch.py、fastapi_app/tests/test_batch_import_service.py），全量作为补充。
loop: false
verify:
  type: shell
  command: python -m pytest tests/test_backup.py tests/test_batch.py fastapi_app/tests/test_batch_import_service.py -q 2>&1 | Select-Object -Last 3

- [ ] **Step 11: 前端类型检查 + 构建验证**
action: 在 D:\erp_system\frontend-vite 运行 vue-tsc 类型检查（npm run type-check）。若通过，运行 npm run build 验证构建。修复任何因改动引入的 TS/模板错误。
loop: until type-check 与 build 均通过
max_iterations: 3
verify:
  type: shell
  command: npm run type-check 2>&1 | Select-Object -Last 5

- [ ] **Step 12: 人工验收检查点（P0 完成）**
action: 汇总 P0 修复结果：列出每个 P0 项的改动文件清单、验证结果、测试输出摘要。暂停等待用户验收后进入 P1 计划。
loop: false
gate: human
verify:
  type: human-review
  check: 用户确认 P0 修复可接受，再进入 P1 阶段

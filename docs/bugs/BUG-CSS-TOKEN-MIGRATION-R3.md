# BUG-CSS-TOKEN-MIGRATION-R3 修复记录

- **修复时间**: 2026-04-28 13:43:17
- **Git Commit**: 8bf683d5a796516bb7e7481406c2be0322cae1b7
- **根因分析**: CSS设计token覆盖率不足，13个视图文件中存在大量硬编码hex颜色值（~180个），4个视图文件重复实现showToast函数而非使用共享composable
- **影响范围**: frontend-vite/src 全部视图和组件
- **修复方案**:
  1. ProductListView.vue: 136个硬编码hex→CSS custom property tokens（Slate/Primary/Success/Warning/Danger/Ocean）
  2. ProductEditView.vue: 30个硬编码hex→CSS custom property tokens
  3. 4个文件（ApprovalView/BatchView/OcrImportView/PurchaseView）删除重复showToast函数，改用共享useToast composable
  4. 9个文件模板inline style中的hex值→var(--token)替换
  5. PendingOrdersPanel.vue JS gradient hex→var(--token)
  6. InventoryTab.vue #fff→var(--color-text-inverse) + 动态样式改用:class绑定
  7. app.css新增Slate色阶（50-700）和heading token
- **验证结果**: npm run build ✅ 通过，零SCSS残留，零legacy变量残留
- **Token覆盖率**: style section 100%, template inline 100%, JS/DOM 100%（print模板除外）
- **剩余可接受hex**: useSummaryModal.ts打印模板(13个)、useToast.ts运行时fallback(4个)

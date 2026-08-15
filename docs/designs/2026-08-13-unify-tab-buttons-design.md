---
design_type: feature
created_at: 2026-08-13
---

# 全系统 TAB 按钮样式统一为来料登记药丸样式

## Intent Contract

```
intent: 将全系统 4 处与来料登记(/material)不一致的 TAB 按钮样式，统一为来料登记「来料进度/历史查询」的药丸(pill)标签样式
constraints:
  - 不改变任何 TAB 的交互逻辑（点击切换、角标计数、路由跳转、mode 切换全部保留）
  - 不迁移到共享 UiTabs/UiTabTrigger 组件（采用局部 CSS/模板对齐，改动最小）
  - 不触碰已与目标一致的页面（Purchase/StockOut/Case/CustomerOrder/Report/Batch/PurchasePlan/SummaryModal/CaseStockTab/共享组件）
  - 仅改动 BackupView、CustomerView、ProductionToolbar、CreateShipmentPlanDialog 四处
success_criteria: 四处 TAB 渲染为白色内联药丸组（圆角 12px 容器 + 圆角 9px 按钮），激活态为蓝渐变+阴影，hover 为浅蓝底+蓝字，与来料登记一致
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run: npm run type-check（frontend-vite，确保模板结构改动不破坏类型）
  - run: npm run test（若涉及被测试组件）
  - check: 四处无残留旧样式类、无未使用样式
  - confirm: 浏览器分别打开 /material 与四处页面，TAB 视觉一致，切换逻辑正常
```

## Governance Contract

```
approval_gates:
  - 设计文档批准（本步骤）
rollback: git revert 对四处文件的样式与模板改动
ownership: 前端
```

## Scope

| In | Out |
|----|-----|
| 数据备份 BackupView.vue 的 TAB 条 | 共享组件重构 |
| 客户管理 CustomerView.vue 的新建客户按钮组 | 已一致的页面样式 |
| 生产报表 ProductionToolbar.vue 的 日报/月报 切换 | 后端/接口改动 |
| 出货计划弹窗 CreateShipmentPlanDialog.vue 的 填写/导入 切换 | HubeiView 确认状态胶囊（另行决策） |

## 统一的目标样式（源自 MaterialView `.mr-tab-btn` / UiTabTrigger `.ui-tab-btn`）

容器（药丸组）：
```css
.tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
```
按钮：
```css
.tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: background .3s ease, color .3s ease, box-shadow .3s ease, transform .3s ease;
}
.tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91,141,239,0.2);
  transform: translateY(-1px);
}
```

## Decisions

| # | 决定 | 说明 |
|---|------|------|
| 1 | 采用来料登记药丸样式作为统一基准 | 与共享 UiTabs/UiTabTrigger 完全一致，是全系统主流样式 |
| 2 | BackupView 新增药丸组包裹层 | 现有 `.bk-tab-bar` 为通栏，含右侧 `.bk-tab-actions`；将两个 TAB 按钮包进 `.bk-tab-group` 药丸组，actions 保留在栏内右侧 |
| 3 | CustomerView 单按钮同样套用药丸组 | 虽为单个「新建客户」按钮，仍切换到白色药丸组+渐变激活，保持视觉一致 |
| 4 | CSD 弹窗 TAB 切换为药丸样式 | 原 18px 实心渐变(白字)改为 13px 药丸（蓝渐变激活），与来料一致；保留 span 元素结构 |
| 5 | 仅做局部样式/模板改动 | 不动共享组件、不改交互逻辑、不改已一致页面 |

## Surface

- `frontend-vite/src/views/backup/BackupView.vue`：`.bk-tab-bar` 保持通栏；新增 `.bk-tab-group` 药丸组包裹两个按钮；`.bk-tab-btn`/`.bk-tab-active` 对齐药丸样式（补 justify-content、hover 阴影、渐变激活）。
- `frontend-vite/src/views/customer/CustomerView.vue`：`.cu-tabs` 灰底分段 → 白色药丸组；`.cu-tab-btn` 对齐药丸按钮（圆角 9px、完整 transition、hover、渐变激活）。
- `frontend-vite/src/views/production/components/ProductionToolbar.vue`：`.pr-tab-group` 灰底 → 白色药丸组；`.pr-tab`/`.pr-tab-active` 对齐药丸按钮。
- `frontend-vite/src/views/purchase-plan/components/CreateShipmentPlanDialog.vue`：`.csd-header-tabs` 灰底 → 白色药丸组；`.csd-htab`/`.csd-htab-active` 对齐药丸按钮（字号 18px→13px）。

## Risks & Open Questions

- 低风险：纯视觉样式调整，交互逻辑不变。
- 待定：HubeiView 左上角「未确认/已确认」滤镜为另一套胶囊样式（先前进度的设计），本次不纳入；如需一并统一可另行处理。
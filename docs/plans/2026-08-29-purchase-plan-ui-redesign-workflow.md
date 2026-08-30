---
intent: 按设计提案重构出货计划页面UI（每日卡片+月度汇总表格）
success_criteria: 所有组件修改完成，npm run build 通过
risk_level: low
auto_approve: true
---

## Steps

- [ ] **Step 1: 重构 purchase-plan-common.scss — 新增卡片/进度条/动画/状态颜色样式**
action: 在 purchase-plan-common.scss 中新增 day-card 状态变体（overdue/due-soon/completed/normal）、进度条（progress-bar）、卡片入场动画（staggered cardEntrance）、KPI 条、筛选标签、分页等样式
loop: false
verify: npm run build --prefix d:\erp_system\frontend-vite

- [ ] **Step 2: 扩展 types.ts — 新增 _status 字段和进度类型**
action: 在 types.ts 中为 PurchasePlanItem 新增 _status: 'overdue' | 'due-soon' | 'completed' | 'normal' 字段，以及进度相关类型
loop: false
verify: npx tsc --noEmit --project d:\erp_system\frontend-vite\tsconfig.json

- [ ] **Step 3: 重构 PurchasePlanDailyTab.vue — 卡片式每日计划**
action: 将每日计划改为卡片式布局，左边界彩色标识（红/橙/绿/蓝），显示客户名+数量列表，数量超标时折叠显示"+N 家客户"，支持级联入场动画
loop: false
verify: npm run build --prefix d:\erp_system\frontend-vite

- [ ] **Step 4: 重构 PurchasePlanMonthlySummary.vue — 表格新增进度条列**
action: 在月度汇总表格中新增"进度"列，显示颜色区分的进度条（绿/蓝/橙/红），完成100%显示绿色、0%显示红色
loop: false
verify: npm run build --prefix d:\erp_system\frontend-vite

- [ ] **Step 5: 重构 PurchasePlanToolbar.vue — 新增 KPI 进度条和月导航**
action: 工具栏新增 KPI 条（总计划/已出/剩余/进度），月导航改为独立 nav 组件，与搜索框同行排列
loop: false
verify: npm run build --prefix d:\erp_system\frontend-vite

- [ ] **Step 6: 重构 PurchasePlanView.vue — 新页面骨架和 tab 栏**
action: 替换页面骨架为 page-header + main-card 结构，tab 栏改为分组样式，新增背景点阵纹理
loop: false
verify: npm run build --prefix d:\erp_system\frontend-vite

- [ ] **Step 7: 最终构建验证**
action: 运行 npm run build 确认全部编译通过
loop: false
verify: npm run build --prefix d:\erp_system\frontend-vite
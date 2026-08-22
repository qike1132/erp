---
design_type: feature
created_at: 2026-08-20
---

# 移动端概览页 iOS 风格重构设计

## Intent Contract
```
intent: 将移动端概览页（DashboardMobile + 4 个卡片组件）按 iOS Human Interface Guidelines 重构：移除假状态栏、emoji 图标换 SF Symbol 风格 SVG、核心指标 Hero 置顶 + 分组卡片、iOS hairline 分隔、新增下拉刷新
constraints: 不改后端/API/数据模型；不引入新依赖；仅浅色；复用 --m-* 设计令牌与现有数据组合式函数
success_criteria: 手机端概览页呈现 iOS 质感；下拉刷新可用；核心指标置顶、分组清晰；构建通过
risk_level: low
```

## Verification Contract
```
verify_steps:
  - run tests: 无相关单测，跳过
  - check: npm run build 通过；dev/prod 页面能渲染新概览
  - confirm: 手机端查看：假状态栏已移除、无 emoji 图标、核心 Hero 置顶、分组卡片 + hairline、下拉刷新触发刷新
```

## Governance Contract
```
approval_gates: 设计确认（已通过） → 实现后手机端视觉验收
rollback: git checkout 还原 src/mobile/views/dashboard/ 下改动文件
ownership: 前端（我执行，用户验收）
```

## Scope

| In | Out |
| --- | --- |
| 重写 DashboardMobile.vue（模板/样式/下拉刷新） | 修改后端 /dashboard/mobile API |
| 重构 4 个卡片组件为 iOS 风格（SVG 图标 + 分组 + hairline） | 改动其它移动端页面 |
| 核心 Hero 置顶 + 分组信息层级 | 深色模式 / 多主题 |
| 下拉刷新 + 按压反馈 + 入场动效 | 引入新依赖 |
| useDashboardMobileData 增加下拉刷新状态 | 改动 Tab Bar / 布局 |

## Decisions

| # | 决策 | 理由 / 备选 |
| --- | --- | --- |
| 1 | 移除假系统状态栏（时间/信号/电池） | 真机自带状态栏，模拟显廉价（iOS 应用不在 Web 内伪造状态栏） |
| 2 | emoji 图标 → SF Symbol 风格线性 SVG | 大厂质感核心；描边 1.8 + Apple 语义色 + tinted 圆角方盒 |
| 3 | 核心 Hero（今日订单/今日总产值）置顶 + 分组卡 | 用户选定「核心置顶+分组」，一眼看重点 |
| 4 | iOS hairline 分隔线 rgba(60,60,67,0.29) + 分节小标题 | 贴合 iOS Grouped Table View |
| 5 | 下拉刷新（scrollTop=0 手势）+ 保留按钮 | 用户选定「下拉刷新+按钮」 |
| 6 | 仅浅色 | 用户选定「暂只做浅色」 |

## Surface

**组件**：
- `src/mobile/views/dashboard/DashboardMobile.vue` — 整体重写模板与样式；新增下拉刷新逻辑（监听 `.m-layout-content` 滚动容器 touch 事件）
- `src/mobile/views/dashboard/components/OrderOverviewCard.vue` — iOS 风格化（SVG 图标 + 指标）
- `src/mobile/views/dashboard/components/StockOverviewCard.vue` — iOS 分组行式
- `src/mobile/views/dashboard/components/ProductionDeptCard.vue` — 大数字 + 部门排行 + hairline
- `src/mobile/views/dashboard/components/WarehouseCard.vue` — 2×2 宫格 + SVG 图标
- `src/mobile/views/dashboard/composables/useDashboardMobileData.ts` — 增加 `refreshing` 状态与 `onPullRefresh` 封装（数据逻辑不变）

**样式令牌**：页面边距 16 / 卡片圆角 20 / 卡片内 20 / 分组间距 24 / 行距 12；字体 Large Title 34·Headline 17·Caption 13·Footnote 11；分隔 hairline 0.5px；阴影 0 1px 3px + 0 4px 12px。

**交互**：下拉刷新（橡皮筋 + 旋转指示器 + 弹簧回弹）；`prefers-reduced-motion` 时禁用入场与刷新动画；卡片错峰入场（保留）。

## Risks & Open Questions

- 下拉刷新依赖 `.m-layout-content` 作为滚动容器（MobileLayout 已实现 overflow-y:auto）；需在 touchstart/touchmove/touchend 中处理，避免与页面滚动冲突。
- 低风险：仅前端 UI 重构，数据层不变。

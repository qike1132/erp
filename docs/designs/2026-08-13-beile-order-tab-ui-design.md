---
design_type: feature
created_at: 2026-08-13
---

# 湖北订单页确认状态 TAB 样式对齐板房管理

## Intent Contract

```
intent: 将 /beile-order 页面左上角「未确认/已确认」状态切换从分段式样式改为与板房管理(RoleTabs)一致的胶囊标签样式
constraints:
  - 不改变 TAB 交互逻辑（confirmStatus 读写、setConfirmStatus、角标计数 unconfirmedCount 全部保留）
  - 不改动 BeileOrderTab.vue、HubeiSearchBar.vue 与后端逻辑
  - 仅修改 HubeiView.vue 的 .bo-confirm-filter 相关样式与模板结构
success_criteria: 未确认/已确认 渲染为独立圆角胶囊，激活态为蓝色渐变+阴影+白字，hover 为蓝边浅蓝底；未确认角标正常显示
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run: npm run type-check（frontend-vite）
  - check: HubeiView.vue 无未使用样式残留、模板绑定正确
  - confirm: 页面 /beile-order 顶部 TAB 呈现胶囊样式，切 TAB 仍触发确认状态筛选
```

## Governance Contract

```
approval_gates:
  - 设计文档批准（本步骤）
rollback: git revert 对 HubeiView.vue 的样式与模板改动
ownership: 前端
```

## Scope

| In | Out |
|----|-----|
| HubeiView.vue 的确认状态 TAB 模板与样式 | BeileOrderTab.vue 逻辑 |
| 胶囊样式（圆角、渐变激活态、hover） | 后端/接口改动 |
| 保留未确认角标计数 | 其他页面样式 |

## Decisions

| # | 决定 | 说明 |
|---|------|------|
| 1 | 采用 RoleTabs 胶囊视觉 | 独立圆角胶囊，激活态蓝渐变+阴影，对齐板房管理 |
| 2 | 保留角标计数 | 未确认数量徽章在激活/非激活态下分别适配配色 |
| 3 | 仅动 HubeiView.vue | 结构与样式集中在此文件，改动最小 |

## Surface

- `frontend-vite/src/views/hubei/HubeiView.vue`：将 `.bo-confirm-filter-seg`（内联分段容器）改为独立胶囊列表；`.bo-confirm-filter-btn` 改为圆角胶囊并新增激活态渐变/阴影、hover 态。

## Risks & Open Questions

- 无高风险；仅视觉样式调整，逻辑不变。

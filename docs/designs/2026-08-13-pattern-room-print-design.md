---
design_type: feature
created_at: 2026-08-13
---

# 板房打样单打印功能设计

## Intent Contract

```
intent: 在板房管理（/pattern-room）页面为当前选中的打样产品新增「打印打样单」功能：
        一键打印该产品已录入的全部部位明细（部位名称/版本/供应商/布料名称/色号），
        打印内容同时包含产品图片与产品名称、编号、客户等抬头信息。
constraints:
  - 页面路由 /pattern-room 与现有布局不变
  - 不改动后端接口与数据模型，仅纯前端打印
  - 打印数据复用现有 partHook.partsByVersion（当前角色全部部位+全部版本）与 projectHook.currentProject
  - 遵循简约原则：仅新增打印入口与打印视图，不做 PDF/图片导出、历史记录等额外能力
  - 打印视图仅影响打印输出，屏幕浏览界面保持现状
success_criteria:
  - 前端 npm run type-check / test / build 全部通过
  - 顶部操作栏出现「打印打样单」按钮，仅当已选中产品且该产品有部位数据时可点击
  - 点击后弹出打印预览，内容包含：产品图片、产品名称/编号/客户抬头、部位明细表格（部位名称/版本/供应商/布料名称/色号）
  - 打印预览中其余页面元素（左侧列表、按钮、弹窗）不显示
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests (frontend): npm run type-check && npm run test
  - run build: npm run build
  - check: 顶部出现「打印打样单」按钮；未选中产品或无部位时禁用/提示
  - check: 点击后出现打印弹窗，含产品图片与部位明细表格，数据与详情面板一致
  - check: 打印样式（@media print）下仅显示打样单内容，按钮与其余界面隐藏
  - confirm: 无 P0/P1 编译错误；既有测试全部通过
```

## Governance Contract

```
approval_gates:
  - 设计文档批准（本次）
  - 实现计划（writing-plans）批准
  - 合并前 code-review
rollback: 纯前端改动，仅移除打印按钮、弹窗组件与相关样式即可整体还原；不涉及迁移与后端
ownership: 板房/打样模块负责人
```

## Scope

| In | Out |
| --- | --- |
| 新增打印弹窗组件（产品图片 + 抬头 + 部位明细表格） | PDF / 图片文件导出下载 |
| 顶部操作栏「打印打样单」按钮与点击逻辑 | 打印历史记录、批量打印、模板自定义 |
| `@media print` 打印样式（仅显示打样单） | 后端接口改动、数据模型改动 |
| 打印数据由现有 hook 提供（不新增接口） | 非当前角色的部位数据打印 |

## Decisions

| # | 决策 | 选择 | 被否方案 |
| --- | --- | --- | --- |
| D1 | 打印入口位置 | 顶部操作栏按钮（右上角，与「新建打样」「录入信息」同级） | 详情面板内按钮 |
| D2 | 打印内容范围 | 当前角色全部部位 + 全部版本（复用 partsByVersion 扁平数据） | 仅最终版本 |
| D3 | 打印实现方式 | 浏览器打印（window.print）+ 打印专用弹窗视图 | 生成图片/PDF 下载 |
| D4 | 打印数据来源 | 复用现有 hook 数据（不新增后端接口） | 新增打印专用接口 |
| D5 | 打印视图载体 | 独立 PrintDialog 组件，屏幕显示弹窗预览，打印时仅输出内容区 | 直接打印整个页面（会带出侧栏/按钮） |

## Surface

**前端组件**（`frontend-vite/src/views/pattern-room/components/`）：
- 新增 `PrintDialog.vue`：接收 `project`（产品图片/名称/编号/客户）与 `parts`（部位明细），渲染打样单内容；`@media print` 下隐藏弹窗外壳与按钮，仅打印内容区。
- 修改 `PatternRoomView.vue`：顶部操作栏新增「打印打样单」按钮；引入 `PrintDialog`；点击后基于 `projectHook.currentProject.value` 与 `partHook.partsByVersion.value` 组装数据并打开弹窗。

**类型**：复用 `@/api/patternRoom` 的 `ProjectDetailResponse`、`PartDetail`，不新增类型。

## Risks & Open Questions

- 打印时产品图片跨域/加载：产品图片为内部文件地址，打印由浏览器原生处理，若加载失败打印视图显示占位；不影响表格数据。
- partsByVersion 为空（未录入部位）：打印按钮禁用或点击提示「暂无部位数据」，不打开空弹窗。
- 多角色：partsByVersion 已按当前角色过滤，打印即当前角色数据；若需按角色分别打印，用户可切换角色后再打印。

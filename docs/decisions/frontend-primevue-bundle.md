# 前端 PrimeVue 包体评估

## 结论

保留 PrimeVue，但不接受当前 672KB 单一 `vendor-primevue` 包作为长期形态。

## 事实

- 构建产物：`vendor-primevue-*.js` 约 672KB。
- 引用来源：
  - `UiDataTable`：15 个 Vue 文件。
  - `UiAutocomplete`：7 个 Vue 文件。
  - `UiDrawer`：4 个 Vue 文件。
  - `UiDateRangePicker`：2 个 Vue 文件。
- 深度使用集中在共享表格、自动补全、抽屉和日期区间，不是低收益场景。

## 建议路线

1. **短期**：修改 `vite.config.ts` 的 `manualChunks`，不再把整个 `primevue` 打成一个入口包，允许 Vite 按实际模块拆分。
2. **中期**：审计 `main.ts` 中的 `primevue/config` 全局初始化，确认样式、语言与 PT 配置是否可以延迟到首个 PrimeVue 组件加载。
3. **中期**：将低频组件改为异步组件，优先 `UiDateRangePicker`、`UiDrawer`、`UiAutocomplete`。
4. **谨慎项**：`UiDataTable` 使用面广，不建议与组件库替换混在同一批变更中。

## 验收指标

- 首屏关键 JS 传输体积下降，并记录优化前后数字。
- 核心表格页、移动端订单页、板房页 E2E 或手动回归通过。
- `npm run build` 与 `npm run test` 均通过。
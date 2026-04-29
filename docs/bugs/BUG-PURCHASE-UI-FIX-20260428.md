# BUG-PURCHASE-UI-FIX-20260428 修复记录

- **修复时间**: 2026-04-28 21:37:53
- **Git Commit**: 8bf683d5a796516bb7e7481406c2be0322cae1b7
- **根因分析**:
  1. P0: UiCheckbox.vue 传 :checked/@update:checked 给 reka-ui CheckboxRoot，但后者使用 modelValue/update:modelValue，导致全选和行内选择均失效
  2. P0: completeOrder API 发送 { id } 但后端 OrderIdRequest 期望 { order_id }，导致422错误
  3. P1: ActiveOrdersPanel 显示 o.order_date(仅日期)而非 o.create_time(含时分)
  4. P2: batchComplete 在 clearSelection() 后引用 selectedIds.value.length(始终0)
- **影响范围**: 采购中心审核订单和采购中订单两个模块的所有交互功能
- **修复方案**:
  1. UiCheckbox.vue: :checked -> :model-value, @update:checked -> @update:model-value, 加类型转换 ( === true)
  2. api/index.ts: { id } -> { order_id: id }
  3. ActiveOrdersPanel.vue: o.order_date -> o.create_time || o.order_date
  4. usePurchaseOrders.ts: 在 clearSelection() 前捕获 count
- **验证结果**:
  - Vite build 成功
  - API 测试: order_id字段返回404(正确), id字段返回422(旧bug确认)
  - create_time 字段正确返回 "2026-04-28 21:11"
  - bandit 0高危

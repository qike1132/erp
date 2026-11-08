<template>
  <div class="bb-group" :class="{ 'bb-group--compact': compact }">
    <label class="bb-check" :for="`${prefix}-is-blind-box`">
      <input
        :id="`${prefix}-is-blind-box`"
        v-model="model.isBlindBox"
        type="checkbox"
        class="bb-checkbox"
        :name="`${prefix}-is-blind-box`"
      />
      盲盒
    </label>
  </div>
  <template v-if="model.isBlindBox">
    <div class="bb-group" :class="{ 'bb-group--compact': compact }">
      <label class="bb-check" :for="`${prefix}-has-hidden-role`">
        <input
          :id="`${prefix}-has-hidden-role`"
          v-model="model.hasHiddenRole"
          type="checkbox"
          class="bb-checkbox"
          :name="`${prefix}-has-hidden-role`"
        />
        该 SKU 有隐藏款
      </label>
    </div>
    <div class="bb-group" :class="{ 'bb-group--compact': compact }">
      <label class="bb-label" :for="`${prefix}-hidden-carton-ratio`">盲盒隐藏款装箱配比</label>
      <div class="bb-input-wrap">
        <FontAwesomeIcon icon="box-open" class="bb-input-icon" aria-hidden="true" />
        <input
          :id="`${prefix}-hidden-carton-ratio`"
          v-model.number="model.hiddenCartonRatio"
          type="number"
          class="bb-input"
          step="1"
          min="1"
          :max="HIDDEN_CARTON_RATIO_MAX"
          placeholder="例如：72"
          :name="`${prefix}-hidden-carton-ratio`"
          autocomplete="off"
          :disabled="!model.hasHiddenRole"
          :aria-describedby="`${prefix}-hidden-carton-ratio-hint`"
        />
      </div>
      <small :id="`${prefix}-hidden-carton-ratio-hint`" class="bb-hint">
        每多少个订单数量配 1 个隐藏款（如 72，即 10000÷72≈139 个）；留空表示不额外配隐藏款。
        有隐藏款时：常规角色按「订单数量 ÷ 常规角色数」均分（常规 4 款 → 10000÷4），隐藏款额外按配比计算；
        无隐藏款时：订单数量按「订单数量 ÷ 角色数量」均分。BOM 需恰有 1 个隐藏款角色（右键指定或精确命名为「隐藏款」）。
      </small>
    </div>
  </template>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { HIDDEN_CARTON_RATIO_MAX, type BlindBoxForm } from '../composables/useProductBlindBox'

defineProps<{
  /** 表单实例前缀：保证新增/编辑两个表单的 input id/name 不冲突 */
  prefix: string
  /** 紧凑模式（编辑弹窗网格内使用，组间距由父级 gap 控制） */
  compact?: boolean
}>()

// 与 StockOutInputForm 同款：表单对象用 defineModel 双向绑定（ESLint
// vue/no-mutating-props 禁止子组件直接改 prop 对象的字段）
const model = defineModel<BlindBoxForm>({ required: true })

/** 父开关关闭时清空全部子配置（后端也会归一，这里保证 UI 一致） */
function clearChildren() {
  model.value.hasHiddenRole = false
  model.value.hiddenCartonRatio = null
}

// 取消「有隐藏款」→ 清空配比，避免禁用输入框里残留旧值被误提交
watch(() => model.value.hasHiddenRole, (has) => {
  if (!has) model.value.hiddenCartonRatio = null
})

// 关闭盲盒 → 连带清空子配置
watch(() => model.value.isBlindBox, (on) => {
  if (!on) clearChildren()
})
</script>

<style scoped>
.bb-group { margin-bottom: 16px; }
.bb-group--compact { margin-bottom: 0; }
.bb-check {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; color: var(--color-text-primary, #111827);
  cursor: pointer; user-select: none;
}
.bb-checkbox {
  width: 16px; height: 16px; margin: 0;
  accent-color: var(--color-primary-600, #2563eb);
  cursor: pointer;
}
.bb-label {
  display: block; margin-bottom: 6px;
  font-size: 13px; font-weight: 500;
  color: var(--color-text-secondary, #4b5563);
}
.bb-input-wrap { position: relative; }
.bb-input-icon {
  position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
  color: var(--color-text-muted, #9ca3af); font-size: 14px;
}
/* 边框用 #8592a3（3.16:1，满足非文本对比度）；不用 --color-border-light
   （#e2e8f0 仅 1.2:1，会跌破 WCAG 输入框边界要求） */
.bb-input {
  width: 100%; box-sizing: border-box;
  padding: 8px 12px 8px 36px;
  color: var(--color-text);
  background: white;
  border: 2px solid #8592a3; border-radius: 10px;
  font-size: 14px; font-family: inherit; line-height: 1.5;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}
.bb-input:focus {
  background: white;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
/* 编辑弹窗的 .pd-input 是 16px / 11px 14px / radius 12，紧凑模式跟随，避免同排不同高 */
.bb-group--compact .bb-input { padding: 11px 14px 11px 40px; font-size: 16px; border-radius: 12px; }
.bb-group--compact .bb-input-icon { left: 14px; }
.bb-input:disabled { background: #f3f4f6; cursor: not-allowed; color: #6b7280; }
.bb-hint {
  display: block; margin-top: 6px;
  color: var(--color-text-secondary); font-size: 12px; line-height: 1.5;
}
</style>

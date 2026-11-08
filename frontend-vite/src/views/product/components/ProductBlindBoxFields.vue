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
          max="1000000"
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

export interface BlindBoxForm {
  isBlindBox: boolean
  hasHiddenRole: boolean
  hiddenCartonRatio: number | null | ''
}

defineProps<{
  /** 表单实例前缀：保证新增/编辑两个表单的 input id/name 不冲突 */
  prefix: string
  /** 紧凑模式（编辑弹窗网格内使用，组间距由父级 gap 控制） */
  compact?: boolean
}>()

const model = defineModel<BlindBoxForm>({ required: true })

// 取消「有隐藏款」→ 清空配比，避免禁用输入框里残留旧值被误提交
watch(() => model.value.hasHiddenRole, (has) => {
  if (!has) model.value.hiddenCartonRatio = null
})

// 关闭盲盒 → 连带清空子配置（后端也会归一，这里保证 UI 一致）
watch(() => model.value.isBlindBox, (on) => {
  if (!on) {
    model.value.hasHiddenRole = false
    model.value.hiddenCartonRatio = null
  }
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
.bb-input {
  width: 100%; box-sizing: border-box;
  padding: 10px 12px 10px 36px;
  border: 1px solid #8592a3; border-radius: 10px;
  font-size: 14px; font-family: inherit;
}
.bb-input:disabled { background: #f3f4f6; cursor: not-allowed; color: #6b7280; }
.bb-hint {
  display: block; margin-top: 6px;
  color: var(--color-text-secondary); font-size: 12px; line-height: 1.5;
}
</style>

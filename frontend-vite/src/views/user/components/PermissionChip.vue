<template>
  <!-- interactive=false 时退化为纯视觉胶囊（点击穿透给外层整行） -->
  <component
    :is="interactive ? 'button' : 'span'"
    class="pd-op"
    :class="{ on: checked, static: !interactive }"
    :type="interactive ? 'button' : undefined"
    :aria-pressed="interactive ? checked : undefined"
    @click="interactive && $emit('toggle')"
  >
    <PermissionCheckBox :state="checked ? 'all' : 'none'" :label="label" :interactive="false" />
    <slot>{{ checked ? '已授权' : '未授权' }}</slot>
  </component>
</template>

<script setup lang="ts">
/**
 * PermissionChip.vue — 权限「开关胶囊」
 *
 * 分配权限弹窗统一的开关外观：勾选框 + 文案。
 * - 默认文案随状态变（已授权 / 未授权），用于「一行一项」的权限行；
 * - 也可用默认插槽换成动作词（TAB 行传「编辑」「删除」）。
 * - `interactive=false` 退化为纯视觉（`pointer-events:none`），供「整行可点」的行使用。
 */
import PermissionCheckBox from '@/views/user/components/PermissionCheckBox.vue'

withDefaults(
  defineProps<{
    /** 是否已勾选 */
    checked: boolean
    /** 供读屏器使用的名称 */
    label: string
    /** 是否可独立点击（false = 纯视觉，点击穿透给外层行） */
    interactive?: boolean
  }>(),
  { interactive: true },
)

defineEmits<{ toggle: [] }>()
</script>

<style scoped>
.pd-op {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
  padding: 4px 12px 4px 8px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 999px;
  background: #fff;
  font-size: 12.5px;
  color: var(--color-text-secondary);
  cursor: pointer;
}
button.pd-op:hover {
  border-color: var(--color-primary-300);
}
.pd-op.on {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  color: var(--color-primary-700);
  font-weight: 600;
}
.pd-op.static {
  pointer-events: none;
}
</style>

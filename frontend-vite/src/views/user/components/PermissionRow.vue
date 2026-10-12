<template>
  <div
    class="pd-row"
    :class="{ on: checked }"
    role="checkbox"
    :aria-checked="checked"
    tabindex="0"
    @click="$emit('toggle')"
    @keydown.enter.prevent="$emit('toggle')"
    @keydown.space.prevent="$emit('toggle')"
  >
    <PermissionCheckBox :state="checked ? 'all' : 'none'" :label="item.name" :interactive="false" />
    <span class="pd-row-name">{{ item.name }}</span>
    <code class="pd-code">{{ item.code }}</code>
  </div>
</template>

<script setup lang="ts">
/**
 * PermissionRow.vue — 分配权限弹窗右栏的一行权限
 *
 * 整行可点（勾选框为纯指示器，点击穿透给整行）；`checked` 决定高亮与 aria。
 */
import type { PermissionItem } from '@/types'
import PermissionCheckBox from '@/views/user/components/PermissionCheckBox.vue'

defineProps<{
  /** 该行对应的权限 */
  item: PermissionItem
  /** 是否已勾选 */
  checked: boolean
}>()

defineEmits<{ toggle: [] }>()
</script>

<style scoped>
.pd-row {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-bottom: 7px;
  padding: 9px 12px;
  border: 1px solid var(--color-border-light, #f0f2f5);
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
}
.pd-row:hover {
  border-color: var(--color-primary-200);
  background: var(--color-primary-50);
}
.pd-row.on {
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
}
.pd-row-name {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--color-text);
}
.pd-row.on .pd-row-name {
  color: var(--color-primary-700);
}
.pd-code {
  flex: none;
  padding: 3px 7px;
  border: 1px solid var(--color-border-light, #f0f2f5);
  border-radius: 6px;
  background: var(--color-slate-50, #f8fafc);
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
  color: var(--color-text-placeholder, #94a3b8);
}
</style>

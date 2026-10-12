<template>
  <span
    class="pd-box"
    :class="[state, { static: !interactive }]"
    :role="interactive ? 'checkbox' : undefined"
    :aria-checked="interactive ? ariaChecked : undefined"
    :aria-label="interactive ? label : undefined"
    :aria-hidden="interactive ? undefined : 'true'"
    :tabindex="interactive ? 0 : -1"
    @click.stop="onToggle"
    @keydown.enter.prevent.stop="onToggle"
    @keydown.space.prevent.stop="onToggle"
  />
</template>

<script setup lang="ts">
/**
 * PermissionCheckBox.vue — 权限三态勾选框
 *
 * 三态：全选（对勾）/ 半选（横杠）/ 未选（空框）。
 * `interactive=false` 退化为纯指示器（不参与 Tab、`pointer-events:none` 让点击穿透），
 * 供「整行可点」的右栏权限行使用；左栏模块行则用默认的独立交互。
 * 纯指示器模式**不挂 role/aria**（`aria-hidden`）——它总被放进本身已带
 * `role="checkbox"` 的行或 `<button>` 里，再挂一个复选框角色会变成控件套控件，
 * 读屏器重复播报。
 */
import { computed } from 'vue'
import type { PermissionCheckState } from '@/views/user/composables/useUserManagement'

const props = withDefaults(
  defineProps<{
    state: PermissionCheckState
    /** 供读屏器使用的名称 */
    label: string
    /** 是否可独立交互（false = 纯指示器，点击穿透给外层行） */
    interactive?: boolean
  }>(),
  { interactive: true },
)

const emit = defineEmits<{ toggle: [] }>()

/** 三态 → aria-checked */
const ariaChecked = computed(() =>
  props.state === 'all' ? 'true' : props.state === 'none' ? 'false' : 'mixed',
)

function onToggle() {
  if (props.interactive) emit('toggle')
}
</script>

<style scoped>
.pd-box {
  width: 15px;
  height: 15px;
  flex: none;
  border: 1.6px solid var(--color-border-strong, #cbd5e1);
  border-radius: 4px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.pd-box.static {
  cursor: default;
  pointer-events: none;
}
.pd-box.all,
.pd-box.on {
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
}
.pd-box.all::after,
.pd-box.on::after {
  content: '';
  width: 3px;
  height: 7px;
  border: solid #fff;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg) translate(-1px, -1px);
}
.pd-box.partial {
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
}
.pd-box.partial::after {
  content: '';
  width: 8px;
  height: 2px;
  border-radius: 1px;
  background: #fff;
}
</style>

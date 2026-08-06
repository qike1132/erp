<script setup lang="ts">
/**
 * UiDrawer — 侧边抽屉面板
 *
 * 基于 PrimeVue Drawer，统一所有侧边详情/编辑面板。
 * 消除 PlanDetailDrawer.vue 的 468 行自建 UI 代码。
 *
 * Props:
 *   visible       - 控制显示/隐藏
 *   position      - 'left' | 'right' | 'top' | 'bottom'（默认 'right'）
 *   title         - 标题文本
 *   width         - 宽度（仅 left/right，默认 '520px'）
 *
 * Emits:
 *   update:visible - 双向绑定
 *
 * Slots:
 *   default  - 抽屉内容
 *   header   - 自定义头部（可选，覆盖默认 title）
 *   footer   - 底部操作区（可选）
 *
 * 示例：
 *   <UiDrawer v-model:visible="showDrawer" title="订单详情">
 *     <OrderDetail :order="selected" />
 *     <template #footer>
 *       <UiButton @click="showDrawer = false">关闭</UiButton>
 *     </template>
 *   </UiDrawer>
 */
import { Drawer } from 'primevue'

withDefaults(
  defineProps<{
    visible: boolean
    position?: 'left' | 'right' | 'top' | 'bottom'
    title?: string
    width?: string
  }>(),
  {
    position: 'right',
    title: '',
    width: '520px',
  },
)

defineSlots<{
  default: () => unknown
  header: () => unknown
  footer: () => unknown
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

function onHide() {
  emit('update:visible', false)
}
</script>

<template>
  <Drawer
    :visible="visible"
    :position="position"
    :style="{ width }"
    :showCloseIcon="true"
    :dismissable="true"
    :closeOnEscape="true"
    @update:visible="onHide"
  >
    <!-- 头部 -->
    <template #header>
      <slot name="header">
        <span class="text-lg font-bold text-heading">{{ title }}</span>
      </slot>
    </template>

    <!-- 内容 -->
    <slot />

    <!-- 底部 -->
    <template v-if="$slots.footer" #footer>
      <slot name="footer" />
    </template>
  </Drawer>
</template>

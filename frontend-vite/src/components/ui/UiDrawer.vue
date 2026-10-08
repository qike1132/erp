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
// 按组件深导入（PrimeVue 官方推荐写法），显式声明依赖
import Drawer from 'primevue/drawer'
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    visible: boolean
    position?: 'left' | 'right' | 'top' | 'bottom'
    title?: string
    width?: string
    /** 居中面板（如宽表格明细），而不是贴边抽屉。此时 width 作为最大宽度。 */
    centered?: boolean
  }>(),
  {
    position: 'right',
    title: '',
    width: '520px',
    centered: false,
  },
)

/**
 * 居中模式走 PrimeVue 的 `center` 定位：mask 是 flex 容器，主题的 inline style 会对
 * 未知 position 用 justify/align = center，于是面板落在屏幕正中（见 primevue-pt 的 drawer.root）。
 */
const drawerPosition = computed(() => (props.centered ? 'center' : props.position))

/**
 * 宽度：居中模式当作 max-width（面板用 w-[95%] 自适应）；左右抽屉是固定 width；
 * 上下抽屉固定占满宽度（见 primevue-pt 的 drawer.root），不套用 width，否则会被默认 520px 压窄。
 */
const panelStyle = computed(() => {
  if (props.centered) return { maxWidth: props.width }
  return props.position === 'left' || props.position === 'right' ? { width: props.width } : undefined
})

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
    :position="drawerPosition"
    :style="panelStyle"
    :show-close-icon="true"
    :dismissable="true"
    :close-on-escape="true"
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

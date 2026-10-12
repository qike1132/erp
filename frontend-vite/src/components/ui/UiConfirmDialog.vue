<template>
  <UiDialog
    :open="open"
    :sr-title="text"
    :description="sub || text"
    max-width-class="max-w-[420px]"
    :close-on-overlay-click="closeOnOverlayClick"
    :overlay-z-class="overlayZClass"
    :content-z-class="contentZClass"
    @update:open="onOpenUpdate"
  >
    <div class="p-8">
      <div :class="['w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-4 text-2xl', iconBgClass]">
        <FontAwesomeIcon :icon="iconName" aria-hidden="true" />
      </div>
      <div class="text-center text-base text-text mb-2">
        {{ text }}
      </div>
      <div v-if="sub" class="text-center text-sm text-text-secondary">
        {{ sub }}
      </div>
    </div>
    <template #footer>
      <UiButton variant="outline" :aria-label="cancelLabel" @click="$emit('cancel')"> 取消 </UiButton>
      <UiButton :variant="confirmVariant" :aria-label="confirmLabel" @click="$emit('confirm')"> 确认 </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiDialog from './UiDialog.vue'
import UiButton from './UiButton.vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    text: string
    sub?: string
    type?: 'danger' | 'warning'
    /** 点击遮罩/空白处是否关闭弹窗（默认 true） */
    closeOnOverlayClick?: boolean
    /**
     * 嵌套于另一模态（如抽屉）之上时的 z 层级类名。
     * 不传则沿用 UiDialog 的默认层级（overlay 30 / modal 40）—— 既有调用方行为不变；
     * 需要在抽屉之上显示时传 'z-[var(--z-overlay-nested)]' / 'z-[var(--z-modal-nested)]'。
     */
    overlayZClass?: string
    contentZClass?: string
  }>(),
  {
    type: 'danger',
    closeOnOverlayClick: true,
    // 显式声明为 undefined：转发给 UiDialog 后由其自身默认值兜底（不改变既有层级）。
    overlayZClass: undefined,
    contentZClass: undefined,
    sub: undefined,
  },
)

const emit = defineEmits<{
  'update:open': [value: boolean]
  confirm: []
  cancel: []
}>()

function onOpenUpdate(val: boolean) {
  emit('update:open', val)
  if (!val) emit('cancel')
}

const iconBgClass = computed(() =>
  props.type === 'danger' ? 'bg-danger-50 text-danger-500' : 'bg-warning-50 text-warning-500',
)

const iconName = computed(() => (props.type === 'danger' ? 'trash-alt' : 'triangle-exclamation'))

const confirmVariant = computed(() => (props.type === 'danger' ? 'danger' : 'primary'))

/**
 * 两个按钮的可访问名必须互不相同并带上下文语境。
 * 可见文字「取消 / 确认」本身够用，但一旦被上层统一覆盖就会退化成同名按钮，
 * 读屏器用户将无法区分——这里显式带上问句，保证任何情况下都可辨认。
 */
const cancelLabel = computed(() => `取消，${props.text}`)
const confirmLabel = computed(() => `确认，${props.text}`)
</script>

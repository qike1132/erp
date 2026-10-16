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
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import UiDialog from './UiDialog.vue'
import UiButton from './UiButton.vue'

/** 焦点落在这些元素内时，Enter 归输入框自己（确认框自身从不含输入框，
 *  但确认框可能从带输入框的表单里弹出——此时抢 Enter 会打断用户正在填的内容）。 */
function isTypingTarget(t: EventTarget | null): boolean {
  return !!(t as HTMLElement | null)?.closest?.('input, textarea, [contenteditable="true"]')
}

const props = withDefaults(
  defineProps<{
    open: boolean
    text: string
    sub?: string
    type?: 'danger' | 'warning'
    /**
     * 点击遮罩/空白处是否关闭弹窗。默认 **false**（2026-10-14 全站约定）：
     * 确认框只走「取消 / 确认」，避免误点空白把待确认的动作吞掉。
     */
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
    closeOnOverlayClick: false,
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

/**
 * 键盘操作（2026-10-16）：弹窗打开期间监听 keydown，Enter = 确认、Esc = 取消，
 * 让删除确认可以纯键盘完成。焦点在输入框内时 Enter 不抢（交给输入框）。
 * 监听器挂在 document 上：确认框出现在 Teleport/Portal 里，组件自身节点未必在页面上，
 * 但 keydown 会冒泡到 document。已关闭/未打开时不挂，避免泄漏到全局。
 */
let bound = false

function keyHandler(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    if (isTypingTarget(e.target)) return
    e.preventDefault()
    // 立即摘监听再 emit：连按 Enter 不会重复触发删除
    unbindKeys()
    emit('confirm')
  } else if (e.key === 'Escape') {
    e.preventDefault()
    unbindKeys()
    emit('cancel')
  }
}

function bindKeys() {
  if (!props.open || bound) return
  document.addEventListener('keydown', keyHandler)
  bound = true
}

function unbindKeys() {
  if (!bound) return
  document.removeEventListener('keydown', keyHandler)
  bound = false
}

onMounted(bindKeys)
onBeforeUnmount(unbindKeys)
watch(
  () => props.open,
  (open) => {
    if (open) bindKeys()
    else unbindKeys()
  },
)

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

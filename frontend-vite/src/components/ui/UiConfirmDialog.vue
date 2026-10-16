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

<!-- 跨实例共享状态必须在普通 <script> 里、**不能**放进 <script setup>：
     后者的所有声明都会被编译进 setup() 作用域，于是每个实例各持一份栈，
     守卫「只有栈顶响应」会恒真，多实例同按一次 Enter 仍会一起触发。 -->
<script lang="ts">
/** 当前处于打开状态的确认框实例栈，后打开的在栈顶（= 视觉最上层）。
 *
 *  为什么需要它：键盘监听挂在 document 上，而一个页面可能同时挂两个确认框
 *  （DashboardView 的「退出登录」+「备货提醒」——后者是挂载后请求返回才打开的）。
 *  两个监听都会收到同一次 Enter，于是按一下回车既登出又跳 /beile-order，
 *  两处路由互相抢，用户被送到备货页而不是登录页。
 *
 *  约定：**只有栈顶那个响应按键**，与用户看到的层级一致。
 *  入栈/出栈随 bindKeys/unbindKeys 同步，onBeforeUnmount 兜底摘除。
 */
const openStack: symbol[] = []
</script>

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
/** 本实例在共享栈里的凭据。用 Symbol 而非组件实例，避免持有可被 GC 的对象 */
const selfToken = Symbol('UiConfirmDialog')
/** 本次打开期间按键是否已被本实例消费过。
 *  显式标志而非只靠 unbindKeys：否则「防连按」要依赖 watch 的 flush 时序
 *  （emit 时 props.open 仍为 true，watcher 要到下一拍才重绑）——哪天有人给
 *  @confirm 加了 .stop 或换了非 Teleport 的弹窗实现，保护就会静默失效。 */
let consumed = false

function keyHandler(e: KeyboardEvent) {
  // 只让最上层（栈顶）那一个响应：堆叠场景下视觉盖在最上面的框才是用户想操作的那个
  if (openStack[openStack.length - 1] !== selfToken) return
  if (consumed) return
  if (e.key === 'Enter') {
    if (isTypingTarget(e.target)) return
    e.preventDefault()
    consumed = true
    // 立即摘监听再 emit：连按 Enter 不会重复触发删除
    unbindKeys()
    emit('confirm')
  } else if (e.key === 'Escape') {
    e.preventDefault()
    consumed = true
    unbindKeys()
    emit('cancel')
  }
}

function bindKeys() {
  if (!props.open || bound) return
  consumed = false
  document.addEventListener('keydown', keyHandler)
  openStack.push(selfToken)
  bound = true
}

function unbindKeys() {
  if (bound) {
    document.removeEventListener('keydown', keyHandler)
    const i = openStack.lastIndexOf(selfToken)
    if (i >= 0) openStack.splice(i, 1)
  }
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

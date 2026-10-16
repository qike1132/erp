<template>
  <DialogRoot :open="open" @update:open="$emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay
        :class="['fixed inset-0 bg-black/50 backdrop-blur-sm data-[state=open]:animate-[fadeIn_0.2s_ease]', overlayZClass]"
      />
      <DialogContent
        :class="[
          'fixed inset-0 m-auto bg-surface-card rounded-2xl shadow-lg w-[95%] h-fit max-h-[90vh] overflow-hidden flex flex-col animate-slide-up',
          contentZClass,
          maxWidthClass,
        ]"
        @interact-outside="onInteractOutside"
      >
        <!-- 始终渲染 DialogTitle / DialogDescription（aria-labelledby / aria-describedby 要求）。
             无可见标题时用 srTitle 提供真实名称，而不是让读屏器只听到「对话框」。 -->
        <DialogTitle
          v-if="!title && !$slots.title"
          class="sr-only"
        >
          {{ srTitle || '对话框' }}
        </DialogTitle>
        <DialogDescription class="sr-only">
          {{ description || '对话框内容' }}
        </DialogDescription>
        <div
          v-if="title || $slots.title"
          class="px-6 py-5 border-b border-border-light flex justify-between items-center"
        >
          <DialogTitle class="text-lg font-semibold m-0 text-text flex items-center gap-2 flex-1 justify-center">
            <slot name="title-icon" />
            <slot name="title">
              {{ title }}
            </slot>
          </DialogTitle>
          <DialogClose
            class="w-8 h-8 border-none bg-surface rounded-full cursor-pointer flex items-center justify-center text-text-secondary transition-colors duration-200 hover:bg-danger-50 hover:text-danger-500"
            aria-label="关闭"
          >
            <FontAwesomeIcon icon="times" aria-hidden="true" />
          </DialogClose>
        </div>
        <div :class="['overflow-y-auto flex-1 overscroll-contain', { 'p-6': bodyPadded }, bodyClass]">
          <slot />
        </div>
        <div v-if="$slots.footer" class="px-6 py-4 border-t border-border-light flex justify-end gap-2">
          <slot name="footer" />
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>

<script setup lang="ts">
import { DialogRoot, DialogPortal, DialogOverlay, DialogContent, DialogTitle, DialogDescription, DialogClose } from 'reka-ui'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    /** 无可见标题时，提供给读屏器的真实名称（如确认框的问句） */
    srTitle?: string
    /** 提供给读屏器的描述文本 */
    description?: string
    maxWidthClass?: string
    overlayZClass?: string
    contentZClass?: string
    /**
     * 额外加到 body 容器的 class。内容经 DialogPortal 渲染到 body，调用方的 scoped 样式
     * 够不到 body 容器；需要覆盖 body 的背景/内边距时用这个钩子。
     */
    bodyClass?: string
    /**
     * body 是否带内置内边距（`p-6`），默认 true。需要自定义内边距时传 false —— 否则
     * 得跟内置 `p-6` 抢优先级（只能靠全局 `!important`，且 UiDialog 改 `p-6` 会静默失效）。
     */
    bodyPadded?: boolean
    /**
     * 点击遮罩/空白处是否关闭弹窗。
     * 默认 **false**（2026-10-14 全站约定）：误点空白会丢掉已填内容，故一律不关，
     * 只走 ✕ / 取消 / Esc。确需「点空白即关」的调用方显式传 true。
     */
    closeOnOverlayClick?: boolean
  }>(),
  {
    maxWidthClass: 'max-w-[800px]',
    overlayZClass: 'z-[var(--z-overlay)]',
    contentZClass: 'z-[var(--z-modal)]',
    bodyClass: undefined,
    bodyPadded: true,
    closeOnOverlayClick: false,
    title: undefined,
    srTitle: undefined,
    description: undefined,
  },
)

defineEmits<{ 'update:open': [value: boolean] }>()

/** 阻止点击遮罩/空白处关闭：仅当 closeOnOverlayClick 为 false 时拦截 */
function onInteractOutside(event: Event) {
  if (props.closeOnOverlayClick === false) event.preventDefault()
}
</script>

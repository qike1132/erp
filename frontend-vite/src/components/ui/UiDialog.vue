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
        <!-- 始终渲染 DialogTitle（aria-labelledby 要求），无标题时隐藏但保持可访问性 -->
        <DialogTitle
          v-if="!title && !$slots.title"
          class="sr-only"
        >
          对话框
        </DialogTitle>
        <DialogDescription class="sr-only">
          对话框内容
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
        <div class="p-6 overflow-y-auto flex-1 overscroll-contain">
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
    maxWidthClass?: string
    overlayZClass?: string
    contentZClass?: string
    /** 点击遮罩/空白处是否关闭弹窗（默认 true） */
    closeOnOverlayClick?: boolean
  }>(),
  {
    maxWidthClass: 'max-w-[800px]',
    overlayZClass: 'z-[var(--z-overlay)]',
    contentZClass: 'z-[var(--z-modal)]',
    closeOnOverlayClick: true,
  },
)

defineEmits<{ 'update:open': [value: boolean] }>()

/** 阻止点击遮罩/空白处关闭：仅当 closeOnOverlayClick 为 false 时拦截 */
function onInteractOutside(event: Event) {
  if (props.closeOnOverlayClick === false) event.preventDefault()
}
</script>

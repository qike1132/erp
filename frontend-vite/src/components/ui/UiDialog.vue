<template>
  <DialogRoot :open="open" @update:open="$emit('update:open', $event)">
    <DialogPortal>
      <DialogOverlay
        class="fixed inset-0 bg-black/50 backdrop-blur-sm z-[var(--z-overlay)] data-[state=open]:animate-[fadeIn_0.2s_ease]"
      />
      <DialogContent
        :class="[
          'fixed inset-0 m-auto bg-surface-card rounded-2xl shadow-lg w-[95%] h-fit max-h-[90vh] overflow-hidden flex flex-col z-[var(--z-modal)] animate-slide-up',
          maxWidthClass,
        ]"
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
            <i class="fas fa-times" aria-hidden="true" />
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

withDefaults(
  defineProps<{
    open: boolean
    title?: string
    maxWidthClass?: string
  }>(),
  {
    maxWidthClass: 'max-w-[800px]',
  },
)

defineEmits<{ 'update:open': [value: boolean] }>()
</script>

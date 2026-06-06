<template>
  <div class="text-center py-12 text-text-muted">
    <i :class="['text-5xl mb-3 opacity-30 block', icon]" aria-hidden="true" />
    <p class="text-sm m-0 mb-2">
      <slot>{{ text }}</slot>
    </p>
    <slot name="action">
      <button
        v-if="actionText"
        class="mt-3 px-4 py-2 text-sm font-medium rounded-[var(--radius-sm)] bg-primary-50 text-primary-600 hover:bg-primary-100 transition-colors duration-200 cursor-pointer"
        @click="$emit('action')"
      >
        {{ actionText }}
      </button>
    </slot>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    icon?: string
    text?: string
    actionText?: string
  }>(),
  {
    icon: 'fas fa-inbox',
    text: '暂无数据',
    actionText: '',
  },
)

defineEmits<{
  action: []
}>()
</script>

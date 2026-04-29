<template>
  <UiDialog :open="open" max-width-class="max-w-[420px]" @update:open="onOpenUpdate">
    <div class="p-8">
      <div :class="['w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-4 text-2xl', iconBgClass]">
        <i :class="iconClass" />
      </div>
      <div class="text-center text-base text-text mb-2">
        {{ text }}
      </div>
      <div v-if="sub" class="text-center text-sm text-text-secondary">
        {{ sub }}
      </div>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="$emit('cancel')"> 取消 </UiButton>
      <UiButton :variant="confirmVariant" @click="$emit('confirm')"> 确认 </UiButton>
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
  }>(),
  {
    type: 'danger',
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

const iconClass = computed(() => (props.type === 'danger' ? 'fas fa-trash-alt' : 'fas fa-exclamation-triangle'))

const confirmVariant = computed(() => (props.type === 'danger' ? 'danger' : 'primary'))
</script>

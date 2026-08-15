<template>
  <UiDialog v-model:open="openModel" title="添加国家" max-width-class="max-w-[420px]">
    <div class="co-form-group">
      <label class="co-label">国家名称</label>
      <UiInput v-model="countryNameModel" placeholder="请输入国家名称" name="country" autocomplete="off" />
    </div>
    <template #footer>
      <UiButton variant="outline" @click="openModel = false">取消</UiButton>
      <UiButton variant="primary" @click="saveCountry">保存</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'

const props = defineProps<{
  open: boolean
  newCountryName: string
  saveCountry: () => void
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'update:newCountryName': [value: string]
}>()

const openModel = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})

const countryNameModel = computed({
  get: () => props.newCountryName,
  set: (v: string) => emit('update:newCountryName', v),
})
</script>

<style scoped>
.co-form-group { margin-bottom: 14px; }
.co-label {
  display: block; font-size: 13px; font-weight: 500; margin-bottom: 4px; color: var(--color-text-secondary);
}
</style>

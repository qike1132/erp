<template>
  <UiDialog :open="open" @update:open="$emit('update:open', $event)" title="收货登记" title-icon="" max-width-class="max-w-[540px]" overlay-z-class="z-[var(--z-overlay-nested)]" content-z-class="z-[var(--z-modal-nested)]">
    <template #title-icon><FontAwesomeIcon icon="box" style="color:var(--color-success-500);" /></template>
    <div class="mr-fg2"><label>物料名称</label><div style="font-weight:600;font-size:17px;">{{ item.name }}</div></div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;">
      <div class="mr-fg2"><label>采购数量</label><div style="font-size:17px;">{{ item.ordered }}</div></div>
      <div class="mr-fg2"><label>已收货</label><div style="font-size:17px;color:var(--color-success-500);">{{ item.received }}</div></div>
      <div class="mr-fg2"><label>待收货</label><div style="font-size:17px;color:var(--color-warning-500);">{{ item.remaining }}</div></div>
    </div>
    <div class="mr-fg2"><label>本次收货数量</label><input type="number" v-model.number="qty" min="0.01" step="0.01" placeholder="输入本次收货数量"></div>
    <div class="mr-fg2"><label>备注</label><textarea v-model="remark" rows="2" placeholder="可选备注..."></textarea></div>
    <template #footer>
      <button class="mr-btn mr-btn-ghost" @click="$emit('update:open', false)">取消</button>
      <button class="mr-btn mr-btn-success" @click="onSubmit"><FontAwesomeIcon icon="check" /> 确认收货</button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'

interface ReceiveItem {
  id: number
  name: string
  ordered: number
  received: number
  remaining: number
}

const props = defineProps<{
  open: boolean
  item: ReceiveItem
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  submit: [payload: { qty: number | null; remark: string }]
}>()

const qty = ref<number | null>(null)
const remark = ref('')

watch(() => props.open, (val) => {
  if (val) {
    qty.value = null
    remark.value = ''
  }
})

function onSubmit() {
  emit('submit', { qty: qty.value, remark: remark.value })
}
</script>

<style scoped lang="scss">
@use '../material-dialogs.scss' as *;
</style>

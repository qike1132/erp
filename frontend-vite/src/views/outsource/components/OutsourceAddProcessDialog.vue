<template>
  <UiDialog v-model:open="open" :title="`为「${target?.product_name || ''}」添加工序`" max-width-class="max-w-[560px]">
    <div class="osp-form">
      <div class="osp-form-row">
        <label class="osp-form-label">常用工序（点击即添加）</label>
        <div class="osp-quick-tags">
          <button
            v-for="tag in COMMON_PROCESSES"
            :key="tag"
            type="button"
            class="osp-quick-tag"
            :class="{ 'osp-quick-tag--added': isAdded(tag), 'osp-quick-tag--disabled': isAdded(tag) }"
            :disabled="isAdded(tag) || saving"
            @click="quickAdd(tag)"
          >
            <FontAwesomeIcon v-if="isAdded(tag)" icon="check" aria-hidden="true" />
            {{ tag }}
          </button>
        </div>
      </div>
      <div class="osp-form-row">
        <label class="osp-form-label">或输入自定义工序名称</label>
        <div class="osp-add-row">
          <input
            v-model="addInput"
            class="osp-text-input"
            placeholder="输入工序名称，多个用逗号分隔"
            maxlength="200"
            @keyup.enter="handleAdd()"
          />
          <UiButton variant="primary" :disabled="saving" @click="handleAdd()">
            {{ saving ? '添加中…' : '添加' }}
          </UiButton>
        </div>
      </div>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="open = false">关闭</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { outsourceApi } from '@/api'
import type { OutsourceProcessType } from '@/api/outsource'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import { toast } from '@/composables/useToast'

interface ProductCard {
  product_id: number
  product_name: string
  product_barcode: string | null
  factory: string | null
  processes: OutsourceProcessType[]
}

const props = defineProps<{
  target: ProductCard | null
  productCards: ProductCard[]
  refresh: () => Promise<void>
}>()

const emit = defineEmits<{
  'update:target': [card: ProductCard | null]
  removePending: [productId: number]
}>()

const open = defineModel<boolean>('open', { default: false })
const addInput = ref('')
const saving = ref(false)

const COMMON_PROCESSES = ['电绣', '转印']

function isAdded(tag: string): boolean {
  if (!props.target) return false
  return props.target.processes.some((p) => p.process_type === tag)
}

async function quickAdd(tag: string) {
  if (!props.target || isAdded(tag)) return
  saving.value = true
  try {
    const res = await outsourceApi.batchCreateProcessTypes(props.target.product_id, [tag])
    toast.success(res.message || `已添加「${tag}」`)
    await refreshAfterAdd()
  } catch (e) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(msg || '添加失败')
  } finally {
    saving.value = false
  }
}

async function handleAdd() {
  if (!props.target) return
  const names = addInput.value
    .split(/[,，\n]/)
    .map((n) => n.trim())
    .filter(Boolean)
  if (names.length === 0) {
    toast.warning('请输入工序名称')
    return
  }
  saving.value = true
  try {
    const res = await outsourceApi.batchCreateProcessTypes(props.target.product_id, names)
    toast.success(res.message || '工序已添加')
    addInput.value = ''
    await refreshAfterAdd()
  } catch (e) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(msg || '添加失败')
  } finally {
    saving.value = false
  }
}

async function refreshAfterAdd() {
  emit('removePending', props.target?.product_id ?? 0)
  await props.refresh()
  const refreshed = props.productCards.find((c) => c.product_id === props.target?.product_id)
  if (refreshed) emit('update:target', refreshed)
}
</script>

<style scoped>
.osp-form { display: flex; flex-direction: column; gap: 14px; }
.osp-form-row { display: flex; flex-direction: column; gap: 6px; }
.osp-form-label { font-size: 12.5px; font-weight: 600; color: var(--color-text-secondary); }
.osp-quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 4px 0;
}
.osp-quick-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 16px;
  border-radius: 999px;
  border: 1.5px solid var(--color-primary-300);
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s ease, transform 0.15s ease, opacity 0.15s ease;
  font-family: inherit;
}
.osp-quick-tag:hover:not(:disabled) {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}
.osp-quick-tag--added {
  background: var(--color-success-50);
  border-color: var(--color-success-300);
  color: var(--color-success-700);
}
.osp-quick-tag--disabled { cursor: default; opacity: 0.85; }
.osp-add-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.osp-text-input {
  width: 100%;
  padding: 8px 12px;
  font-size: 13px;
  color: var(--color-text);
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  box-sizing: border-box;
  font-family: inherit;
}
.osp-text-input:focus {
  outline: none;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}
</style>
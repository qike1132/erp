<template>
  <UiDialog :open="open" title="批量导入出货计划" max-width-class="max-w-[1000px]" @update:open="handleClose">
    <div class="buf">
      <div class="buf-steps">
        <div
          v-for="(s, i) in steps"
          :key="s.key"
          class="buf-step"
          :class="{
            'buf-step-active': step === s.key,
            'buf-step-done': steps.findIndex(x => x.key === step) > i,
          }"
        >
          <div class="buf-step-num">{{ i + 1 }}</div>
          <span class="buf-step-label">{{ s.label }}</span>
        </div>
      </div>

      <div v-if="step === 'upload'" class="buf-upload-area">
        <div class="buf-upload-center">
          <div class="buf-upload-icon"><i class="fas fa-cloud-upload-alt" /></div>
          <h4 class="buf-upload-title">上传 Excel 文件</h4>
          <p class="buf-upload-desc">支持 .xlsx 格式，文件大小不超过 10MB</p>
        </div>
        <UiUpload accept=".xlsx" placeholder="拖拽文件到此处，或点击选择文件" @change="handleFileSelect" />
        <div v-if="uploading" class="buf-progress">
          <UiSpinner /> <span style="margin-left: 8px">正在上传并解析...</span>
        </div>
        <div class="buf-template">
          <a class="buf-template-link" @click.prevent="downloadTemplate">
            <i class="fas fa-download" style="margin-right: 4px" />下载导入模板
          </a>
        </div>
      </div>

      <div v-if="step === 'preview'" class="buf-preview">
        <div class="buf-preview-head">
          <h4 class="buf-preview-title">
            <i class="fas fa-table" style="margin-right: 6px; color: var(--color-primary-500)" />
            数据预览
            <span class="buf-record-count">共 {{ stagingList.length }} 条</span>
          </h4>
          <div class="buf-preview-actions">
            <UiButton size="sm" variant="outline" @click="handleValidate">
              <i class="fas fa-check-circle" style="margin-right: 4px" />验证数据
            </UiButton>
            <UiButton size="sm" variant="danger" @click="handleClearStaging">
              <i class="fas fa-trash" style="margin-right: 4px" />清空
            </UiButton>
          </div>
        </div>

        <div v-if="isLoadingStaging" class="buf-loading">
          <UiSpinner /> <span style="margin-left: 8px; color: var(--color-text-muted)">加载中...</span>
        </div>
        <div v-else-if="stagingList.length" class="buf-table-wrap">
          <table class="buf-table">
            <thead>
              <tr>
                <th style="width: 40px">
                  <input type="checkbox" :checked="allSelected" @change="toggleAll" />
                </th>
                <th>客户</th>
                <th>产品名称</th>
                <th>69码</th>
                <th class="buf-th-num">数量</th>
                <th>计划日期</th>
                <th>备注</th>
                <th class="buf-th-center">验证状态</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, i) in stagingList"
                :key="i"
                :class="{ 'buf-row-invalid': !row.is_validated }"
              >
                <td><input v-model="selectedIds" type="checkbox" :value="row.id" /></td>
                <td class="buf-td-customer">{{ row.customer_name }}</td>
                <td>{{ row.product_name }}</td>
                <td class="buf-td-barcode">{{ row.barcode }}</td>
                <td class="buf-td-num">{{ row.quantity }}</td>
                <td>{{ row.plan_date }}</td>
                <td class="buf-td-muted">{{ row.remark || '-' }}</td>
                <td class="buf-td-center">
                  <UiBadge v-if="row.is_validated" variant="completed">已验证</UiBadge>
                  <UiBadge v-else variant="pending">待验证</UiBadge>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <UiEmpty v-else description="暂存区为空" />
      </div>

      <div v-if="step === 'confirm'" class="buf-confirm">
        <div class="buf-confirm-center">
          <div class="buf-confirm-icon"><i class="fas fa-check-circle" /></div>
          <h4>确认导入数据</h4>
          <p>已选择 <b>{{ selectedIds.length }}</b> 条记录，确认后将写入正式出货计划</p>
        </div>
      </div>
    </div>

    <template #footer>
      <template v-if="step === 'upload'">
        <UiButton variant="outline" @click="handleClose">取消</UiButton>
      </template>
      <template v-else-if="step === 'preview'">
        <UiButton variant="outline" @click="handleClearAndBack">返回</UiButton>
        <UiButton
          variant="primary"
          :disabled="selectedIds.length === 0"
          @click="step = 'confirm'"
        >
          确认导入 ({{ selectedIds.length }})
        </UiButton>
      </template>
      <template v-else>
        <UiButton variant="outline" @click="step = 'preview'">返回</UiButton>
        <UiButton variant="primary" :disabled="confirming" @click="handleConfirm">
          <i v-if="confirming" class="fas fa-spinner fa-spin" style="margin-right: 4px" />
          确认写入
        </UiButton>
      </template>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { planApi } from '@/api'
import { showToast } from '@/composables/useToast'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiUpload from '@/components/ui/UiUpload.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const queryClient = useQueryClient()

const steps = [
  { key: 'upload', label: '上传文件' },
  { key: 'preview', label: '预览数据' },
  { key: 'confirm', label: '确认导入' },
]

const step = ref<'upload' | 'preview' | 'confirm'>('upload')
const uploading = ref(false)
const confirming = ref(false)
const batchId = ref('')
const selectedIds = ref<number[]>([])

const {
  data: stagingData,
  isLoading: isLoadingStaging,
  refetch: refetchStaging,
} = useQuery({
  queryKey: ['plan-staging-list'],
  queryFn: async () => {
    const res = (await planApi.stagingList()) as any
    return res
  },
  enabled: computed(() => step.value === 'preview'),
  staleTime: 5_000,
})

const stagingList = computed(() => stagingData.value?.data ?? [])

const allSelected = computed(
  () => stagingList.value.length > 0 && selectedIds.value.length === stagingList.value.length,
)

function toggleAll() {
  if (allSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = stagingList.value.map((r: any) => r.id)
  }
}

watch(
  () => props.open,
  (val) => {
    if (val) {
      step.value = 'upload'
      batchId.value = ''
      selectedIds.value = []
    }
  },
)

async function handleFileSelect(files: FileList) {
  const file = files[0]
  if (!file) return

  if (!file.name.endsWith('.xlsx')) {
    showToast('仅支持 .xlsx 格式文件', 'warning')
    return
  }

  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    const res = (await planApi.upload(formData)) as any
    batchId.value = res.batch_id || ''
    showToast(`解析成功，共 ${res.total || 0} 条记录`, 'success')
    step.value = 'preview'
    refetchStaging()
  } catch (err: any) {
    showToast(err.response?.data?.detail || '上传失败', 'error')
  } finally {
    uploading.value = false
  }
}

async function handleValidate() {
  try {
    const res = (await planApi.stagingValidate()) as any
    showToast(res.message || '验证完成', 'success')
    refetchStaging()
  } catch (err: any) {
    showToast(err.response?.data?.detail || '验证失败', 'error')
  }
}

async function handleClearStaging() {
  try {
    await planApi.stagingClear()
    showToast('暂存区已清空', 'success')
    refetchStaging()
  } catch (err: any) {
    showToast(err.response?.data?.detail || '清空失败', 'error')
  }
}

async function handleConfirm() {
  confirming.value = true
  try {
    const data: any = { batch_id: batchId.value }
    if (selectedIds.value.length > 0) data.selected_ids = selectedIds.value
    const res = (await planApi.stagingConfirm(data)) as any
    showToast(res.message || '导入成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['plan-list'] })
    queryClient.invalidateQueries({ queryKey: ['plan-monthly'] })
    queryClient.invalidateQueries({ queryKey: ['plan-monthly-overview'] })
    queryClient.invalidateQueries({ queryKey: ['plan-monthly-schedule'] })
    emit('update:open', false)
  } catch (err: any) {
    showToast(err.response?.data?.detail || '导入失败', 'error')
  } finally {
    confirming.value = false
  }
}

function handleClearAndBack() {
  step.value = 'upload'
  selectedIds.value = []
}

function handleClose(val: boolean) {
  if (!val) {
    step.value = 'upload'
    selectedIds.value = []
  }
  emit('update:open', val)
}

async function downloadTemplate() {
  try {
    await planApi.downloadTemplate()
  } catch {
    showToast('下载模板失败', 'error')
  }
}
</script>

<style scoped>
.buf {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.buf-steps {
  display: flex;
  gap: 0;
  background: var(--color-surface);
  border-radius: var(--radius-md);
  padding: 4px;
  border: 1px solid var(--color-border-light);
}
.buf-step {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: var(--radius-sm);
  transition: all 0.3s;
}
.buf-step-active {
  background: var(--gradient-primary);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.3);
}
.buf-step-active .buf-step-num {
  background: white;
  color: var(--color-primary-500);
}
.buf-step-active .buf-step-label {
  color: white;
}
.buf-step-done .buf-step-num {
  background: var(--color-success-500);
  color: white;
}
.buf-step-num {
  width: 22px; height: 22px;
  border-radius: 50%;
  background: var(--color-border-light);
  color: var(--color-text-secondary);
  font-size: 0.7rem;
  font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.3s;
}
.buf-step-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  transition: color 0.3s;
}

.buf-upload-area {
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-items: center;
}
.buf-upload-center {
  text-align: center;
}
.buf-upload-icon {
  font-size: 2.5rem;
  color: var(--color-primary-500);
  margin-bottom: 8px;
}
.buf-upload-title {
  margin: 0 0 4px;
  font-size: 1rem;
  font-weight: 700;
  color: var(--color-text);
}
.buf-upload-desc {
  color: var(--color-text-secondary);
  font-size: 0.85rem;
  margin: 0;
}
.buf-progress {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
  color: var(--color-text-secondary);
  font-size: 0.9rem;
}
.buf-template {
  text-align: center;
}
.buf-template-link {
  color: var(--color-primary-500);
  cursor: pointer;
  font-size: 0.85rem;
  text-decoration: none;
  transition: color 0.2s;
}
.buf-template-link:hover {
  color: var(--color-primary-600);
  text-decoration: underline;
}

.buf-preview {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.buf-preview-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.buf-preview-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 4px;
}
.buf-preview-actions {
  display: flex;
  gap: 8px;
}
.buf-record-count {
  color: var(--color-text-secondary);
  font-size: 0.85rem;
  font-weight: 400;
  margin-left: 8px;
}
.buf-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 0;
}

.buf-table-wrap {
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
}
.buf-table {
  width: 100%;
  border-collapse: collapse;
}
.buf-table th,
.buf-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--color-border-light);
  font-size: 0.82rem;
}
.buf-table thead th {
  background: var(--gradient-card-header);
  font-weight: 600;
  white-space: nowrap;
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  position: sticky;
  top: 0;
  z-index: 1;
}
.buf-table tbody tr:hover {
  background: rgba(91, 141, 239, 0.04);
}
.buf-row-invalid {
  background: rgba(234, 84, 85, 0.04);
}
.buf-th-num { text-align: right; }
.buf-th-center { text-align: center; }
.buf-td-num { text-align: right; }
.buf-td-center { text-align: center; }
.buf-td-customer { font-weight: 600; }
.buf-td-barcode { font-family: var(--font-mono); font-size: 0.78rem; color: var(--color-text-muted); }
.buf-td-muted { color: var(--color-text-muted); }

.buf-confirm {
  display: flex;
  justify-content: center;
  padding: 24px 0;
}
.buf-confirm-center {
  text-align: center;
}
.buf-confirm-icon {
  font-size: 3rem;
  color: var(--color-success-500);
  margin-bottom: 12px;
}
.buf-confirm-center h4 {
  margin: 0 0 8px;
  font-size: 1.1rem;
  font-weight: 700;
}
.buf-confirm-center p {
  color: var(--color-text-secondary);
  font-size: 0.9rem;
  margin: 0;
}
.buf-confirm-center b {
  color: var(--color-primary-500);
}
</style>

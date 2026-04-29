<template>
  <UiDialog :open="open" title="新增出货计划" max-width-class="max-w-[960px]" @update:open="$emit('update:open', $event)">
    <div class="cpf">
      <div class="cpf-section">
        <h4 class="cpf-section-title">基本信息</h4>
        <div class="cpf-grid">
          <div class="cpf-field">
            <label class="cpf-label">客户 <span class="cpf-required">*</span></label>
            <UiSelect v-model="form.customer_id" placeholder="选择客户" :options="customerOptions" />
          </div>
          <div class="cpf-field">
            <label class="cpf-label">计划月份 <span class="cpf-required">*</span></label>
            <UiInput v-model="form.plan_month" placeholder="YYYY-MM" />
          </div>
          <div class="cpf-field">
            <label class="cpf-label">备注</label>
            <UiInput v-model="form.remark" placeholder="可选" />
          </div>
        </div>
      </div>

      <div class="cpf-section">
        <div class="cpf-section-head">
          <h4 class="cpf-section-title">计划明细</h4>
          <div class="cpf-detail-actions">
            <span class="cpf-detail-count">{{ form.details.length }} 条</span>
            <UiButton size="sm" variant="outline" @click="addDetail">
              <i class="fas fa-plus" style="margin-right: 4px" />添加明细
            </UiButton>
          </div>
        </div>

        <div class="cpf-details">
          <div
            v-for="(detail, index) in form.details"
            :key="index"
            class="cpf-detail-card"
          >
            <div class="cpf-detail-head">
              <span class="cpf-detail-index">
                <span class="cpf-index-num">{{ index + 1 }}</span>
              </span>
              <button v-if="form.details.length > 1" class="cpf-detail-remove" @click="removeDetail(index)">
                <i class="fas fa-times" />
              </button>
            </div>
            <div class="cpf-detail-grid">
              <div class="cpf-field">
                <label class="cpf-label">产品名称 <span class="cpf-required">*</span></label>
                <UiInput v-model="detail.product_name" placeholder="产品名称" />
              </div>
              <div class="cpf-field">
                <label class="cpf-label">数量 <span class="cpf-required">*</span></label>
                <UiInputNumber v-model="detail.quantity" :min="1" :max="999999" />
              </div>
              <div class="cpf-field">
                <label class="cpf-label">计划日期 <span class="cpf-required">*</span></label>
                <UiInput v-model="detail.plan_date" placeholder="YYYY-MM-DD" />
              </div>
            </div>
            <div class="cpf-field" style="max-width: 300px; margin-top: 8px">
              <label class="cpf-label">备注</label>
              <UiInput v-model="detail.remark" placeholder="可选" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <UiButton variant="outline" @click="$emit('update:open', false)">取消</UiButton>
      <UiButton variant="primary" :disabled="submitting" @click="handleSubmit">
        <i v-if="submitting" class="fas fa-spinner fa-spin" style="margin-right: 4px" />
        提交
      </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { customerApi } from '@/api'
import { showToast } from '@/composables/useToast'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiInputNumber from '@/components/ui/UiInputNumber.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiButton from '@/components/ui/UiButton.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const queryClient = useQueryClient()
const submitting = ref(false)

interface DetailForm {
  product_id: number
  product_name: string
  quantity: number
  plan_date: string
  remark: string
}

const form = reactive({
  customer_id: '',
  customer_name: '',
  plan_month: '',
  remark: '',
  details: [
    { product_id: 0, product_name: '', quantity: 1, plan_date: '', remark: '' },
  ] as DetailForm[],
})

const { data: namesData } = useQuery({
  queryKey: ['customer-active-names'],
  queryFn: async () => {
    const res = (await customerApi.activeNames()) as any
    return res.names ?? res ?? []
  },
  staleTime: 60_000,
})

const customerOptions = computed(() => {
  const arr = Array.isArray(namesData.value) ? namesData.value : []
  return arr.map((c: any) => ({
    value: String(c.id ?? ''),
    label: c.name ?? c,
  }))
})

watch(
  () => form.customer_id,
  (id) => {
    const arr = Array.isArray(namesData.value) ? namesData.value : []
    const found = arr.find((c: any) => String(c.id) === id)
    form.customer_name = found ? found.name : ''
  },
)

watch(
  () => props.open,
  (val) => {
    if (val) {
      form.customer_id = ''
      form.customer_name = ''
      const now = new Date()
      form.plan_month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
      form.remark = ''
      form.details = [
        { product_id: 0, product_name: '', quantity: 1, plan_date: '', remark: '' },
      ]
    }
  },
)

function addDetail() {
  form.details.push({
    product_id: 0,
    product_name: '',
    quantity: 1,
    plan_date: '',
    remark: '',
  })
}

function removeDetail(index: number) {
  form.details.splice(index, 1)
}

async function handleSubmit() {
  if (!form.customer_id) {
    showToast('请选择客户', 'warning')
    return
  }
  if (!form.plan_month) {
    showToast('请输入计划月份', 'warning')
    return
  }

  const validDetails = form.details.filter((d) => d.product_name && d.quantity > 0 && d.plan_date)
  if (validDetails.length === 0) {
    showToast('请至少添加一条完整明细', 'warning')
    return
  }

  submitting.value = true
  try {
    const { planApi } = await import('@/api')
    await planApi.create({
      customer_id: Number(form.customer_id),
      customer_name: form.customer_name,
      plan_month: form.plan_month,
      remark: form.remark,
      details: validDetails.map((d) => ({
        product_id: d.product_id,
        product_name: d.product_name,
        barcode: '',
        quantity: d.quantity,
        plan_date: d.plan_date,
        remark: d.remark,
      })),
    })
    showToast('创建成功', 'success')
    emit('update:open', false)
    queryClient.invalidateQueries({ queryKey: ['plan-list'] })
    queryClient.invalidateQueries({ queryKey: ['plan-monthly'] })
    queryClient.invalidateQueries({ queryKey: ['plan-monthly-overview'] })
    queryClient.invalidateQueries({ queryKey: ['plan-monthly-schedule'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '创建失败', 'error')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.cpf {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.cpf-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cpf-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.cpf-section-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text);
  margin: 0;
  padding-bottom: 4px;
  border-bottom: 2px solid var(--color-primary-100);
  display: inline-block;
}
.cpf-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
@media (max-width: 768px) {
  .cpf-grid {
    grid-template-columns: 1fr;
  }
}
.cpf-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.cpf-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.cpf-required {
  color: var(--color-danger-500);
}
.cpf-hint {
  font-size: 0.75rem;
}
.cpf-hint-success {
  color: var(--color-success-500);
}
.cpf-hint-error {
  color: var(--color-danger-500);
}

.cpf-detail-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cpf-detail-count {
  font-size: 0.78rem;
  color: var(--color-text-secondary);
  font-weight: 600;
}

.cpf-details {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
  padding-right: 4px;
}
.cpf-detail-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: 16px;
  transition: all 0.2s;
}
.cpf-detail-card:hover {
  border-color: var(--color-primary-200);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.08);
}
.cpf-detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.cpf-detail-index {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px; height: 24px;
  border-radius: 6px;
  background: var(--color-primary-50);
}
.cpf-index-num {
  font-size: 0.78rem;
  font-weight: 800;
  color: var(--color-primary-500);
}
.cpf-detail-remove {
  width: 24px; height: 24px;
  border-radius: 6px;
  border: none;
  background: var(--color-danger-50);
  color: var(--color-danger-500);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.7rem;
  transition: all 0.2s;
}
.cpf-detail-remove:hover {
  background: var(--color-danger-100);
}
.cpf-detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
@media (max-width: 768px) {
  .cpf-detail-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>

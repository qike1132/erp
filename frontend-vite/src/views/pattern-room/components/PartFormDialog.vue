<template>
  <UiDialog
    :open="open"
    :title="isEditing ? '编辑部位' : '新增部位'"
    max-width="560px"
    @update:open="$emit('update:open', $event)"
  >
    <div class="pf-body">
      <div class="pf-grid">
        <!-- 部位名称 -->
        <div class="pf-field pf-full">
          <label class="pf-label">部位名称 <span class="pf-required">*</span></label>
          <input
            v-model="form.part_name"
            class="pf-input"
            placeholder="如：领口、袖口、前幅"
          />
        </div>

        <!-- 排序 -->
        <div class="pf-field">
          <label class="pf-label">排序号</label>
          <input
            v-model.number="form.sort_order"
            type="number"
            class="pf-input"
            placeholder="0"
          />
        </div>

        <!-- 布料名称 -->
        <div class="pf-field pf-full">
          <label class="pf-label">布料名称</label>
          <input
            v-model="form.fabric_name"
            class="pf-input"
            placeholder="如：纯棉平纹布"
          />
        </div>

        <!-- 布料规格 -->
        <div class="pf-field pf-full">
          <label class="pf-label">布料规格</label>
          <input
            v-model="form.fabric_spec"
            class="pf-input"
            placeholder="如：40S*40S/133*72"
          />
        </div>

        <!-- 供应商 -->
        <div class="pf-field pf-full">
          <label class="pf-label">供应商</label>
          <select v-model="form.supplier_id" class="pf-select">
            <option :value="null">-- 请选择 --</option>
            <option v-for="s in suppliers" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </div>

        <!-- 联系人 -->
        <div class="pf-field">
          <label class="pf-label">联系人</label>
          <input v-model="form.contact_person" class="pf-input" placeholder="联系人姓名" />
        </div>

        <!-- 联系电话 -->
        <div class="pf-field">
          <label class="pf-label">联系电话</label>
          <input v-model="form.contact_phone" class="pf-input" placeholder="手机或座机" />
        </div>

        <!-- 单价 -->
        <div class="pf-field">
          <label class="pf-label">单价（元）</label>
          <input v-model.number="form.unit_price" type="number" step="0.01" class="pf-input" placeholder="0.00" />
        </div>

        <!-- 交货天数 -->
        <div class="pf-field">
          <label class="pf-label">交货天数</label>
          <input v-model.number="form.delivery_days" type="number" class="pf-input" placeholder="0" />
        </div>

        <!-- 备注 -->
        <div class="pf-field pf-full">
          <label class="pf-label">备注</label>
          <textarea v-model="form.remark" class="pf-textarea" rows="2" placeholder="其他说明..." />
        </div>
      </div>
    </div>
    <template #footer>
      <div class="pf-footer">
        <UiButton variant="ghost" @click="$emit('update:open', false)">取消</UiButton>
        <UiButton variant="primary" :loading="submitting" :disabled="!form.part_name.trim()" @click="handleSubmit">
          {{ isEditing ? '保存' : '创建' }}
        </UiButton>
      </div>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { reactive, computed, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import type { Supplier } from '@/types'
import type { PartDetail, PartCreateRequest, PartUpdateRequest } from '@/api/patternRoom'

const props = defineProps<{
  open: boolean
  part: PartDetail | null
  suppliers: Supplier[]
  submitting: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'submit-create': [data: PartCreateRequest]
  'submit-update': [data: PartUpdateRequest]
}>()

const isEditing = computed(() => props.part != null)

const form = reactive({
  part_name: '',
  sort_order: 0,
  fabric_name: '',
  fabric_spec: '',
  supplier_id: null as number | null,
  contact_person: '',
  contact_phone: '',
  unit_price: null as number | null,
  delivery_days: null as number | null,
  remark: '',
})

watch(() => props.open, (val) => {
  if (val) {
    if (props.part) {
      form.part_name = props.part.part_name ?? ''
      form.sort_order = props.part.sort_order ?? 0
      form.fabric_name = props.part.fabric_name ?? ''
      form.fabric_spec = props.part.fabric_spec ?? ''
      form.supplier_id = props.part.supplier_id ?? null
      form.contact_person = props.part.contact_person ?? ''
      form.contact_phone = props.part.contact_phone ?? ''
      form.unit_price = props.part.unit_price ?? null
      form.delivery_days = props.part.delivery_days ?? null
      form.remark = props.part.remark ?? ''
    } else {
      resetForm()
    }
  }
})

function resetForm() {
  form.part_name = ''
  form.sort_order = 0
  form.fabric_name = ''
  form.fabric_spec = ''
  form.supplier_id = null
  form.contact_person = ''
  form.contact_phone = ''
  form.unit_price = null
  form.delivery_days = null
  form.remark = ''
}

function handleSubmit() {
  if (isEditing.value) {
    const data: PartUpdateRequest = {
      part_name: form.part_name,
      sort_order: form.sort_order,
      fabric_name: form.fabric_name || null,
      fabric_spec: form.fabric_spec || null,
      supplier_id: form.supplier_id,
      contact_person: form.contact_person || null,
      contact_phone: form.contact_phone || null,
      unit_price: form.unit_price,
      delivery_days: form.delivery_days,
      remark: form.remark || null,
      version: props.part!.version,
    }
    emit('submit-update', data)
  } else {
    const data: PartCreateRequest = {
      part_name: form.part_name,
      sort_order: form.sort_order,
      fabric_name: form.fabric_name || null,
      fabric_spec: form.fabric_spec || null,
      supplier_id: form.supplier_id,
      contact_person: form.contact_person || null,
      contact_phone: form.contact_phone || null,
      unit_price: form.unit_price,
      delivery_days: form.delivery_days,
      remark: form.remark || null,
    }
    emit('submit-create', data)
  }
}
</script>

<style scoped>
.pf-body {
  padding: 16px 0;
  max-height: 60vh;
  overflow-y: auto;
}
.pf-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.pf-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pf-full {
  grid-column: 1 / -1;
}
.pf-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}
.pf-required {
  color: #ef4444;
}
.pf-input, .pf-select, .pf-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  background: var(--color-surface);
  color: var(--color-text-primary);
  outline: none;
  transition: border-color 0.2s;
  box-sizing: border-box;
}
.pf-input:focus, .pf-select:focus, .pf-textarea:focus {
  border-color: var(--color-primary-500);
}
.pf-textarea {
  resize: vertical;
}
.pf-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 8px;
}
</style>

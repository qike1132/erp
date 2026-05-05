<template>
  <UiDialog
    :open="open"
    title=""
    max-width-class="max-w-[1200px]"
    @update:open="$emit('update:open', $event)"
  >
    <template #title>
      <div class="csd-header-tabs">
        <span
          :class="['csd-htab', { 'csd-htab-active': mode === 'manual' }]"
          @click="mode = 'manual'"
        >填写数据</span>
        <span
          :class="['csd-htab', { 'csd-htab-active': mode === 'import' }]"
          @click="mode = 'import'"
        >批量导入</span>
      </div>
    </template>

    <div class="csd-form">
      <!-- 填写数据 -->
      <template v-if="mode === 'manual'">
        <div class="csd-detail-header">
          <span class="csd-field-cust">客户 <span class="csd-required">*</span></span>
          <span class="csd-field-flex">产品名称 <span class="csd-required">*</span></span>
          <span class="csd-field-xs">数量 <span class="csd-required">*</span></span>
          <span class="csd-field-sm">出货日期 <span class="csd-required">*</span></span>
          <span class="csd-field-action"></span>
        </div>
        <div class="csd-detail-item" v-for="(d, idx) in form.details" :key="idx">
            <div class="csd-detail-row">
              <div class="csd-field csd-field-cust">
                <UiSelect
                  v-model="d.customer_id"
                  placeholder="选择客户"
                  :options="customerOptions"
                  style="width: 100%"
                />
              </div>
              <div class="csd-field csd-field-flex csd-field-product">
                <input
                  v-model="d.product_name"
                  type="text"
                  class="csd-input"
                  placeholder="输入产品名称"
                  @input="onProductInput(idx)"
                  @focus="onProductFocus(idx)"
                  @blur="onProductBlur(idx)"
                />
                <div v-if="d._showSuggest && productSuggestions[idx]?.length" class="csd-suggest-list">
                  <div
                    v-for="p in productSuggestions[idx]"
                    :key="p.id"
                    class="csd-suggest-item"
                    @mousedown.prevent="selectProduct(idx, p)"
                  >
                    <span class="csd-suggest-name">{{ p.name }}</span>
                    <span class="csd-suggest-meta">
                      <span v-if="p.barcode" class="csd-suggest-barcode">{{ p.barcode }}</span>
                      <span v-if="p.current_stock != null" class="csd-suggest-stock">库存 {{ p.current_stock }}</span>
                    </span>
                  </div>
                </div>
              </div>
              <div class="csd-field csd-field-xs">
                <input
                  v-model.number="d.quantity"
                  type="number"
                  class="csd-input csd-input-num"
                  min="1"
                  placeholder="0"
                />
              </div>
              <div class="csd-field csd-field-sm">
                <input
                  type="date"
                  class="csd-input csd-input-date"
                  :value="d.plan_date"
                  @input="d.plan_date = ($event.target as HTMLInputElement).value"
                  @click="($event.target as HTMLInputElement).showPicker()"
                />
              </div>
              <button
                v-if="form.details.length > 1"
                class="csd-remove-btn"
                title="移除此行"
                @click="removeDetail(idx)"
              >
                <i class="fas fa-trash" />
              </button>
          </div>
        </div>
      </template>

      <!-- 批量导入 -->
      <template v-if="mode === 'import'">
        <div
          class="csd-upload-area"
          :class="{ 'csd-upload-hover': dragOver }"
          @click="fileInp?.click()"
          @dragover.prevent="dragOver = true"
          @dragleave="dragOver = false"
          @drop.prevent="onDrop"
        >
          <div class="csd-upload-label">
            <i class="fas fa-file-excel" />
            <span v-if="file" class="csd-file-selected"><i class="fas fa-check-circle" />{{ file.name }}</span>
            <span v-else>拖拽文件到此处或点击选择 · 支持 .xlsx .xls .csv</span>
          </div>
          <div class="csd-upload-buttons">
            <button class="csd-inline-btn" @click.stop="dlTpl">模板</button>
            <button class="csd-inline-btn csd-inline-btn-primary" :disabled="!file || uploading" @click.stop="doUpload">
              <i v-if="!uploading" class="fas fa-upload"></i>
              <i v-else class="fas fa-spinner fa-spin"></i> 导入
            </button>
            <button v-if="file" class="csd-inline-btn csd-inline-btn-danger" @click.stop="clearFile">
              <i class="fas fa-trash"></i>
            </button>
          </div>
          <input ref="fileInp" type="file" accept=".xlsx,.xls,.csv" hidden @change="onFile" />
        </div>
        <div v-if="upMsg" class="csd-upload-message" :class="{ 'csd-upload-success': upOk, 'csd-upload-error': !upOk }">
          <i :class="upOk ? 'fas fa-check-circle' : 'fas fa-exclamation-circle'"></i>
          {{ upMsg }}
        </div>
      </template>

      <div v-if="errorMsg" class="csd-error">
        <i class="fas fa-exclamation-circle" /> {{ errorMsg }}
      </div>
    </div>

    <template #footer>
      <button v-if="mode === 'manual'" class="csd-btn csd-btn-add" @click="addDetail">
        <i class="fas fa-plus" /> 添加明细
      </button>
      <span style="flex:1"></span>
      <button class="csd-btn csd-btn-cancel" @click="$emit('update:open', false)">
        取消
      </button>
      <button v-if="mode === 'manual'" class="csd-btn csd-btn-submit" :disabled="submitting" @click="handleSubmit">
        <i v-if="submitting" class="fas fa-spinner fa-spin" />
        <i v-else class="fas fa-check" />
        {{ submitting ? '保存中...' : '确认创建' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { planApi, customerApi } from '@/api'
import { get } from '@/api/request'
import { showToast } from '@/composables/useToast'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiSelect from '@/components/ui/UiSelect.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  created: []
}>()

const qc = useQueryClient()

const mode = ref<'manual' | 'import'>('manual')

const ym = (() => { const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}` })()

interface DetailLine {
  customer_id: string | number
  product_name: string
  product_id: number
  plan_date: string
  quantity: number | null
  _showSuggest: boolean
}

const form = reactive({
  details: [
    { customer_id: '', product_name: '', product_id: 0, plan_date: '', quantity: null, _showSuggest: false },
  ] as DetailLine[],
})

const productSuggestions = reactive<Record<number, any[]>>({})
let _searchTimer: any = null

const submitting = ref(false)
const errorMsg = ref('')

// 批量导入相关
const file = ref<File | null>(null)
const fileInp = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const uploading = ref(false)
const upMsg = ref('')
const upOk = ref(true)
let _ut: any = null

watch(() => props.open, (val) => {
  if (val) {
    form.details = [{ customer_id: '', product_name: '', product_id: 0, plan_date: '', quantity: null, _showSuggest: false }]
    errorMsg.value = ''
    mode.value = 'manual'
    clearFile()
  }
})

const { data: namesData } = useQuery({
  queryKey: ['customer-active-names'],
  queryFn: async () => {
    const r = (await customerApi.activeNames()) as any
    return r.names ?? r ?? []
  },
  staleTime: 60_000,
})

const customerMap = computed(() => {
  const arr = Array.isArray(namesData.value) ? namesData.value : []
  const map = new Map<number, string>()
  for (const c of arr) {
    map.set(Number(c.id ?? 0), c.name ?? c)
  }
  return map
})

const customerOptions = computed(() => {
  const arr = Array.isArray(namesData.value) ? namesData.value : []
  return arr.map((c: any) => ({ value: String(c.id ?? ''), label: c.name ?? c }))
})

function addDetail() {
  form.details.push({ customer_id: '', product_name: '', product_id: 0, plan_date: '', quantity: null, _showSuggest: false })
}

function removeDetail(idx: number) {
  form.details.splice(idx, 1)
  delete productSuggestions[idx]
}

async function searchProducts(q: string): Promise<any[]> {
  if (!q.trim()) return []
  try {
    const d = await get<any[]>('/aux/product-search', { q })
    return Array.isArray(d) ? d : []
  } catch {
    return []
  }
}

function onProductInput(idx: number) {
  const kw = form.details[idx].product_name.trim()
  form.details[idx].product_id = 0
  clearTimeout(_searchTimer)
  if (!kw) {
    productSuggestions[idx] = []
    form.details[idx]._showSuggest = false
    return
  }
  _searchTimer = setTimeout(async () => {
    const list = await searchProducts(kw)
    productSuggestions[idx] = list.slice(0, 10)
    form.details[idx]._showSuggest = list.length > 0
  }, 300)
}

function onProductFocus(idx: number) {
  const kw = form.details[idx].product_name.trim()
  if (kw && !(productSuggestions[idx]?.length)) {
    searchProducts(kw).then(r => {
      productSuggestions[idx] = r.slice(0, 10)
      form.details[idx]._showSuggest = r.length > 0
    })
  } else if (productSuggestions[idx]?.length) {
    form.details[idx]._showSuggest = true
  }
}

function onProductBlur(idx: number) {
  setTimeout(() => { form.details[idx]._showSuggest = false }, 150)
}

function selectProduct(idx: number, p: any) {
  form.details[idx].product_name = p.name || ''
  form.details[idx].product_id = p.id || 0
  form.details[idx]._showSuggest = false
  productSuggestions[idx] = []
}

// 批量导入功能
function onDrop(ev: DragEvent) { dragOver.value = false; const fs = ev.dataTransfer?.files; if (fs?.length) vfile(fs[0]) }
function onFile(ev: Event) { const t2 = ev.target as HTMLInputElement; if (t2.files?.length) vfile(t2.files[0]); t2.value = '' }
function vfile(f: File) { clearUpMsg(); const ext = '.' + (f.name.split('.').pop()?.toLowerCase() ?? ''); if (!['.xlsx', '.xls', '.csv'].includes(ext)) { showUpMsg('仅支持 .xlsx .xls .csv', false); return; } if (f.size > 10 * 1024 * 1024) { showUpMsg('文件超过 10MB', false); return; } if (f.size === 0) { showUpMsg('文件为空', false); return; } file.value = f }
function clearFile() { file.value = null; clearUpMsg() }
async function doUpload() { if (!file.value) return; uploading.value = true; clearUpMsg(); try { const fd = new FormData(); fd.append('file', file.value); const r = await planApi.upload(fd) as any; showUpMsg(`导入成功，共 ${r.total || 0} 条`, true); clearFile(); qc.invalidateQueries({ queryKey: ['pp-monthly'] }); qc.invalidateQueries({ queryKey: ['pp-summary'] }); emit('created') } catch (e: any) { showUpMsg(e.response?.data?.detail || e.message || '导入失败', false) } finally { uploading.value = false } }
function showUpMsg(msg: string, ok: boolean) { upMsg.value = msg; upOk.value = ok; clearTimeout(_ut); _ut = setTimeout(() => upMsg.value = '', 5000) }
function clearUpMsg() { upMsg.value = ''; clearTimeout(_ut) }
async function dlTpl() { try { await planApi.downloadTemplate() } catch { showToast('下载失败', 'error') } }

function validate(): string | null {
  for (let i = 0; i < form.details.length; i++) {
    const d = form.details[i]
    if (d.customer_id === '' || d.customer_id === 0) return `第 ${i + 1} 行：请选择客户`
    if (!d.product_name.trim()) return `第 ${i + 1} 行：产品名称不能为空`
    if (!d.plan_date) return `第 ${i + 1} 行：请选择出货日期`
    if (!d.quantity || d.quantity <= 0) return `第 ${i + 1} 行：数量必须大于 0`
    if (!Number.isInteger(d.quantity)) return `第 ${i + 1} 行：数量必须为整数`
  }

  return null
}

async function handleSubmit() {
  const err = validate()
  if (err) { errorMsg.value = err; return }
  errorMsg.value = ''

  submitting.value = true
  try {
    // 按客户分组提交
    const byCustomer = new Map<number, DetailLine[]>()
    for (const d of form.details) {
      const cid = Number(d.customer_id)
      if (!byCustomer.has(cid)) byCustomer.set(cid, [])
      byCustomer.get(cid)!.push(d)
    }

    for (const [cid, lines] of byCustomer) {
      const cname = customerMap.value.get(cid) || ''
      const planMonth = lines[0].plan_date ? lines[0].plan_date.substring(0, 7) : ym

      const payload = {
        customer_id: cid,
        customer_name: cname,
        plan_month: planMonth,
        details: lines.map(d => ({
          product_id: d.product_id || 0,
          product_name: d.product_name.trim(),
          barcode: '',
          plan_date: d.plan_date,
          quantity: Number(d.quantity),
          remark: '',
        })),
      }

      await planApi.create(payload)
    }

    showToast('出货计划创建成功', 'success')
    emit('created')
  } catch (err: any) {
    const detail = err.response?.data?.detail || err.message || '创建失败，请重试'
    errorMsg.value = typeof detail === 'string' ? detail : JSON.stringify(detail)
    showToast(errorMsg.value, 'error')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.csd-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 70vh;
}

.csd-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.csd-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.csd-required {
  color: var(--color-danger-500);
}

.csd-hint {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.csd-input {
  padding: 0 10px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  font-size: 0.9375rem;
  line-height: 1.5;
  outline: none;
  transition: all 0.3s ease;
  background: white;
  width: 100%;
  box-sizing: border-box;
  color: var(--color-text);
  height: 44px;
}
.csd-input:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.csd-input::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}

.csd-input-num {
  text-align: center;
  font-weight: 700;
}

.csd-input-date {
  cursor: pointer;
}

.csd-header-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: var(--color-surface, #f1f5f9);
  margin: 0 auto;
}

.csd-htab {
  padding: 6px 20px;
  border-radius: 9px;
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
  white-space: nowrap;
}

.csd-htab:hover {
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.csd-htab-active {
  color: white;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  box-shadow: 0 2px 6px rgba(91, 141, 239, 0.25);
}

.csd-upload-area {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: white;
  border: 2px dashed var(--color-border-light, #e2e8f0);
  border-radius: 11px;
  cursor: pointer;
  transition: all 0.3s ease;
  flex-wrap: wrap;
}
.csd-upload-hover {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.csd-upload-area:hover {
  border-color: var(--color-primary-300);
}
.csd-upload-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 400;
  color: var(--color-text-muted);
  font-family: inherit;
}
.csd-upload-label i {
  color: var(--color-text-muted);
  font-size: 16px;
}
.csd-file-selected {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-success-600);
}
.csd-upload-buttons {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.csd-inline-btn {
  padding: 4px 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 7px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font-family: inherit;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.csd-inline-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}
.csd-inline-btn-primary {
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
  color: white;
}
.csd-inline-btn-primary:hover:not(:disabled) {
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
  color: white;
}
.csd-inline-btn-danger {
  background: var(--color-danger-50);
  border-color: var(--color-danger-200);
  color: var(--color-danger-500);
}
.csd-inline-btn-danger:hover:not(:disabled) {
  background: var(--color-danger-100);
  border-color: var(--color-danger-300);
  color: var(--color-danger-600);
}
.csd-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.csd-upload-message {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
}
.csd-upload-success {
  background: var(--color-success-50);
  color: var(--color-success-600);
  border: 1px solid var(--color-success-200);
}
.csd-upload-error {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
  border: 1px solid var(--color-danger-200);
}

.csd-detail-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.csd-detail-header span {
  display: flex;
  align-items: center;
}

.csd-field-product {
  position: relative;
}

.csd-suggest-list {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 100;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.1);
  margin-top: 4px;
  max-height: 200px;
  overflow-y: auto;
}

.csd-suggest-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s ease;
  font-size: 13px;
  gap: 8px;
}

.csd-suggest-item:hover {
  background: var(--color-primary-50);
}

.csd-suggest-item:first-child {
  border-radius: 10px 10px 0 0;
}

.csd-suggest-item:last-child {
  border-radius: 0 0 10px 10px;
}

.csd-suggest-name {
  font-weight: 500;
  color: var(--color-text);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.csd-suggest-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.csd-suggest-barcode {
  font-size: 11px;
  color: var(--color-text-muted);
  font-family: var(--font-mono, monospace);
  background: var(--color-surface);
  padding: 2px 6px;
  border-radius: 4px;
}

.csd-suggest-stock {
  font-size: 11px;
  color: var(--color-success-600);
  font-weight: 500;
}

.csd-field-action {
  width: 44px;
  flex-shrink: 0;
}

.csd-detail-item {
  padding: 6px 10px;
  background: transparent;
  border: none;
  border-radius: 8px;
}

.csd-detail-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: nowrap;
}

.csd-field-flex {
  flex: 1;
  min-width: 160px;
}

.csd-field-cust {
  width: 180px;
  flex-shrink: 0;
}

.csd-field-sm {
  width: 140px;
  flex-shrink: 0;
}

.csd-field-xs {
  width: 90px;
  flex-shrink: 0;
}

.csd-remove-btn {
  width: 44px;
  height: 44px;
  border-radius: 9px;
  border: 1px solid var(--color-danger-200);
  background: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-danger-500);
  font-size: 0.75rem;
  transition: all 0.2s ease;
  flex-shrink: 0;
}
.csd-remove-btn:hover {
  background: var(--color-danger-50);
  border-color: var(--color-danger-400);
  color: var(--color-danger-600);
}

.csd-btn {
  padding: 10px 24px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.csd-btn-add {
  border: 1.5px dashed var(--color-primary-300);
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.csd-btn-add:hover {
  border-color: var(--color-primary-400);
  background: var(--color-primary-100);
  color: var(--color-primary-700);
}

.csd-add-line {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 5px 14px;
  border: 1.5px dashed var(--color-primary-200);
  border-radius: 8px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}
.csd-add-line:hover {
  border-color: var(--color-primary-400);
  background: var(--color-primary-100);
  color: var(--color-primary-700);
}

.csd-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--color-danger-50);
  color: var(--color-danger-600);
  font-size: 13px;
  font-weight: 600;
  border: 1px solid var(--color-danger-200);
}

.csd-btn {
  padding: 10px 24px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.csd-btn-cancel {
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
}
.csd-btn-cancel:hover {
  border-color: var(--color-border-dark);
  color: var(--color-text);
}

.csd-btn-submit {
  border: none;
  background: var(--gradient-primary);
  color: white;
}
.csd-btn-submit:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(91, 141, 239, 0.3);
}
.csd-btn-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

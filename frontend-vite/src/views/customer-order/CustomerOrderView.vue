<template>
  <div class="co-container">
    <div class="co-card co-card-main">
      <!-- 卡片头部 -->
      <div class="co-card-header">
        <div class="co-header-left">
          <HeaderTabs />
        </div>
      </div>

      <!-- TAB: 录入 -->
      <div class="co-tab-content">
      <div class="co-body">
        <!-- 左栏：录入表单 -->
        <div class="co-col">
          <div class="co-col-title">
            <span><i class="fas fa-edit"></i> {{ isOrder ? '订单信息录入' : '备货信息录入' }}</span>
            <div class="co-type-switch">
              <button :class="['co-type-btn', isOrder && 'active']" @click="form.type = 'order'">
                <i class="fas fa-clipboard-list" />订单
              </button>
              <button :class="['co-type-btn', !isOrder && 'active']" @click="form.type = 'stockin'">
                <i class="fas fa-truck-loading" />备货
              </button>
            </div>
          </div>
          <div class="co-col-scroll">
            <form @submit.prevent="addStaged">
              <div class="co-form-row">
                <div class="co-form-group">
                  <label class="co-label">订单类型 <span class="co-required">*</span></label>
                  <UiSelect
                    v-model="form.orderType"
                    placeholder="请选择订单类型"
                    style="width: 100%"
                    :options="orderTypeOptions"
                  />
                </div>
                <div v-if="isCustomOrder" class="co-form-group">
                  <label class="co-label">国家</label>
                  <div style="display: flex; gap: 8px; align-items: center;">
                    <UiSelect
                      v-model="form.country"
                      placeholder="请选择国家"
                      style="flex: 1"
                      :options="countryStore.countryOptions"
                    />
                    <UiButton variant="outline" style="white-space: nowrap; flex-shrink: 0;" @click="openCountryDialog">
                      <i class="fas fa-plus" />
                    </UiButton>
                  </div>
                </div>
              </div>
              <div class="co-form-row">
                <div v-if="isOrder" class="co-form-group">
                  <label class="co-label">订单时间 <span class="co-required">*</span></label>
                  <UiDatePicker v-model="form.date" style="width: 100%" />
                </div>
                <div v-else class="co-form-group">
                  <label class="co-label">备货时间 <span class="co-required">*</span></label>
                  <UiDatePicker v-model="form.date" style="width: 100%" />
                </div>
                <div class="co-form-group">
                  <label class="co-label">客户名称 <span class="co-required">*</span></label>
                  <UiSelect
                    v-model="form.customer"
                    placeholder="请选择客户"
                    style="width: 100%"
                    :options="customerOptions"
                  />
                </div>
              </div>

              <div class="co-form-group" style="position: relative">
                <label class="co-label">产品名称 <span class="co-required">*</span></label>
                <input
                  type="text"
                  class="form-text-input"
                  :value="form.productSearch"
                  placeholder="输入产品名称搜索"
                  @input="form.productSearch = ($event.target as HTMLInputElement).value; onProductInput()"
                  @focus="onProductFocus"
                  @blur="hideSuggestions"
                />
                <Transition name="co-dropdown">
                  <div v-if="suggestions.length && showSuggestions" class="co-autocomplete">
                    <div
                      v-for="p in suggestions"
                      :key="p.id"
                      class="co-autocomplete-item"
                      @mousedown.prevent="selectProduct(p)"
                    >
                      {{ p.name || p.value }}
                    </div>
                  </div>
                </Transition>
              </div>

              <div class="co-form-row">
                <div class="co-form-group">
                  <label class="co-label"
                    >{{ isOrder ? '订单数量' : '备货数量' }} <span class="co-required">*</span></label
                  >
                  <input type="number" class="form-number-input" v-model.number="form.quantity" min="1" max="9999999" step="1" style="width: 100%" />
                </div>
                <div v-if="isOrder" class="co-form-group">
                  <label class="co-label">抵扣备货数量</label>
                  <div class="co-deduct-row">
                    <button
                      type="button"
                      :class="['co-btn-deduct', form.deductStock && 'active']"
                      @click="handleDeductPreview"
                    >
                      <i class="fas fa-boxes" />抵扣备货
                    </button>
                    <span
                      class="co-deduct-display"
                      :style="{ borderColor: form.deductQuantity > 0 ? 'var(--color-ocean-deep)' : 'var(--color-text-muted)' }"
                      @click="openDeductEdit"
                    >
                      <i class="fas fa-edit" style="font-size: 11px" />抵扣: <strong>{{ form.deductQuantity }}</strong>
                    </span>
                  </div>
                  <div v-if="deductInfoVisible" class="co-deduct-info">
                    <small v-if="availableStock > 0" style="color: var(--color-success-700)">
                      <i class="fas fa-check-circle" /> 可用备货: <strong>{{ availableStock }}</strong> 件
                      <span v-if="form.deductQuantity > 0" style="margin-left: 8px; color: var(--color-ocean-text)">
                        <i class="fas fa-arrow-right" /> 抵扣后剩余:
                        <strong>{{ availableStock - form.deductQuantity }}</strong> 件
                      </span>
                    </small>
                    <small v-else style="color: var(--color-warning-500)"><i class="fas fa-exclamation-circle" /> 暂无可用备货</small>
                  </div>
                </div>
              </div>

              <div class="co-form-group">
                <label class="co-label">备注</label>
                <textarea
                  v-model="form.note"
                  rows="2"
                  class="co-textarea"
                  :placeholder="isOrder ? '例如：加急订单' : '例如：批量备货'"
                />
              </div>

              <!-- 批量导入 -->
              <div class="co-section-label"><i class="fas fa-file-import"></i> 批量导入</div>
              <div
                class="co-section-header co-droppable"
                :class="{ 'co-drag-over': isDragOver }"
                @click="excelInputRef?.click()"
                @dragover.prevent="isDragOver = true"
                @dragleave="isDragOver = false"
                @drop.prevent="onDrop"
              >
                <label class="form-label co-droppable-label">
                  <i class="fas fa-file-excel label-icon"></i>
                  <span v-if="excelFile" class="co-file-inline co-file-inline-success"><i class="fas fa-file-excel" />{{ excelFile.name }}</span>
                  <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
                </label>
                <div class="co-inline-actions">
                  <button class="co-inline-btn" @click.stop="downloadTemplate">模板</button>
                  <button class="co-inline-btn co-inline-btn-success" :disabled="!excelFile" @click.stop="handleImport">
                    {{ importing ? '导入中...' : '导入' }}
                  </button>
                </div>
                <input
                  ref="excelInputRef"
                  type="file"
                  accept=".xlsx,.xls"
                  style="display: none"
                  @change="handleExcelSelect"
                />
              </div>

              <UiButton variant="primary" :disabled="!canAdd" style="margin-top: 15px" @click="addStaged">
                <i class="fas fa-plus-circle" />{{ isOrder ? '新增订单' : '新增备货' }}
              </UiButton>
            </form>
          </div>
        </div>

        <!-- 右栏：暂存列表 + 批量导入 -->
        <div class="co-col">
          <div class="co-col-title">
            <span><i class="fas fa-layer-group"></i> 暂存列表</span>
            <span v-if="stagedItems.length" class="count-badge-subtle">共 {{ stagedItems.length }} 个</span>
          </div>
          <div class="co-col-scroll">
            <template v-if="stagedItems.length">
              <div
                v-for="(item, idx) in stagedItems"
                :key="item.type + '-' + item.productId + '-' + idx"
                class="co-staged-card"
                :style="{ borderColor: item.type === 'order' ? 'var(--color-ocean-light)' : 'var(--color-success-200)' }"
              >
                <div class="co-staged-main">
                  <div class="co-staged-info">
                    <span :class="['co-type-badge', item.type]">{{ item.type === 'order' ? '订单' : '备货' }}</span>
                    <span class="co-staged-tag"><i class="fas fa-user" />{{ item.customer }}</span>
                    <span class="co-staged-tag"><i class="fas fa-calendar-alt" />{{ item.date }}</span>
                    <span class="co-staged-product">
                      <i
                        :class="item.type === 'order' ? 'fas fa-shopping-cart' : 'fas fa-cubes'"
                        :style="{ color: item.type === 'order' ? 'var(--color-ocean-text)' : 'var(--color-success-700)' }"
                      />
                      {{ item.productName }}
                    </span>
                    <span class="count-badge-subtle">数量: {{ item.quantity }}</span>
                    <span v-if="item.deductQuantity > 0" class="count-badge-subtle">抵扣: {{ item.deductQuantity }}</span>
                    <span v-if="item.note" class="count-badge-subtle">备注: {{ item.note }}</span>
                  </div>
                  <div class="co-staged-actions">
                    <button class="co-btn-icon co-btn-warn" @click="openEditStaged(idx)">
                      <i class="fas fa-edit" />
                    </button>
                    <button class="co-btn-icon co-btn-danger" @click="stagedItems.splice(idx, 1)">
                      <i class="fas fa-trash" />
                    </button>
                  </div>
                </div>
              </div>
            </template>
            <div v-else class="co-empty-state">
              <i class="fas fa-box-open co-empty-icon" />
              <p>暂无暂存记录</p>
            </div>
          </div>
        </div>
      </div>

      <!-- 提交按钮 -->
      <div v-if="stagedItems.length" class="co-submit-bar">
      <div style="display: flex; gap: 12px; justify-content: center; flex-wrap: wrap">
        <UiButton
          v-if="stagedOrders.length"
          variant="primary"
          size="lg"
          :disabled="submitting"
          style="min-width: 180px"
          @click="submitOrders"
        >
          <i class="fas fa-paper-plane" />{{ submitting ? '提交中...' : `提交订单 (${stagedOrders.length})` }}
        </UiButton>
        <UiButton
          v-if="stagedStockins.length"
          variant="success"
          size="lg"
          :disabled="submitting"
          style="min-width: 180px"
          @click="submitStockins"
        >
          <i class="fas fa-paper-plane" />{{ submitting ? '提交中...' : `提交备货 (${stagedStockins.length})` }}
        </UiButton>
      </div>
    </div>
      </div>

    </div>

    <!-- 编辑暂存弹窗 -->
    <UiDialog
      :open="editStagedVisible"
      :title="editStagedData?.type === 'order' ? '编辑暂存订单' : '编辑暂存备货'"
      @update:open="editStagedVisible = $event"
    >
      <template v-if="editStagedData">
        <div class="co-form-group">
          <label class="co-label">客户名称</label>
          <UiSelect v-model="editStagedData.customer" style="width: 100%" :options="customerOptions" />
        </div>
        <div class="co-form-group">
          <label class="co-label">{{ editStagedData.type === 'order' ? '订单时间' : '备货时间' }}</label>
          <UiDatePicker v-model="editStagedData.date" style="width: 100%" />
        </div>
        <div class="co-form-group">
          <label class="co-label">产品名称</label>
          <UiInput :model-value="editStagedData.productName" disabled />
        </div>
        <div class="co-form-group">
          <label class="co-label">{{ editStagedData.type === 'order' ? '订单数量' : '备货数量' }}</label>
          <input type="number" class="form-number-input" v-model.number="editStagedData.quantity" min="1" max="9999999" step="1" style="width: 100%" />
        </div>
        <div v-if="editStagedData.type === 'order'" class="co-form-group">
          <label class="co-label">抵扣备货数量</label>
          <input type="number" class="form-number-input" v-model.number="editStagedData.deductQuantity" min="0" :max="Math.min(editStagedData.quantity, editAvailableStock)" step="1" style="width: 100%" />
          <small v-if="editAvailableStock > 0" style="color: var(--color-success-700); margin-top: 4px; display: block">
            <i class="fas fa-check-circle" /> 可用备货: <strong>{{ editAvailableStock }}</strong> 件
          </small>
        </div>
        <div class="co-form-group">
          <label class="co-label">备注</label>
          <textarea v-model="editStagedData.note" rows="2" class="co-textarea" />
        </div>
      </template>
      <template #footer>
        <UiButton variant="outline" @click="editStagedVisible = false"> 取消 </UiButton>
        <UiButton variant="primary" @click="saveEditStaged"> 保存 </UiButton>
      </template>
    </UiDialog>

    <UiDialog :open="countryDialogVisible" title="添加国家" max-width-class="max-w-[420px]" @update:open="countryDialogVisible = $event">
      <div class="co-form-group">
        <label class="co-label">国家名称</label>
        <UiInput v-model="newCountryName" placeholder="请输入国家名称" />
      </div>
      <template #footer>
        <UiButton variant="outline" @click="countryDialogVisible = false">取消</UiButton>
        <UiButton variant="primary" @click="saveCountry">保存</UiButton>
      </template>
    </UiDialog>

    <UiConfirmDialog
      :open="confirmDialog.open"
      :text="confirmDialog.text"
      :sub="confirmDialog.sub"
      :type="confirmDialog.type"
      @confirm="confirmDialog.onConfirm"
      @cancel="confirmDialog.onCancel"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { get, post } from '@/api/request'
import { customerApi } from '@/api'
import UiInput from '@/components/ui/UiInput.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import { showToast } from '@/composables/useToast'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useCountryStore } from '@/stores/country'

const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()
const countryStore = useCountryStore()

// ===== Data queries =====
const { data: customerData } = useQuery({
  queryKey: ['customers-active-names'],
  queryFn: () => customerApi.activeNames() as Promise<any>,
  staleTime: 30_000,
  gcTime: 60_000,
})
const customerList = computed(() => {
  const raw = customerData.value?.names ?? customerData.value ?? []
  return raw.map((c: any) => ({ name: c.name ?? c }))
})
const customerOptions = computed(() => customerList.value.map((c: { name: string }) => ({ value: c.name, label: c.name })))

// ===== Product search (shared) =====
async function searchProducts(q: string) {
  if (!q.trim()) return []
  try {
    const d = await get<any[]>('/aux/product-search', { q })
    return (Array.isArray(d) ? d : []).map((p: any) => ({ value: p.name, id: p.id, ...p }))
  } catch {
    return []
  }
}

const suggestions = ref<any[]>([])
const showSuggestions = ref(false)
let searchTimeout: ReturnType<typeof setTimeout> | null = null

function onProductInput() {
  form.productId = 0
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = setTimeout(async () => {
    suggestions.value = await searchProducts(form.productSearch)
    showSuggestions.value = suggestions.value.length > 0
  }, 300)
}
function onProductFocus() {
  if (form.productSearch && suggestions.value.length === 0) {
    searchProducts(form.productSearch).then((r) => {
      suggestions.value = r
      showSuggestions.value = r.length > 0
    })
  } else if (suggestions.value.length > 0) {
    showSuggestions.value = true
  }
}
function hideSuggestions() {
  setTimeout(() => { showSuggestions.value = false }, 150)
}
function selectProduct(p: any) {
  form.productId = p.id
  form.productSearch = p.value
  showSuggestions.value = false
  if (isOrder.value && form.deductStock) fetchAvailableStock()
}

// ===== Unified form =====
const today = new Date().toISOString().split('T')[0]
const form = reactive({
  type: 'order' as 'order' | 'stockin',
  orderType: 'normal' as 'normal' | 'custom',
  date: today,
  customer: '',
  productSearch: '',
  productId: 0,
  quantity: 1,
  deductStock: false,
  deductQuantity: 0,
  note: '',
  country: '',
})
const isOrder = computed(() => form.type === 'order')
const isCustomOrder = computed(() => form.orderType === 'custom')
const orderTypeOptions = [
  { value: 'normal', label: '常规订单' },
  { value: 'custom', label: '定制订单' },
]
const canAdd = computed(() => !!form.customer && !!form.productId && form.quantity > 0 && form.quantity <= 9999999 && !!form.date)

const countryDialogVisible = ref(false)
const newCountryName = ref('')

function openCountryDialog() {
  newCountryName.value = ''
  countryDialogVisible.value = true
}

function saveCountry() {
  const trimmed = newCountryName.value.trim()
  if (!trimmed) {
    showToast('请输入国家名称', 'warning')
    return
  }
  const ok = countryStore.addCountry(trimmed)
  if (ok) {
    form.country = trimmed
    countryDialogVisible.value = false
    showToast('国家保存成功', 'success')
  } else {
    showToast('该国家已存在', 'warning')
  }
}

const availableStock = ref(0)
const deductInfoVisible = ref(false)

async function fetchAvailableStock() {
  if (!form.productId || !form.customer) {
    availableStock.value = 0
    return
  }
  try {
    const res = (await get('/aux/available-stockins', { product_id: form.productId, customer: form.customer })) as any
    const items = res.stockins ?? res.items ?? res ?? []
    availableStock.value = items.reduce((s: number, i: any) => s + (i.available ?? i.quantity - (i.deducted || 0)), 0)
  } catch {
    availableStock.value = 0
  }
}

async function handleDeductPreview() {
  form.deductStock = !form.deductStock
  if (form.deductStock) {
    await fetchAvailableStock()
    deductInfoVisible.value = true
    form.deductQuantity = Math.min(form.quantity, availableStock.value)
  } else {
    form.deductQuantity = 0
    deductInfoVisible.value = false
  }
}
function openDeductEdit() {
  if (!form.deductStock) handleDeductPreview()
  deductInfoVisible.value = true
}

function addStaged() {
  if (!canAdd.value) {
    if (!form.productId && form.productSearch) {
      showToast('请从下拉列表中选择产品', 'warning')
    } else {
      showToast('请填写日期、客户和产品', 'warning')
    }
    return
  }
  stagedItems.value.push({
    type: form.type,
    orderType: form.orderType,
    customer: form.customer,
    productId: form.productId,
    productName: form.productSearch,
    quantity: form.quantity,
    date: form.date,
    note: form.note,
    country: isCustomOrder.value ? form.country : '',
    deductStock: isOrder.value ? form.deductStock : false,
    deductQuantity: isOrder.value && form.deductStock ? form.deductQuantity : 0,
  })
  form.productSearch = ''
  form.productId = 0
  form.quantity = 1
  form.note = ''
  form.orderType = 'normal'
  form.country = ''
  form.deductStock = false
  form.deductQuantity = 0
  deductInfoVisible.value = false
}

// ===== Staged items (unified) =====
const stagedItems = ref<any[]>([])
const stagedOrders = computed(() => stagedItems.value.filter((i: any) => i.type === 'order'))
const stagedStockins = computed(() => stagedItems.value.filter((i: any) => i.type === 'stockin'))

const submitting = ref(false)

async function submitOrders() {
  if (!stagedOrders.value.length) return
  submitting.value = true
  try {
    const payload = stagedOrders.value.map((i) => ({
      product_id: i.productId,
      customer: i.customer,
      quantity: i.quantity,
      deduct_stock: i.deductStock || false,
      deduct_quantity: i.deductQuantity || 0,
      note: i.note || '',
      order_date: i.date || '',
      order_type: i.orderType === 'custom' ? 'custom' : 'regular',
      country: i.country || '',
    }))
    await post('/aux/batch-submit-orders', { orders: payload })
    showToast('订单提交成功', 'success')
    stagedItems.value = stagedItems.value.filter((i) => i.type !== 'order')
    queryClient.invalidateQueries({ queryKey: ['orders-list'] })
    queryClient.invalidateQueries({ queryKey: ['stockins-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '提交失败', 'error')
  } finally {
    submitting.value = false
  }
}

async function submitStockins() {
  if (!stagedStockins.value.length) return
  submitting.value = true
  try {
    const payload = stagedStockins.value.map((i) => ({
      product_id: i.productId,
      customer: i.customer,
      quantity: i.quantity,
      note: i.note || '',
      stockin_date: i.date || '',
      order_type: i.orderType === 'custom' ? 'custom' : 'regular',
      country: i.country || '',
    }))
    await post('/aux/batch-submit-stockins', { stockins: payload })
    showToast('备货提交成功', 'success')
    stagedItems.value = stagedItems.value.filter((i) => i.type !== 'stockin')
    queryClient.invalidateQueries({ queryKey: ['stockins-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '提交失败', 'error')
  } finally {
    submitting.value = false
  }
}

// ===== Edit staged (unified) =====
const editStagedVisible = ref(false)
const editStagedIdx = ref(-1)
const editStagedData = ref<any>(null)
const editAvailableStock = ref(0)

function openEditStaged(idx: number) {
  editStagedIdx.value = idx
  editStagedData.value = { ...stagedItems.value[idx] }
  editStagedVisible.value = true
  if (editStagedData.value.type === 'order' && editStagedData.value.productId && editStagedData.value.customer) {
    get('/aux/available-stockins', {
      product_id: editStagedData.value.productId,
      customer: editStagedData.value.customer,
    })
      .then((res: any) => {
        const items = res.stockins ?? res.items ?? res ?? []
        editAvailableStock.value = items.reduce(
          (s: number, i: any) => s + (i.available ?? i.quantity - (i.deducted || 0)),
          0,
        )
      })
      .catch(() => {
        editAvailableStock.value = 0
      })
  }
}
function saveEditStaged() {
  if (editStagedIdx.value >= 0 && editStagedData.value) {
    if (editStagedData.value.deductQuantity > 0) editStagedData.value.deductStock = true
    stagedItems.value[editStagedIdx.value] = { ...editStagedData.value }
  }
  editStagedVisible.value = false
}

// ===== Batch upload (shared) =====
const excelFile = ref<File | null>(null)
const importing = ref(false)
const isDragOver = ref(false)
const excelInputRef = ref<HTMLInputElement | null>(null)

function handleExcelSelect(e: Event) {
  excelFile.value = (e.target as HTMLInputElement).files?.[0] ?? null
}
function onDrop(e: DragEvent) {
  isDragOver.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) excelFile.value = f
}
function downloadTemplate() {
  window.open('/api/v1/batch/download-template', '_blank')
}

async function handleImport() {
  if (!excelFile.value) return
  importing.value = true
  try {
    const fd = new FormData()
    fd.append('file', excelFile.value)
    if (isOrder.value) {
      await post('/staging-orders/import', fd)
      showToast('导入成功', 'success')
      const res = (await get('/staging-orders')) as any
      const items = res.staging_orders ?? res.items ?? []
      stagedItems.value.push(
        ...items.map((i: any) => ({
          type: 'order' as const,
          customer: i.customer,
          productId: i.product_id,
          productName: i.product_name,
          quantity: i.quantity,
          date: i.order_date,
          note: i.note,
          deductStock: i.deduct_stock,
          deductQuantity: i.deduct_quantity || 0,
        })),
      )
    } else {
      await post('/staging-stockins/import', fd)
      showToast('导入成功', 'success')
      const res = (await get('/staging-stockins')) as any
      const items = res.staging_stockins ?? res.items ?? []
      stagedItems.value.push(
        ...items.map((i: any) => ({
          type: 'stockin' as const,
          customer: i.customer,
          productId: i.product_id,
          productName: i.product_name,
          quantity: i.quantity,
          date: i.stockin_date,
          note: i.note,
          deductStock: false,
          deductQuantity: 0,
        })),
      )
    }
    excelFile.value = null
  } catch (err: any) {
    showToast(err.response?.data?.detail || '导入失败', 'error')
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
/* ===== 表单输入 ===== */
.form-number-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  transition: all 0.3s ease;
  outline: none;
  -moz-appearance: textfield;
}
.form-number-input::-webkit-inner-spin-button,
.form-number-input::-webkit-outer-spin-button {
  opacity: 1;
}
.form-number-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.form-text-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  transition: all 0.3s ease;
  outline: none;
}
.form-text-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

/* ===== 页面容器 ===== */
.co-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* ===== 主卡片 ===== */
.co-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  overflow: hidden;
}
.co-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.co-card-main:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
}

/* ===== 卡片头部 ===== */
.co-card-header {
  padding: 10px 24px;
  background: transparent;
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: flex-start;
  border-bottom: 2px solid var(--color-border, #cbd5e1);
  gap: 12px;
}
.co-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.co-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.co-card-title-group h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.co-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* ===== 图标色块 ===== */
.co-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.co-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

/* ===== 头部操作区 ===== */
.co-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}
.co-header-right {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
}

.co-tab-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

/* ===== 双栏主体 ===== */
.co-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
@media (max-width: 1024px) {
  .co-body {
    grid-template-columns: 1fr;
  }
}

/* ===== 栏目 ===== */
.co-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.co-col + .co-col {
  border-left: 2px solid var(--color-border, #cbd5e1);
}

/* ===== 栏目标题 ===== */
.co-col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
}
.co-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}

.co-col-scroll {
  padding: 16px 20px;
  overflow-y: auto;
  flex: 1;
}

/* ===== 区块标题（批量导入等 - 输入框风格） ===== */
.co-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  min-height: 40px;
  box-sizing: border-box;
  cursor: default;
  transition: all 0.3s ease;
}
.co-section-header:hover {
  border-color: var(--color-ocean-deep);
  background: var(--color-slate-50);
}
.co-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 6px;
}
.co-section-title i {
  color: var(--color-success-500);
}
.co-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  padding: 8px 0 4px;
}

/* ===== Droppable 标题栏 ===== */
.co-droppable {
  cursor: pointer;
}
.co-droppable.co-drag-over {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.co-droppable-label {
  display: flex !important;
  margin-bottom: 0;
  cursor: pointer;
  font-size: 14px !important;
  font-weight: 400 !important;
  color: var(--color-text-muted) !important;
}
.co-droppable-label .label-icon {
  color: var(--color-text-muted) !important;
}
.co-inline-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.co-inline-btn {
  padding: 3px 8px;
  border: 1px solid var(--color-border-light);
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  background: white;
  color: var(--color-text-secondary);
  transition: all 0.2s ease;
}
.co-inline-btn:hover {
  border-color: var(--color-ocean-deep);
  color: var(--color-primary-600);
}
.co-inline-btn-success {
  border-color: var(--color-success-400);
  color: var(--color-success-600);
}
.co-inline-btn-success:hover {
  background: var(--color-success-50);
}
.co-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.co-file-inline {
  font-size: 13px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.co-file-inline-success {
  color: var(--color-success-600);
}

/* ===== 类型切换 ===== */
.co-type-switch {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.co-type-btn {
  padding: 5px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
}
.co-type-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.co-type-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* ===== 表单 ===== */
.co-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}
.co-form-group {
  margin-bottom: 14px;
}
.co-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
}
.co-required {
  color: var(--color-danger-500);
}
.co-textarea {
  width: 100%;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  resize: vertical;
  outline: none;
  transition: all 0.3s ease;
  font-family: inherit;
}
.co-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.co-textarea::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}

/* ===== 抵扣 ===== */
.co-deduct-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
}
.co-btn-deduct {
  padding: 6px 12px;
  border: 2px solid var(--color-border-light);
  border-radius: 9px;
  background: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
}
.co-btn-deduct:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}
.co-btn-deduct.active {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  border-color: var(--color-primary-400);
}
.co-deduct-display {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 10px;
  border: 2px dashed var(--color-border-light);
  background: var(--color-surface, #f8fafc);
  cursor: pointer;
  transition: all 0.3s ease;
  color: var(--color-text-secondary);
}
.co-deduct-display:hover {
  border-color: var(--color-primary-400);
  background: var(--color-primary-50);
}
.co-deduct-display strong {
  color: var(--color-primary-600);
}
.co-deduct-info {
  margin-top: 6px;
  padding: 6px 0;
}
.co-deduct-info small {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ===== 暂存列表 ===== */
.co-staged-card {
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 8px;
  transition: all 0.3s ease;
}
.co-staged-card:hover {
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.co-staged-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.co-staged-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.co-staged-tag {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 4px;
}
.co-staged-tag i {
  font-size: 11px;
}
.co-staged-product {
  display: flex;
  align-items: center;
  gap: 4px;
  font-weight: 500;
}
.co-staged-actions {
  display: flex;
  gap: 4px;
  margin-left: 8px;
  flex-shrink: 0;
}

/* ===== 类型徽章 ===== */
.co-type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
}
.co-type-badge.order {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-type-badge.stockin {
  background: var(--color-success-100);
  color: var(--color-success-600);
}

/* ===== 操作按钮 ===== */
.co-btn-icon {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.co-btn-warn {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.co-btn-warn:hover {
  background: var(--color-warning-100);
  transform: translateY(-1px);
}
.co-btn-danger {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}
.co-btn-danger:hover {
  background: var(--color-danger-100);
  transform: translateY(-1px);
}
.co-btn-danger:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ===== 搜索建议 ===== */
.co-autocomplete {
  position: absolute;
  left: 0;
  right: 0;
  top: 100%;
  background: white;
  border: 2px solid var(--color-primary-200);
  border-radius: 12px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.12);
  z-index: 1000;
  max-height: 200px;
  overflow-y: auto;
}
.co-autocomplete-item {
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 13px;
}
.co-autocomplete-item:last-child {
  border-bottom: none;
}
.co-autocomplete-item:hover {
  background-color: var(--color-primary-50);
  transform: translateX(4px);
}

/* ===== Dropdown Animation ===== */
.co-dropdown-enter-active {
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.co-dropdown-leave-active {
  transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
}
.co-dropdown-enter-from {
  opacity: 0;
  transform: translateY(-8px) scale(0.96);
}
.co-dropdown-enter-to {
  opacity: 1;
  transform: translateY(0) scale(1);
}
.co-dropdown-leave-from {
  opacity: 1;
  transform: translateY(0) scale(1);
}
.co-dropdown-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
}

/* ===== 提交栏 ===== */
.co-submit-bar {
  text-align: center;
  padding: 16px 24px;
  border-top: 1px solid var(--color-border, #cbd5e1);
}

/* ===== 空状态 ===== */
.co-empty-state {
  text-align: center;
  padding: 40px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--color-text-secondary);
}
.co-empty-icon {
  font-size: 28px;
  opacity: 0.5;
}
.co-empty-state p {
  margin: 0;
  font-size: 14px;
}
</style>

<template>
  <div class="stock-out-tab">
    <!-- TAB: 录入 -->
    <div v-show="activeTab === 'input'" class="so-tab-content">
      <div class="so-body">
        <!-- 左栏：出货信息录入 -->
        <div class="so-col">
          <StockOutInputForm
            v-model:form="form"
            :customer-options="customerOptions"
            :shipment-info="shipmentInfo"
            :can-add="canAdd"
            :staged-count="staged.length"
            :search-fn="searchProductsForAutocomplete"
            @add-staged="addStaged"
            @product-select="onProductSelect"
            @clear-shipment="shipmentInfo = null"
            @ocr-staged="addOcrStaged"
            @imported="onStockoutImported"
          />
        </div>

        <!-- 右栏：暂存列表 -->
        <div class="so-col">
          <StockOutStagingList
            :staged="staged"
            :staged-total-qty="stagedTotalQty"
            @remove-item="removeStagedItem"
            @edit-item="openEditStaged"
          />
        </div>
      </div>

      <!-- 提交按钮 -->
      <div v-if="staged.length" class="so-submit-bar">
        <UiButton
          variant="danger"
          size="lg"
          :disabled="submitting"
          @click="submitBatch"
        >
          <FontAwesomeIcon icon="paper-plane" style="margin-right: 6px" aria-hidden="true" />
          {{ submitting ? '提交中…' : '添加出货' }}
        </UiButton>
      </div>
    </div>

    <!-- TAB: 记录查询 -->
    <div v-show="activeTab === 'records'" class="so-tab-content">
      <StockOutRecords ref="recordsRef" :customer-options="customerOptions" />
    </div>

    <!-- 编辑暂存出货弹窗 -->
    <StockOutEditStagedDialog
      v-model:open="editStagedOpen"
      v-model:form="editStagedForm"
      :customer-options="customerOptions"
      @save="saveEditStaged"
    />

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
import { ref, reactive, computed, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { stockApi } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import type { ShipmentInfo, StagedStockout, Product } from '@/types'
import { useStockOutActions } from './composables/useStockOutActions'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { showToast } from '@/composables/useToast'
import { toISODate } from '@/utils/format'
import { invalidateOrderDerivedQueries } from '@/utils/queryKeys'

import StockOutInputForm from './components/StockOutInputForm.vue'
import StockOutStagingList from './components/StockOutStagingList.vue'
import StockOutRecords from './components/StockOutRecords.vue'
import StockOutEditStagedDialog from './components/StockOutEditStagedDialog.vue'

const props = defineProps<{ activeTab: 'input' | 'records' }>()

const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()

// === 客户列表（目录 store 统一缓存，TTL 内跨视图复用） ===
const catalogStore = useCatalogStore()
catalogStore.ensureActiveCustomerNames().catch(() => {
  // 加载失败保持空列表，下次进入视图时重试
})
const customerNames = computed(() => catalogStore.activeCustomerNames.map((c) => c.name))
const customerOptions = computed(() => customerNames.value.map((name) => ({ value: name, label: name })))

// === 产品搜索 ===
async function searchProductsForAutocomplete(q: string): Promise<Product[]> {
  if (!q.trim()) return []
  try {
    const data = await stockApi.searchProducts(q)
    return Array.isArray(data) ? data : (data?.products ? [data.products] : [])
  } catch {
    return []
  }
}

function onProductSelect(product: Product) {
  form.productId = String(product.id)
  form.search = product.name
  fetchShipmentInfo()
}

// === 可出货量查询 ===
const shipmentInfo = ref<ShipmentInfo | null>(null)

async function fetchShipmentInfo() {
  if (!form.productId || !form.customer) {
    shipmentInfo.value = null
    return
  }
  try {
    const data = await stockApi.availableShipment(Number(form.productId), form.customer)
    shipmentInfo.value = data.data ?? null
  } catch {
    shipmentInfo.value = null
  }
}

// === 表单 ===
const today = toISODate()
const form = reactive({ customer: '', date: today, search: '', productId: '', quantity: 0, note: '' })

const canAdd = computed(() => {
  if (!form.customer || !form.productId || form.quantity < 1 || !form.date) return false
  return true
})

watch(() => form.customer, () => {
  if (form.productId) fetchShipmentInfo()
})

// === 暂存列表 ===
const staged = ref<StagedStockout[]>([])

async function removeStagedItem(idx: number) {
  const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
  if (!ok) return
  staged.value.splice(idx, 1)
}

const stagedTotalQty = computed(() => staged.value.reduce((sum: number, item: StagedStockout) => sum + (item.quantity || 0), 0))

async function addStaged() {
  if (!canAdd.value) {
    showToast('请选择客户和产品，并输入数量', 'warning')
    return
  }

  if (form.productId && form.customer) {
    if (shipmentInfo.value === null) {
      await fetchShipmentInfo()
    }
    const avail = shipmentInfo.value?.available_quantity
    if (avail !== undefined && form.quantity > avail) {
      showToast(`出货数量超过可出货量！可出货: ${avail}`, 'error')
      return
    }
  }

  staged.value.push({
    id: Date.now(),
    product_id: form.productId,
    product_name: form.search,
    customer: form.customer,
    date: form.date,
    quantity: form.quantity,
    note: form.note,
  })
  form.search = ''
  form.productId = ''
  form.quantity = 0
  form.note = ''
  shipmentInfo.value = null
}

/** OCR 粘贴识别确认后的条目：与手工录入进同一个暂存列表，提交前仍可改、删 */
function addOcrStaged(items: StagedStockout[]) {
  staged.value.push(...items)
}

// === 编辑暂存 ===
const editStagedOpen = ref(false)
const editStagedIdx = ref(-1)
const editStagedForm = reactive({ customer: '', date: '', productName: '', quantity: 1, note: '' })

function openEditStaged(idx: number) {
  editStagedIdx.value = idx
  const item = staged.value[idx]
  if (!item) return
  editStagedForm.customer = item.customer || ''
  editStagedForm.date = item.date || ''
  editStagedForm.productName = item.product_name || ''
  editStagedForm.quantity = item.quantity || 1
  editStagedForm.note = item.note || ''
  editStagedOpen.value = true
}

function saveEditStaged() {
  if (editStagedIdx.value < 0) return
  const item = staged.value[editStagedIdx.value]
  if (!item) return
  item.customer = editStagedForm.customer
  item.date = editStagedForm.date
  item.quantity = editStagedForm.quantity
  item.note = editStagedForm.note
  editStagedOpen.value = false
}

// === 批量提交 ===
const submitting = ref(false)
const recordsRef = ref<InstanceType<typeof StockOutRecords> | null>(null)

const { submitBatch } = useStockOutActions(staged, submitting, () => {
  recordsRef.value?.refresh()
  queryClient.invalidateQueries({ queryKey: ['pp-monthly'] })
  queryClient.invalidateQueries({ queryKey: ['pp-summary'] })
  // 出货会同时改变库存汇总与报表流水，统一失效派生查询
  invalidateOrderDerivedQueries(queryClient)
})

function onStockoutImported() {
  recordsRef.value?.refresh()
  queryClient.invalidateQueries({ queryKey: ['pp-monthly'] })
  queryClient.invalidateQueries({ queryKey: ['pp-summary'] })
  invalidateOrderDerivedQueries(queryClient)
}

// 切换到记录查询tab时自动加载数据（首次进入时触发）
watch(() => props.activeTab, (tab) => {
  if (tab === 'records') {
    recordsRef.value?.loadIfEmpty()
  }
})
</script>

<style scoped>
/* ===== Layout ===== */
.stock-out-tab {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.so-tab-content {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.so-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
@media (max-width: 992px) {
  .so-body { grid-template-columns: 1fr; }
}
.so-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.so-col + .so-col {
  border-left: 2px solid var(--color-border, #cbd5e1);
}

/* ===== Submit Bar ===== */
.so-submit-bar {
  display: flex;
  justify-content: center;
  padding: 8px 0;
  border-top: 1px solid var(--color-border, #cbd5e1);
}
</style>

<template>
  <div class="stock-out-tab">
    <!-- 录入主区（2026-10-06 记录查询 tab 移除，本组件只承载录入） -->
    <div class="so-tab-content">
      <div class="so-body">
        <!-- 左栏：出货信息录入 -->
        <div class="so-col">
          <StockOutInputForm
            v-model:form="form"
            :customer-options="customerOptions"
            :shipment-info="shipmentInfo"
            :batch-options="batchOptions"
            :can-add="canAdd"
            :staged-count="staged.length"
            :search-fn="searchProductsForAutocomplete"
            :list-fn="fetchSkuList"
            :empty-text="productEmptyText"
            @add-staged="addStaged"
            @product-select="onProductSelect"
            @clear-shipment="clearShipmentSelection"
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
import { stockApi, finishedStockApi } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import type { ShipmentInfo, StagedStockout, Product, BatchAvailable } from '@/types'
import { useStockOutActions } from './composables/useStockOutActions'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { showToast } from '@/composables/useToast'
import { toISODate } from '@/utils/format'
import { invalidateOrderDerivedQueries } from '@/utils/queryKeys'
import { useStockOutProductSearch } from './composables/useStockOutProductSearch'

import StockOutInputForm from './components/StockOutInputForm.vue'
import StockOutStagingList from './components/StockOutStagingList.vue'
import StockOutEditStagedDialog from './components/StockOutEditStagedDialog.vue'

const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()

// === 客户列表（目录 store 统一缓存，TTL 内跨视图复用） ===
const catalogStore = useCatalogStore()
catalogStore.ensureActiveCustomerNames().catch(() => {
  // 加载失败保持空列表，下次进入视图时重试
})
const customerNames = computed(() => catalogStore.activeCustomerNames.map((c) => c.name))
const customerOptions = computed(() => customerNames.value.map((name) => ({ value: name, label: name })))

function onProductSelect(product: Product) {
  form.productId = String(product.id)
  form.search = product.name
  fetchShipmentInfo()
  fetchBatchOptions()
}

// === 可出货量查询 ===
const shipmentInfo = ref<ShipmentInfo | null>(null)
/** 请求序号：快速切换 SKU/客户时丢弃过期响应（与 fetchBatchOptions 同款守卫；
 *  2026-10-17 审计 F-FE-DESK-CORE-02：原先无序号，慢响应后到会覆盖新 SKU 的
 *  可出货量——展示与超额闸门都按错值判定）。 */
let shipReqSeq = 0

async function fetchShipmentInfo() {
  if (!form.productId || !form.customer) {
    shipReqSeq++
    shipmentInfo.value = null
    return
  }
  const seq = ++shipReqSeq
  try {
    const data = await stockApi.availableShipment(Number(form.productId), form.customer)
    if (seq !== shipReqSeq) return // 已有更新的请求在途，丢弃过期响应
    shipmentInfo.value = data.data ?? null
  } catch {
    if (seq !== shipReqSeq) return
    shipmentInfo.value = null
  }
}

// === 成品库存批次列表（选定 SKU 后带出，供按批次扣减） ===
const batchOptions = ref<BatchAvailable[]>([])
/** 请求序号：快速切换 SKU/客户时丢弃过期响应，避免旧结果覆盖新结果 */
let batchReqSeq = 0

async function fetchBatchOptions() {
  if (!form.productId) {
    batchOptions.value = []
    return
  }
  const seq = ++batchReqSeq
  try {
    const res = await finishedStockApi.batches(Number(form.productId))
    if (seq !== batchReqSeq) return // 已有更新的请求在途，丢弃过期响应
    batchOptions.value = res.data ?? []
  } catch {
    if (seq !== batchReqSeq) return
    batchOptions.value = []
  }
  // 当前选中批次若不在新列表里则清空，避免提交一个不存在/不属于该产品的批次
  if (form.batchNo && !batchOptions.value.some((b) => b.batch_no === form.batchNo)) {
    form.batchNo = ''
  }
}

/** 产品选择被清空（StockOutInputForm 的 clear-shipment）：批次也要一并清掉 */
function clearShipmentSelection() {
  shipmentInfo.value = null
  batchOptions.value = []
  form.batchNo = ''
}

// === 表单 ===
const today = toISODate()
const form = reactive({ customer: '', date: today, search: '', productId: '', quantity: 0, note: '', batchNo: '' })

// === 产品搜索 / 浏览（与客户订单页同款：按客户过滤 + 点击查看全部） ===
const {
  searchProducts: searchProductsForAutocomplete,
  fetchSkuList,
  productEmptyText,
} = useStockOutProductSearch(form)

const canAdd = computed(() => {
  if (!form.customer || !form.productId || form.quantity < 1 || !form.date) return false
  return true
})

watch(() => form.customer, () => {
  if (form.productId) {
    fetchShipmentInfo()
    fetchBatchOptions()
  }
})

// === 暂存列表 ===
const staged = ref<StagedStockout[]>([])

async function removeStagedItem(idx: number) {
  const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
  if (!ok) return
  staged.value.splice(idx, 1)
}

const stagedTotalQty = computed(() => staged.value.reduce((sum: number, item: StagedStockout) => sum + (item.quantity || 0), 0))

/**
 * 批次级闸门（前端即时提示）：「已暂存同批次量 + 本次数量」不得超过该批次可用。
 * 必须计入已暂存：同一批次可多次新增出货，只比本次单条会放过累计超额
 * （提交时被后端批次闸门拒，只得到「部分出货成功」）。
 *
 * 同时服务于「新增出货」与「编辑暂存」两条路径（编辑时把被编辑项自身排除，
 * 否则它已被计入 staged，会把可用量算小）。返回 false 表示被拦下。
 *
 * 按 (产品, 客户, 批次) 累计：批次可用量是 (产品, 批次) 级事实，客户只用于把
 * 同一客户对该批次的多次暂存合并计数。
 */
function checkBatchAvailability(opts: {
  productId: string
  customer: string
  batchNo: string
  quantity: number
  excludeId?: number
}): boolean {
  if (!opts.batchNo) return true
  const opt = batchOptions.value.find((b) => b.batch_no === opts.batchNo)
  if (!opt) return true
  const stagedSameBatch = staged.value
    .filter((s) => s.product_id === opts.productId && s.customer === opts.customer
      && (s.batch_no || '') === opts.batchNo && s.id !== opts.excludeId)
    .reduce((sum, s) => sum + (s.quantity || 0), 0)
  if (stagedSameBatch + opts.quantity > opt.available_quantity) {
    showToast(`批次「${opts.batchNo}」可用不足！可用: ${opt.available_quantity}，已暂存: ${stagedSameBatch}`, 'error')
    return false
  }
  return true
}

async function addStaged() {
  if (!canAdd.value) {
    showToast('请选择客户和产品，并输入数量', 'warning')
    return
  }

  if (form.productId && form.customer) {
    // F-FE-DESK-CORE-02：无条件重拉——shipmentInfo 非 null 时可能是上一个
    // SKU/客户的陈旧值（闸门与展示都按它判定），null≠「已验证为最新」。
    await fetchShipmentInfo()
    const avail = shipmentInfo.value?.available_quantity
    if (avail !== undefined) {
      // 2026-10-17 审计 P2-45：产品级可出货量校验必须累计同产品/客户已暂存量，
      // 否则多次添加可累计超过可用量，提交时才被后端拒（部分出货成功）。
      const stagedSameProduct = staged.value
        .filter((s) => s.product_id === form.productId && s.customer === form.customer)
        .reduce((sum, s) => sum + (s.quantity || 0), 0)
      const effectiveAvail = avail - stagedSameProduct
      if (form.quantity > effectiveAvail) {
        showToast(
          `出货数量超过可出货量！可出货: ${effectiveAvail}（已暂存 ${stagedSameProduct}）`,
          'error',
        )
        return
      }
    }
  }

  if (!checkBatchAvailability({
    productId: form.productId,
    customer: form.customer,
    batchNo: form.batchNo,
    quantity: form.quantity,
  })) return

  staged.value.push({
    id: Date.now(),
    product_id: form.productId,
    product_name: form.search,
    customer: form.customer,
    date: form.date,
    quantity: form.quantity,
    note: form.note,
    batch_no: form.batchNo || undefined,
  })
  form.search = ''
  form.productId = ''
  form.quantity = 0
  form.note = ''
  form.batchNo = ''
  shipmentInfo.value = null
  batchOptions.value = []
}

/** OCR 粘贴识别确认后的条目：与手工录入进同一个暂存列表，提交前仍可改、删 */
function addOcrStaged(items: StagedStockout[]) {
  staged.value.push(...items)
}

// === 编辑暂存 ===
const editStagedOpen = ref(false)
const editStagedIdx = ref(-1)
// 注：编辑暂存弹窗不支持改批次（批次在列表徽标里展示，选错只能删了重加）；
// 故这里不引入 batchNo 字段，避免看似可改实则空转。
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
  // 2026-10-17 审计 P2-46：编辑对话框此前无输入校验（HTML min 不拦键入）
  if (!Number.isInteger(editStagedForm.quantity) || editStagedForm.quantity < 1) {
    showToast('数量必须为正整数', 'warning')
    return
  }
  // 批次闸门同样要过：编辑可把数量调大，绕过它就会在提交时才被后端拒（部分出货成功）。
  // excludeId 排除被编辑项自身——它已计入 staged，不排除会把可用量算小。
  if (!checkBatchAvailability({
    productId: item.product_id,
    customer: editStagedForm.customer,
    batchNo: item.batch_no || '',
    quantity: editStagedForm.quantity,
    excludeId: item.id,
  })) return
  item.customer = editStagedForm.customer
  item.date = editStagedForm.date
  item.quantity = editStagedForm.quantity
  item.note = editStagedForm.note
  editStagedOpen.value = false
}

// === 批量提交 ===
const submitting = ref(false)

const { submitBatch } = useStockOutActions(staged, submitting, () => {
  queryClient.invalidateQueries({ queryKey: ['pp-monthly'] })
  queryClient.invalidateQueries({ queryKey: ['pp-summary'] })
  // 出货会同时改变库存汇总与报表流水，统一失效派生查询
  invalidateOrderDerivedQueries(queryClient)
})

function onStockoutImported() {
  queryClient.invalidateQueries({ queryKey: ['pp-monthly'] })
  queryClient.invalidateQueries({ queryKey: ['pp-summary'] })
  invalidateOrderDerivedQueries(queryClient)
}
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

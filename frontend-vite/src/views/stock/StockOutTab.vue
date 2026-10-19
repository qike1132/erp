<template>
  <div class="stock-out-tab">

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
      :saving="editSaving"
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
import { finishedStockApi } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import type { ShipmentInfo, StagedStockout, Product, BatchAvailable } from '@/types'
import { useStockOutActions } from './composables/useStockOutActions'
import { useStockOutAvailabilityGates } from './composables/useStockOutAvailabilityGates'
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

/** 展示用：复用 composable 的请求函数（带序号守卫，F-FE-DESK-CORE-02）。 */
async function fetchShipmentInfo(productId?: string | number, customer?: string) {
  const pid = productId ?? form.productId
  const cust = customer ?? form.customer
  if (!pid || !cust) {
    shipmentInfo.value = null
    return
  }
  shipmentInfo.value = await fetchAvailableShipment(pid, cust)
}

// === 成品库存批次列表（选定 SKU 后带出，供按批次扣减） ===
const batchOptions = ref<BatchAvailable[]>([])
// 页面级/编辑级各自独立的序号池：编辑保存的批次请求不顶掉页面级在途请求（2026-10-19 OCR-2 L3）
const pageBatchSeq = { v: 0 }
const editBatchSeq = { v: 0 }

/** 清空页面级批次下拉时同步推进序号，让在途请求失效（否则迟到响应把旧产品批次写回，OCR-3 Low） */
function clearPageBatches() {
  pageBatchSeq.v++
  batchOptions.value = []
}

/** 按产品拉批次（null=被顶掉）；failValue=失败返回：页面级 []（清空下拉）/编辑级 null（放行后端兜底，OCR-2 M2） */
async function fetchBatchesForProduct(
  productId: string | number, seq: { v: number }, failValue: BatchAvailable[] | null = [],
): Promise<BatchAvailable[] | null> {
  const my = ++seq.v
  try {
    const res = await finishedStockApi.batches(Number(productId))
    return my !== seq.v ? null : (res.data ?? [])
  } catch {
    return my !== seq.v ? null : failValue
  }
}

async function fetchBatchOptions() {
  if (!form.productId) {
    clearPageBatches()
    return
  }
  const batches = await fetchBatchesForProduct(form.productId, pageBatchSeq)
  if (batches === null) return // 已有更新的请求在途，丢弃过期响应
  batchOptions.value = batches
  // 当前选中批次若不在新列表里则清空，避免提交一个不存在/不属于该产品的批次
  if (form.batchNo && !batchOptions.value.some((b) => b.batch_no === form.batchNo)) {
    form.batchNo = ''
  }
}

/** 产品选择被清空（StockOutInputForm 的 clear-shipment）：批次也要一并清掉 */
function clearShipmentSelection() {
  shipmentInfo.value = null
  clearPageBatches()
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
// 产品级累计闸门（2026-10-17 审计 P2-45 / 2026-10-18 OCR 复评）抽到 composable：
// 新增、编辑、OCR 暂存三条入口共用同一口径（本文件已贴 400 行门禁上限）。
const { fetchAvailableShipment, checkProductAvailability } = useStockOutAvailabilityGates(staged)

async function removeStagedItem(idx: number) {
  const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
  if (!ok) return
  staged.value.splice(idx, 1)
}

const stagedTotalQty = computed(() => staged.value.reduce((sum: number, item: StagedStockout) => sum + (item.quantity || 0), 0))

/** 批次级闸门：「已暂存同批次量 + 本次数量」≤ 批次可用（否则提交被后端拒=「部分出货成功」）；excludeId 排除被编辑项 */
function checkBatchAvailability(opts: {
  productId: string
  customer: string
  batchNo: string
  quantity: number
  excludeId?: number
  /** 批次列表：传数组=权威列表，找不到=批次已不存在（拦截，OCR-2 M2）；null=数据不可得（放行）；缺省=回落页面级列表 */
  batches?: BatchAvailable[] | null
  /** 批次缺失时的补救提示；编辑弹窗无批次控件，须提示删除重加而非「清除批次」（OCR-3 Low） */
  missingHint?: string
}): boolean {
  if (!opts.batchNo) return true
  // 显式 null=数据不可得：放行后端兜底（OCR-3 M2）。不得降级页面级列表——那装的是
  // form.productId 的批次，拿来校验 item.product_id 等于用别的产品做 allow/deny。
  if (opts.batches === null) return true
  const opt = (opts.batches ?? batchOptions.value).find((b) => b.batch_no === opts.batchNo)
  if (!opt) {
    if (!opts.batches) return true // 参数缺省=页面级列表未加载：放行，后端兜底
    showToast(`批次「${opts.batchNo}」已不存在（入库记录可能已删除），${opts.missingHint ?? '请清除批次后重试'}`, 'warning')
    return false
  }
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
  if (!Number.isInteger(form.quantity) || form.quantity < 1) {
    showToast('数量必须为正整数', 'warning')
    return
  }
  if (form.productId && form.customer) {
    // 产品级累计闸门（2026-10-17 审计 P2-45；含 F-FE-DESK-CORE-02 的无条件重拉）
    if (!await checkProductAvailability({
      productId: form.productId,
      customer: form.customer,
      quantity: form.quantity,
    })) return
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
  clearPageBatches()
}

/** OCR 粘贴识别确认后的条目：与手工录入进同一个暂存列表，提交前仍可改、删。
 *  2026-10-18 OCR 复评：这里必须保持**同步**——调用方 buildStaged 是同步 emit、
 * 随即归还 false 并清空草稿；改成 async 会在对话框已关闭后才因可用量不足
 * early return，用户看到「已加入」但数据被丢。可用量闸门由提交前的
 * useStockOutActions.submitBatch 预检统一兜底。 */
function addOcrStaged(items: StagedStockout[]) {
  const invalid = items.find((it) => !Number.isInteger(it.quantity) || it.quantity < 1)
  if (invalid) {
    showToast(`OCR 行数量无效（${invalid.quantity}），请修正后再暂存`, 'warning')
    return
  }
  staged.value.push(...items)
}

// === 编辑暂存 ===
const editStagedOpen = ref(false)
const editStagedIdx = ref(-1)
// 编辑弹窗不支持改批次（批次在列表徽标里展示，选错只能删了重加），不引入 batchNo 字段
const editStagedForm = reactive({ customer: '', date: '', productName: '', quantity: 1, note: '' })
const editSaving = ref(false) // 保存链路在途标记：双击守卫 + 弹窗保存按钮禁用（OCR-2 M1）

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

async function saveEditStaged() {
  if (editSaving.value || editStagedIdx.value < 0) return // 在途守卫：双击不重入（OCR-2 M1）
  const idx = editStagedIdx.value
  const item = staged.value[idx]
  const itemId = item?.id
  if (!item || itemId === undefined) return
  // 快照输入（OCR-3 M1）：两个 await 期间弹窗可被关/另开另一行，届时再读 editStagedForm
  // 会把新行的草稿写到本行上；全程只用这份快照。
  const draft = { customer: editStagedForm.customer, date: editStagedForm.date, quantity: editStagedForm.quantity, note: editStagedForm.note }
  if (!Number.isInteger(draft.quantity) || draft.quantity < 1) {
    showToast('数量必须为正整数', 'warning')
    return
  }
  // 空值守卫（OCR-3 M3）：对齐新增路径 canAdd 口径——date 可被清空、UiSelect 可为空，
  // 落成 customer/date 为空的条目后逐行被后端拒，用户只见「部分出货成功」且难定位。
  if (!draft.customer || !draft.date) {
    showToast('请填写客户和出货时间', 'warning')
    return
  }
  editSaving.value = true
  try {
    // await 后行可能被删/换位：itemId 不在原索引即放弃应用（OCR-3 M1）
    const sameItem = () => staged.value[idx]?.id === itemId
    // P1-20：暂存后 batchOptions 已清空，按条目 product_id 重拉权威批次；无 batch_no 短路（L4）；失败=null 放行（M2）
    const editBatches = item.batch_no ? await fetchBatchesForProduct(item.product_id, editBatchSeq, null) : []
    if (!sameItem()) return
    if (!checkBatchAvailability({
      productId: item.product_id, customer: draft.customer,
      batchNo: item.batch_no || '', quantity: draft.quantity,
      excludeId: itemId, batches: editBatches, missingHint: '请删除该行后重新添加',
    })) return

    const ok = await checkProductAvailability({
      productId: item.product_id, customer: draft.customer,
      quantity: draft.quantity, excludeId: itemId,
    })
    if (!ok || !sameItem()) return
    item.customer = draft.customer
    item.date = draft.date
    item.quantity = draft.quantity
    item.note = draft.note
    // 弹窗已另开他行时不得关掉用户刚打开的弹窗（OCR-3 M1）
    if (editStagedIdx.value === idx) editStagedOpen.value = false
  } finally {
    editSaving.value = false
  }
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
/* ===== Layout（单行排版：文件贴 400 行门禁，规则不变） ===== */
.stock-out-tab { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: hidden; }
.so-tab-content { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: hidden; }
.so-body { display: grid; grid-template-columns: 1fr 1fr; flex: 1; min-height: 0; overflow: hidden; }
@media (max-width: 992px) { .so-body { grid-template-columns: 1fr; } }
.so-col { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.so-col + .so-col { border-left: 2px solid var(--color-border, #cbd5e1); }
/* ===== Submit Bar ===== */
.so-submit-bar { display: flex; justify-content: center; padding: 8px 0; border-top: 1px solid var(--color-border, #cbd5e1); }
</style>

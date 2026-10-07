<template>
  <div class="mc-container">
    <div class="page-card page-card-main">
      <!-- 头部：标题 + 操作区（子组件，避免单文件超长） -->
      <MaterialCalcHeader
        :selected-count="selectedProductIds.length"
        :order-count="orderItems.length"
        :calc-status="calcStatus"
        :calculating="calculating"
        @batch="showBatchModal = true"
        @clear="clearAll"
      />

      <div class="page-card-body">
        <!-- Column 1: Product Selection -->
        <ProductSelectColumn
          :selected-product-ids="selectedProductIds"
          @toggle-product="toggleProduct"
          @add-product="addProductFromSearch"
        />

        <!-- Column 2: Order Quantity -->
        <OrderQuantityColumn
          :order-items="orderItems"
          :total-orders="totalOrders"
          @qty-input="onQtyInput"
          @remove="removeAndRecalc"
        />

        <!-- Column 3: Calculation Results（作用域切换 + 扁平回退） -->
        <CalcResultColumn
          :calc-results="calcResults"
          :has-results="hasResults"
          :calc-groups="calcGroups"
        />
      </div>
    </div>

    <!-- Batch Input Modal -->
    <UiDialog :open="showBatchModal" max-width-class="max-w-[400px]" @update:open="showBatchModal = $event">
      <template #header>
        <h3 class="text-base font-semibold text-text m-0">批量录入数量</h3>
      </template>
      <div class="py-2">
        <label class="block text-xs font-semibold text-text-secondary mb-1.5 uppercase tracking-wider">统一订单数量</label>
        <input v-model.number="batchQuantity" type="number" class="form-number-input" min="1" step="1" style="width: 100%" />
      </div>
      <template #footer>
        <UiButton variant="ghost" size="sm" @click="showBatchModal = false"> 取消 </UiButton>
        <UiButton variant="primary" size="sm" @click="applyBatch"> 应用到全部 </UiButton>
      </template>
    </UiDialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { type MaterialCalcProduct } from '@/api'
import {
  useMaterialCalculator,
  clampQuantity,
} from '@/composables/useMaterialCalculator'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import MaterialCalcHeader from './components/MaterialCalcHeader.vue'
import ProductSelectColumn from './components/ProductSelectColumn.vue'
import OrderQuantityColumn from './components/OrderQuantityColumn.vue'
import CalcResultColumn from './components/CalcResultColumn.vue'

// 计算引擎（全局 composable）：订单条目 / 分块结果 / 对比矩阵 / 防抖重算
const {
  orderItems,
  calcResults,
  calcGroups,
  calculating,
  selectedProductIds,
  totalOrders,
  hasResults,
  calcStatus,
  addProduct,
  removeProduct,
  clearAll,
  applyBatch: applyBatchQuantity,
  debounceCalc,
  dispose: disposeCalc,
} = useMaterialCalculator()

const showBatchModal = ref(false)
const batchQuantity = ref(1)

onUnmounted(() => {
  disposeCalc()
})

function toggleProduct(p: MaterialCalcProduct) {
  // S4: 无 BOM 产品在列表中不可交互（模板侧已禁用点击），此处仅处理有 BOM 的
  if (selectedProductIds.value.includes(p.id)) {
    removeProduct(p.id)
  } else {
    addProduct(p)
  }
  debounceCalc()
}

function removeAndRecalc(id: number) {
  removeProduct(id)
  debounceCalc()
}

function addProductFromSearch(p: MaterialCalcProduct, onSettled: (added: boolean) => void) {
  const added = addProduct(p)
  if (added) {
    debounceCalc()
  }
  onSettled(added)
}

// S7: 数量输入规整为非负整数
function onQtyInput(item: { quantity: number }) {
  item.quantity = clampQuantity(item.quantity)
  debounceCalc()
}

function applyBatch() {
  applyBatchQuantity(batchQuantity.value)
  showBatchModal.value = false
  debounceCalc()
}
</script>

<style scoped>
/* === 批量录入弹窗内的数字输入 === */
.form-number-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--color-text);
  font-family: inherit;
  -moz-appearance: textfield;
}
.form-number-input::-webkit-inner-spin-button,
.form-number-input::-webkit-outer-spin-button {
  opacity: 1;
}
.form-number-input:focus {
  outline: none;
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.15);
}
.form-number-input:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
}

/* === Layout === */
.mc-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* === Three Column Body ===
   覆盖全局 .page-card-body：三列 + 16px 间距。
   三列**不再等宽**（2026-10-07）：结果列内容最密（5 列表格 + 长物料名，
   等宽时名称被截断），左两列内容少、留白多 → 按 0.85 : 0.85 : 1.3 配比，
   把宽度让给结果列。 */
.page-card-body {
  display: grid;
  grid-template-columns: 0.85fr 0.85fr 1.3fr;
  gap: var(--sp-4);
  padding: var(--sp-4) var(--sp-5);
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 三列各自成为一个独立面板。
   ⚠️ 这三个 .mc-col 是子组件的**根元素**，所以父组件 scoped 样式能命中；
   子组件内部的 .mc-col-title 等则命中不了，必须写在各自子组件里。 */
.mc-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  border: var(--bw) solid var(--color-border);
  border-radius: var(--r-lg);
  background: var(--color-surface-card);
}
</style>

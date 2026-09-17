<template>
  <div class="mc-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <div class="mc-header-actions">
          <span class="count-badge">已选 {{ selectedProductIds.length }} 个</span>
          <button class="mc-action-btn mc-action-btn-primary" :disabled="orderItems.length === 0" aria-label="批量录入" @click="showBatchModal = true">
            <FontAwesomeIcon icon="layer-group" aria-hidden="true" />
            批量录入
          </button>
          <button class="mc-action-btn mc-action-btn-danger" :disabled="orderItems.length === 0" aria-label="清空" @click="clearAll">
            <FontAwesomeIcon icon="eraser" aria-hidden="true" />
            清空
          </button>
          <span v-if="calcStatus" :class="['mc-status-badge', calculating ? 'calculating' : 'done']">
            {{ calcStatus }}
          </span>
        </div>
      </div>

      <div class="page-card-body">
        <!-- Column 1: Product Selection（子组件化，模板与搜索/过滤逻辑原样搬移） -->
        <ProductSelectColumn
          :selected-product-ids="selectedProductIds"
          @toggle-product="toggleProduct"
          @add-product="addProductFromSearch"
        />

        <!-- Column 2: Order Quantity（子组件化，模板原样搬移） -->
        <OrderQuantityColumn
          :order-items="orderItems"
          :total-orders="totalOrders"
          @qty-input="onQtyInput"
          @remove="removeAndRecalc"
        />

        <!-- Column 3: Calculation Results（分块卡 + 扁平回退） -->
        <CalcResultColumn
          :calc-results="calcResults"
          :has-results="hasResults"
          :calc-groups="calcGroups"
        />
      </div>

      <!-- 跨角色对比矩阵：≥2 个作用域时展示；仅 1 个作用域时隐藏并提示（A-11） -->
      <div v-if="matrix.visible" class="mc-matrix-section">
        <RoleMatrix :scopes="matrix.scopes" :rows="matrix.rows" />
      </div>
      <div v-else-if="matrix.reason === 'single-scope'" class="mc-matrix-hint">
        <FontAwesomeIcon icon="circle-info" aria-hidden="true" />
        当前仅 1 个作用域（无角色区分），无需跨角色对比
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
import ProductSelectColumn from './components/ProductSelectColumn.vue'
import OrderQuantityColumn from './components/OrderQuantityColumn.vue'
import CalcResultColumn from './components/CalcResultColumn.vue'
import RoleMatrix from './components/RoleMatrix.vue'

// 计算引擎（全局 composable）：订单条目 / 分块结果 / 对比矩阵 / 防抖重算
const {
  orderItems,
  calcResults,
  calcGroups,
  calculating,
  selectedProductIds,
  totalOrders,
  hasResults,
  matrix,
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
.form-number-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
/* === Layout === */
.mc-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* === Main Card === */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */

/* === Card Header === */
/* 卡片头部样式已迁移到全局 .page-card-header（src/styles/app.css） */

/* === Three Column Body === */
/* 卡片主体样式已迁移到全局 .page-card-body（src/styles/app.css） */
/* 此处需要 3 列网格布局，覆盖默认 page-card-body */
.page-card-body {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.mc-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.mc-col + .mc-col {
  border-left: 1px solid var(--color-border-light, #f1f5f9);
}

.mc-col-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
}

.mc-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}

/* === Matrix Section === */
.mc-matrix-section {
  flex-shrink: 0;
  overflow: auto;
  border-top: 1px solid var(--color-border-light, #f1f5f9);
}

.mc-matrix-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px 14px;
  font-size: 12px;
  color: var(--color-text-secondary);
  border-top: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
}

/* === Header Actions === */
.mc-header-actions {
  display: flex;
  gap: 8px;
}

.mc-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease, transform 0.3s ease;
  background: white;
}

.mc-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.mc-action-btn i {
  font-size: 11px;
}

.mc-action-btn-primary {
  color: var(--color-primary-600);
}

.mc-action-btn-primary:hover:not(:disabled) {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

.mc-action-btn-danger {
  color: var(--color-danger-500);
}

.mc-action-btn-danger:hover:not(:disabled) {
  background: var(--color-danger-50);
  border-color: var(--color-danger-200);
  transform: translateY(-1px);
}

/* === Status Badge === */
.mc-status-badge {
  padding: 5px 12px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}

.mc-status-badge.calculating {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}

.mc-status-badge.done {
  background: var(--color-success-50);
  color: var(--color-success-600);
}
</style>

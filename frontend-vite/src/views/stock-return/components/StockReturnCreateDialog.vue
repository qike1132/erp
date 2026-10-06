<template>
  <UiDialog
    :open="open"
    title="新增退货"
    max-width-class="max-w-3xl"
    :close-on-overlay-click="false"
    @update:open="emit('update:open', $event)"
  >
    <div class="sr-dialog-body">
      <div class="sr-hint">
        <FontAwesomeIcon icon="info-circle" aria-hidden="true" />
        搜索产品名 -> 勾选要退的出货明细 -> 录数量；确认后回补库存并重算订单状态
      </div>

      <div class="sr-search-row">
        <input
          v-model="searchKeyword"
          class="sr-input grow"
          placeholder="输入产品名称搜索出货明细，如：鲨鱼"
          @keyup.enter="emit('search')"
        />
        <button class="sr-btn sr-btn-primary" :disabled="loadingShipments" @click="emit('search')">
          {{ loadingShipments ? '搜索中…' : '搜索' }}
        </button>
      </div>

      <div class="sr-ship-table" :class="{ loading: loadingShipments }">
        <table>
          <thead>
            <tr>
              <th class="pick-col">选择</th>
              <th>出货单号</th>
              <th>客户</th>
              <th>产品</th>
              <th class="num">数量</th>
              <th class="num">已退</th>
              <th class="num">可退</th>
              <th>出货日期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loadingShipments">
              <td colspan="8" class="empty">加载中…</td>
            </tr>
            <tr v-else-if="shipments.length === 0">
              <td colspan="8" class="empty">没有可退的出货明细（该产品未出货或已退完）</td>
            </tr>
            <tr
              v-for="s in shipments"
              v-else
              :key="s.stockout_id"
              :class="{ picked: pickedId === s.stockout_id }"
              @click="onPick(s)"
            >
              <td class="pick-col">
                <input
                  type="radio"
                  name="shipment-pick"
                  :checked="pickedId === s.stockout_id"
                  :aria-label="'选择出货单 ' + s.stockout_no"
                  @click.stop="onPick(s)"
                />
              </td>
              <td class="mono">{{ s.stockout_no }}</td>
              <td>{{ s.customer || '-' }}</td>
              <td>{{ s.product_name }}</td>
              <td class="num">{{ s.quantity }}</td>
              <td class="num">{{ s.returned_quantity }}</td>
              <td class="num hl">{{ s.available }}</td>
              <td>{{ s.stockout_date }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <template v-if="picked">
        <div class="sr-grid">
          <div class="sr-field">
            <label>退货数量（件）<span class="req">*</span></label>
            <input
              v-model.number="form.quantity"
              type="number"
              min="1"
              :max="form.available ?? undefined"
              :placeholder="'请输入，不超过 ' + (form.available ?? '') + ' 件'"
              class="sr-input"
            />
          </div>
          <div class="sr-field">
            <label>退货原因 <span class="req">*</span></label>
            <select v-model="form.reason" class="sr-select">
              <option value="" disabled>请选择</option>
              <option v-for="r in RETURN_REASON_OPTIONS" :key="r" :value="r">{{ r }}</option>
            </select>
          </div>
        </div>
        <div class="sr-field">
          <label>备注</label>
          <textarea v-model="form.note" class="sr-textarea" rows="2" placeholder="运输破损、责任说明等可补充在此…" />
        </div>
      </template>
    </div>

    <template #footer>
      <button class="sr-btn" :disabled="submitting" @click="emit('update:open', false)">取消</button>
      <button class="sr-btn sr-btn-primary" :disabled="submitting || !form.stockout_id" @click="emit('submit')">
        {{ submitting ? '提交中…' : '确认退货' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * StockReturnCreateDialog.vue - 新增退货弹窗（搜产品 -> 选出货明细 -> 录数量）
 *
 * 第一步：按产品名搜索，弹出该产品全部可退出货明细（单号/客户/数量/已退/可退/日期）；
 * 第二步：勾选要退的明细，可退上限自动带入数量约束；客户/产品由明细带出，无需单独录入。
 */
import { computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import type { ShipmentOption } from '@/api/stockReturn'
import { RETURN_REASON_OPTIONS, type StockReturnFormData } from '../composables/useStockReturn'

const props = defineProps<{
  open: boolean
  submitting: boolean
  shipments: ShipmentOption[]
  loadingShipments: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  submit: []
  search: []
  pick: [row: ShipmentOption]
}>()

/** 表单对象由 composable 持有（reactive）；经 v-model:form 传入，避免直接改 prop */
const form = defineModel<StockReturnFormData>('form', { required: true })

const searchKeyword = defineModel<string>('searchKeyword', { required: true })

const pickedId = computed(() => form.value.stockout_id)
const picked = computed(() => !!form.value.stockout_id)

function onPick(s: ShipmentOption) {
  emit('pick', s)
}

</script>

<style scoped>
.sr-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 4px 2px;
}
.sr-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--color-ocean-light, #d4f1f4);
  border: 1px solid var(--color-ocean, #b0e0e6);
  color: var(--color-ocean-text, #02669e);
  font-size: 12px;
  font-weight: 600;
}
.sr-search-row {
  display: flex;
  gap: 8px;
}
.sr-search-row .sr-input.grow {
  flex: 1;
}
.sr-ship-table {
  border: 1px solid var(--color-border, #e4e7ed);
  max-height: 260px;
  overflow-y: auto;
}
.sr-ship-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.sr-ship-table thead th {
  background: #f8fafc;
  color: #334155;
  font-weight: 700;
  text-align: left;
  padding: 7px 10px;
  border-bottom: 1px solid var(--color-border, #e4e7ed);
  position: sticky;
  top: 0;
}
.sr-ship-table tbody td {
  padding: 7px 10px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
  color: var(--color-text);
}
.sr-ship-table tbody tr {
  cursor: pointer;
}
.sr-ship-table tbody tr:hover td {
  background: var(--color-primary-50, #eff5ff);
}
.sr-ship-table tbody tr.picked td {
  background: var(--color-primary-100, #d6e4ff);
}
.sr-ship-table .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.sr-ship-table .hl {
  color: var(--color-success-700, #2e7d32);
  font-weight: 700;
}
.sr-ship-table .pick-col {
  width: 44px;
  text-align: center;
}
.sr-ship-table .empty {
  text-align: center;
  color: var(--color-text-muted, #64748b);
  padding: 18px 10px;
}
.mono {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--color-primary-700);
}
.sr-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.sr-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sr-field label {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-secondary);
}
.sr-field .req {
  color: var(--color-danger-500);
}
.sr-input,
.sr-select,
.sr-textarea {
  min-height: 34px;
  padding: 4px 10px;
  border: 1px solid var(--color-border, #e4e7ed);
  font-size: 13px;
  color: var(--color-text);
  background: white;
  box-sizing: border-box;
}
.sr-textarea {
  resize: vertical;
}
.sr-input:focus,
.sr-select:focus,
.sr-textarea:focus {
  outline: none;
  border-color: var(--color-primary-300);
}
.sr-btn {
  min-height: 34px;
  padding: 0 16px;
  border: 1px solid var(--color-border, #e4e7ed);
  background: white;
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-secondary);
  cursor: pointer;
}
.sr-btn-primary {
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
  color: white;
}
.sr-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

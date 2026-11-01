<template>
  <div class="pr-rows">
    <table class="pr-rows-table">
      <thead>
        <tr>
          <th class="c-idx">#</th>
          <th>产品</th>
          <th class="c-qty">数量</th>
          <th v-if="batchColumnOn" class="c-batch">
            <div class="c-batch-head">
              <span>批次号<span v-if="batchRequired" class="c-req">必填</span><span v-else class="c-opt">选填</span></span>
              <button type="button" class="pr-rows-fill" data-test="qe-fill-batch" title="把第一行的批次号铺到所有空行" @click="emit('fill-batch')">
                本列同批次
              </button>
            </div>
          </th>
          <th v-if="isPackaging" class="c-custom">定制</th>
          <th class="c-remark">备注</th>
          <th class="c-sum">小计</th>
          <th class="c-act"><span class="sr-only">操作</span></th>
        </tr>
      </thead>
      <tbody>
        <template v-for="(row, i) in rows" :key="row.key">
          <tr :class="['pr-row', { 'has-error': !!row.error }]" data-test="qe-row">
            <td class="c-idx">{{ i + 1 }}</td>
            <td class="c-prod">
              <div class="c-prod-name" :title="row.product_name">{{ row.product_name }}</div>
              <div class="c-prod-meta">
                <span v-if="row.barcode" class="c-code">{{ row.barcode }}</span>
                <label class="c-price" title="单价（自动带出，可改）">
                  <span>¥</span>
                  <input
                    v-model.number="row.unit_price"
                    type="number"
                    min="0"
                    step="0.01"
                    class="c-price-input"
                    data-test="qe-price"
                    aria-label="单价"
                    :disabled="disabled"
                  />
                </label>
                <span v-if="row.duplicate_qty > 0" class="c-dup" data-test="qe-dup" title="今日同部门同产品已录数量，仅提示不阻断">
                  今日已录 {{ row.duplicate_qty }}
                </span>
              </div>
            </td>
            <td class="c-qty">
              <div class="c-step">
                <button type="button" aria-label="减1" :disabled="disabled" @click="emit('adjust', row, -1)">−</button>
                <input
                  v-model.number="row.quantity"
                  type="number"
                  min="0"
                  inputmode="numeric"
                  placeholder="0"
                  aria-label="生产数量"
                  data-test="qe-qty"
                  :data-qty-key="row.key"
                  :disabled="disabled"
                  @input="row.error = ''"
                  @keydown.up.prevent="emit('qty-arrow', row, 1, $event)"
                  @keydown.down.prevent="emit('qty-arrow', row, -1, $event)"
                  @keydown.enter.prevent="emit('qty-enter')"
                />
                <button type="button" aria-label="加1" :disabled="disabled" @click="emit('adjust', row, 1)">＋</button>
              </div>
            </td>
            <td v-if="batchColumnOn" class="c-batch">
              <input
                v-model="row.batch_no"
                type="text"
                class="pr-input c-batch-input"
                :class="{ 'is-bad': batchRequired && !row.batch_no.trim() && !!row.error }"
                placeholder="如 0464628801"
                maxlength="100"
                autocomplete="off"
                data-test="qe-batch"
                :disabled="disabled"
                @input="row.error = ''"
              />
            </td>
            <td v-if="isPackaging" class="c-custom">
              <label class="c-check">
                <input v-model="row.is_custom" type="checkbox" data-test="qe-custom" :disabled="disabled" />
                <span>定制</span>
              </label>
              <input
                v-if="row.is_custom"
                v-model="row.custom_country"
                type="text"
                class="pr-input c-country"
                placeholder="定制国家"
                maxlength="100"
                data-test="qe-country"
                :disabled="disabled"
                @input="row.error = ''"
              />
            </td>
            <td class="c-remark">
              <input
                v-model="row.remark"
                type="text"
                class="pr-input"
                placeholder="选填"
                maxlength="500"
                data-test="qe-remark"
                :disabled="disabled"
              />
            </td>
            <td class="c-sum">{{ formatCurrency((row.quantity || 0) * (row.unit_price || 0)) }}</td>
            <td class="c-act">
              <button type="button" class="c-del" aria-label="删除此行" data-test="qe-remove" :disabled="disabled" @click="emit('remove', row)">
                <FontAwesomeIcon icon="times" aria-hidden="true" />
              </button>
            </td>
          </tr>
          <tr v-if="row.error" class="pr-row-error">
            <td :colspan="colspan" data-test="qe-row-error">
              <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" /> {{ row.error }}
            </td>
          </tr>
        </template>
      </tbody>
    </table>
    <div v-if="!rows.length" class="pr-rows-empty" data-test="qe-empty">
      还没有 SKU —— 在上方搜索框输入产品名或 69 码，回车加入；也可以点「粘贴 Excel」整列导入
    </div>
    <div v-else class="pr-rows-end">清单末尾 · 继续在上方搜索框追加，或粘贴 Excel 整列</div>
  </div>
</template>

<script setup lang="ts">
/**
 * ProductionEntryTable — 方向 A 的行表：一行 = 一个 SKU。
 *
 * 行对象由 useProductionEntry 持有，这里只做展示与轻量编辑（v-model 直接写行字段），
 * 数量步进/删除/铺满批次这类带副作用的动作仍然交回 composable。
 */
import { computed } from 'vue'
import { formatCurrency } from '@/utils/format'
import type { EntryRow } from '../composables/useProductionEntry'

const props = defineProps<{
  rows: EntryRow[]
  batchColumnOn: boolean
  batchRequired: boolean
  isPackaging: boolean
  disabled: boolean
}>()

const emit = defineEmits<{
  remove: [row: EntryRow]
  adjust: [row: EntryRow, delta: number]
  'qty-arrow': [row: EntryRow, direction: number, event: KeyboardEvent]
  'qty-enter': []
  'fill-batch': []
}>()

const colspan = computed(() => 6 + (props.batchColumnOn ? 1 : 0) + (props.isPackaging ? 1 : 0))
</script>

<style scoped>
.pr-rows { flex: 1; min-height: 0; overflow: auto; border: 1px solid var(--color-border); border-radius: 12px; background: #fff; }
.pr-rows-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 16px; min-width: 1140px; }
.pr-rows-table th { position: sticky; top: 0; z-index: 2; background: var(--color-surface); border-bottom: 1px solid var(--color-border); padding: 12px 12px; font-size: 13.5px; font-weight: 700; color: var(--color-text-secondary); text-align: left; white-space: nowrap; }
.pr-rows-table td { border-bottom: 1px solid var(--color-border-light); padding: 12px 12px; vertical-align: middle; }
.pr-row:hover td { background: #fbfcfe; }
.c-idx { width: 36px; text-align: center; color: var(--color-text-placeholder); font-size: 13px; padding-right: 0 !important; }
.c-prod { min-width: 210px; }
.c-prod-name { font-size: 17px; font-weight: 700; color: var(--color-text); line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.c-prod-meta { display: flex; align-items: center; gap: 8px; margin-top: 2px; flex-wrap: wrap; }
.c-code { font-size: 13px; color: var(--color-text-placeholder); font-family: 'SF Mono', Consolas, monospace; }
.c-price { display: inline-flex; align-items: center; gap: 3px; font-size: 13px; color: var(--color-text-muted); }
.c-price-input { width: 74px; border: none; border-bottom: 1px dashed var(--color-border-strong); background: transparent; font-size: 13px; font-weight: 700; color: var(--color-text-secondary); padding: 0 3px; outline: none; font-family: inherit; -moz-appearance: textfield; }
.c-price-input::-webkit-outer-spin-button, .c-price-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.c-price-input:focus { border-bottom-color: var(--color-primary-500); color: var(--color-primary-700); }
.c-dup { font-size: 13px; font-weight: 700; color: var(--color-warning-600); background: var(--color-warning-50); border: 1px solid var(--color-warning-200); border-radius: 5px; padding: 0 5px; }
.c-qty { width: 168px; }
.c-step { display: inline-flex; align-items: stretch; height: 52px; border: 1px solid var(--color-border); border-radius: 10px; overflow: hidden; background: #fff; }
.c-step:focus-within { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.14); }
.c-step button { width: 36px; border: none; background: var(--color-surface); color: var(--color-text-secondary); font-size: 19px; font-weight: 700; cursor: pointer; padding: 0; }
.c-step button:hover:not(:disabled) { background: var(--color-primary-700); color: #fff; }
.c-step input { width: 100%; min-width: 0; border: none; outline: none; text-align: center; font-size: 18px; font-weight: 800; font-variant-numeric: tabular-nums; color: var(--color-text); background: transparent; -moz-appearance: textfield; }
.c-step input::-webkit-outer-spin-button, .c-step input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.c-batch { width: 236px; }
.c-batch-head { display: flex; align-items: center; gap: 8px; }
.c-req { margin-left: 6px; font-size: 12px; font-weight: 800; color: var(--color-warning-700); background: var(--color-warning-50); border: 1px solid var(--color-warning-200); border-radius: 4px; padding: 0 4px; }
.c-opt { margin-left: 6px; font-size: 12px; font-weight: 600; color: var(--color-text-placeholder); }
.pr-rows-fill { border: 1px dashed var(--color-border-strong); background: #fff; color: var(--color-text-muted); font-size: 13px; font-weight: 600; border-radius: 7px; padding: 3px 9px; cursor: pointer; font-family: inherit; white-space: nowrap; }
.pr-rows-fill:hover { border-color: var(--color-primary-400); color: var(--color-primary-700); background: var(--color-primary-50); }
.c-custom { width: 150px; }
.c-check { display: inline-flex; align-items: center; gap: 7px; font-size: 13.5px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; }
.c-country { margin-top: 6px; }
.c-remark { width: 160px; }
.c-sum { width: 128px; text-align: right; font-size: 17px; font-weight: 800; font-variant-numeric: tabular-nums; color: var(--color-text-secondary); white-space: nowrap; }
.c-act { width: 44px; padding-left: 0 !important; }
.c-del { width: 30px; height: 30px; border: none; border-radius: 7px; background: transparent; color: var(--color-text-placeholder); display: grid; place-items: center; cursor: pointer; }
.c-del:hover:not(:disabled) { background: var(--color-danger-50); color: var(--color-danger-600); }
.pr-input { width: 100%; height: 52px; padding: 0 13px; border: 1px solid var(--color-border); border-radius: 10px; background: #fff; font-size: 16px; color: var(--color-text); outline: none; font-family: inherit; box-sizing: border-box; }
.pr-input::placeholder { color: var(--color-text-placeholder); }
.pr-input:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.13); }
.pr-input.is-bad { border-color: var(--color-danger-500); background: #fffafa; }
.c-batch-input { font-family: 'SF Mono', Consolas, monospace; letter-spacing: 0.02em; }
.pr-row.has-error td { background: #fffafa; }
.pr-row-error td { padding: 6px 14px 10px; font-size: 13.5px; font-weight: 600; color: var(--color-danger-600); background: #fffafa; border-bottom: 1px solid var(--color-border-light); }
.pr-rows-empty { padding: 44px 16px; text-align: center; font-size: 15px; color: var(--color-text-placeholder); }
.pr-rows-end { padding: 14px; text-align: center; font-size: 13.5px; color: var(--color-text-placeholder); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
@media (max-width: 1100px) {
  .c-remark { display: none; }
}
</style>

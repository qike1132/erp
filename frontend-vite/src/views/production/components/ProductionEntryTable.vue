<template>
  <div class="pr-rows">
    <table class="pr-rows-table">
      <!-- table-layout:fixed + 百分比列宽：剩余空间按比例摊给所有列，
           而不是全灌进「产品」列（现场反馈产品列右侧空白过大）。
           产品列不给宽度 = 吃掉剩余部分，数据列按百分比保底。 -->
      <colgroup>
        <col class="col-idx" />
        <col class="col-prod" />
        <col class="col-qty" />
        <col v-if="batchColumnOn" class="col-batch" />
        <col v-if="isPackaging" class="col-custom" />
        <col class="col-act" />
      </colgroup>
      <thead>
        <tr>
          <th class="c-idx">#</th>
          <th>产品</th>
          <th class="c-qty">数量</th>
          <th v-if="batchColumnOn" class="c-batch">批次号</th>
          <th v-if="isPackaging" class="c-custom">定制国家</th>
          <th class="c-act"><span class="sr-only">操作</span></th>
        </tr>
      </thead>
      <tbody>
        <template v-for="(row, i) in rows" :key="row.key">
          <tr :class="['pr-row', { 'has-error': !!row.error }]" data-test="qe-row">
            <td class="c-idx">{{ i + 1 }}</td>
            <td class="c-prod">
              <div class="c-prod-name" :title="row.product_name">{{ row.product_name }}</div>
            </td>
            <td class="c-qty">
              <input
                :value="row.quantity === 0 ? '' : row.quantity"
                type="number"
                min="0"
                inputmode="numeric"
                placeholder=""
                aria-label="生产数量"
                data-test="qe-qty"
                :data-qty-key="row.key"
                class="pr-input c-qty-input"
                :disabled="disabled"
                @input="onQtyInput(row, $event)"
                @keydown.up.prevent="emit('qty-arrow', row, 1, $event)"
                @keydown.down.prevent="emit('qty-arrow', row, -1, $event)"
                @keydown.enter.prevent="emit('qty-enter')"
              />
            </td>
            <td v-if="batchColumnOn" class="c-batch">
              <input
                v-model="row.batch_no"
                type="text"
                class="pr-input c-batch-input"
                :class="{ 'is-bad': !!row.error }"
                placeholder="如 0464628801"
                maxlength="100"
                autocomplete="off"
                data-test="qe-batch"
                :disabled="disabled"
                @input="row.error = ''"
              />
            </td>
            <td v-if="isPackaging" class="c-custom">
              <input
                v-model="row.custom_country"
                type="text"
                class="pr-input c-country"
                placeholder="定制国家，填了即定制"
                maxlength="100"
                aria-label="定制国家（填写后自动按定制处理）"
                data-test="qe-country"
                :disabled="disabled"
                @input="onCountryInput(row)"
              />
            </td>
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
import type { EntryRow } from '../composables/useProductionEntry'

const props = defineProps<{
  rows: EntryRow[]
  batchColumnOn: boolean
  isPackaging: boolean
  disabled: boolean
}>()

const emit = defineEmits<{
  remove: [row: EntryRow]
  'qty-arrow': [row: EntryRow, direction: number, event: KeyboardEvent]
  'qty-enter': []
}>()

const colspan = computed(() => 4 + (props.batchColumnOn ? 1 : 0) + (props.isPackaging ? 1 : 0))

/** 数量输入：空串按 0 存，0 在界面上显示为空（默认不是 0） */
function onQtyInput(row: EntryRow, event: Event) {
  const raw = (event.target as HTMLInputElement).value
  row.quantity = raw === '' ? 0 : Number(raw)
  row.error = ''
}

/** 定制国家输入框即开关：填了国家 = 该行按定制处理，清空 = 非定制 */
function onCountryInput(row: EntryRow) {
  row.is_custom = row.custom_country.trim().length > 0
  row.error = ''
}
</script>

<style scoped>
.pr-rows { flex: 1; min-height: 0; overflow: auto; background: #fff; }
.pr-rows-table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0; font-size: 14.5px; min-width: 940px; }
.pr-rows-table th.c-qty, .pr-rows-table th.c-batch, .pr-rows-table th.c-custom { text-align: center; }
.pr-rows-table td.c-qty, .pr-rows-table td.c-batch, .pr-rows-table td.c-custom { text-align: center; }
.c-batch .pr-input, .c-custom .pr-input { text-align: center; }
.col-idx { width: 3.5%; }
.col-qty { width: 12%; }
.col-batch { width: 17%; }
.col-custom { width: 11.5%; }
.col-act { width: 4%; }
.pr-rows-table th { position: sticky; top: 0; z-index: 2; background: #fff; border-bottom: 1px solid var(--color-border); padding: 9px 10px; font-size: 12.5px; font-weight: 700; color: var(--color-text-secondary); text-align: left; white-space: nowrap; }
.pr-rows-table td { border-bottom: 1px solid var(--color-border-light); padding: 9px 10px; vertical-align: middle; }
.pr-row:hover td { background: #fbfcfe; }
.c-idx { text-align: center; color: var(--color-text-placeholder); font-size: 12px; padding-right: 0 !important; }
.c-prod-name { font-size: 14px; font-weight: 700; color: var(--color-text); line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.c-qty-input { text-align: center; font-weight: 800; font-variant-numeric: tabular-nums; -moz-appearance: textfield; }
.c-qty-input::-webkit-outer-spin-button, .c-qty-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.c-req { margin-left: 6px; font-size: 12px; font-weight: 800; color: var(--color-warning-700); background: var(--color-warning-50); border: 1px solid var(--color-warning-200); border-radius: 4px; padding: 0 4px; }
.c-country { width: 100%; }
.c-act { padding-left: 0 !important; }
.c-del { width: 26px; height: 26px; border: none; border-radius: 7px; background: transparent; color: var(--color-text-placeholder); display: grid; place-items: center; cursor: pointer; }
.c-del:hover:not(:disabled) { background: var(--color-danger-50); color: var(--color-danger-600); }
.pr-input { width: 100%; height: 34px; padding: 0 9px; border: 1px solid var(--color-border); border-radius: 7px; background: #fff; font-size: 13px; color: var(--color-text); outline: none; font-family: inherit; box-sizing: border-box; }
.pr-input::placeholder { color: var(--color-text-placeholder); }
.pr-input:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.13); }
.pr-input.is-bad { border-color: var(--color-danger-500); background: #fffafa; }
.c-batch-input { font-family: 'SF Mono', Consolas, monospace; letter-spacing: 0.02em; }
.pr-row.has-error td { background: #fffafa; }
.pr-row-error td { padding: 5px 12px 8px; font-size: 12.5px; font-weight: 600; color: var(--color-danger-600); background: #fffafa; border-bottom: 1px solid var(--color-border-light); }
.pr-rows-empty { padding: 36px 16px; text-align: center; font-size: 13.5px; color: var(--color-text-placeholder); }
.pr-rows-end { padding: 12px; text-align: center; font-size: 12.5px; color: var(--color-text-placeholder); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
@media (max-width: 1100px) {
}
</style>

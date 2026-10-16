<template>
  <div class="pr-fin" data-test="qe-finished">
    <label class="pr-fin-field">
      <span class="pr-fin-label">批次号</span>
      <input
        v-model="batchNo"
        class="pr-fin-input"
        placeholder="如 0464628801（选填）"
        maxlength="100"
        autocomplete="off"
        data-test="qe-batch-no"
      />
    </label>
    <label class="pr-fin-check">
      <input v-model="isCustom" type="checkbox" data-test="qe-is-custom" />
      <span>定制</span>
    </label>
    <label v-if="isCustom" class="pr-fin-field">
      <span class="pr-fin-label">定制国家</span>
      <input
        v-model="customCountry"
        class="pr-fin-input"
        placeholder="如 美国"
        maxlength="100"
        autocomplete="off"
        data-test="qe-custom-country"
      />
    </label>
    <div v-if="error" class="pr-fin-error">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
/**
 * ProductionFinishedStockFields.vue — 包装部成品库存字段（批次号 / 定制）
 *
 * 从 ProductionEntryDialog 抽出：该文件已接近 400 行门禁上限，成品库存三字段
 * 内聚成独立组件（仅包装部显示，由父级 v-if 控制）。
 */
const batchNo = defineModel<string>('batchNo', { required: true })
const isCustom = defineModel<boolean>('isCustom', { required: true })
const customCountry = defineModel<string>('customCountry', { required: true })

defineProps<{ error?: string }>()
</script>

<style scoped>
.pr-fin {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  background: var(--color-slate-50);
}
.pr-fin-field { display: flex; align-items: center; gap: 8px; }
.pr-fin-label { font-size: 15px; font-weight: 600; color: var(--color-text-secondary); white-space: nowrap; }
/* 尺度对齐弹窗既有大控件（EntryDetailFields：17px/14px/14px/60px），
   否则相邻两块一大一小显得像嵌进来的小部件 */
.pr-fin-input {
  padding: 14px 18px;
  min-height: 60px;
  font-size: 17px;
  border: 2px solid var(--color-border);
  border-radius: 14px;
  background: #fff;
  font-family: inherit;
  color: var(--color-text);
  outline: none;
  width: 220px;
  box-sizing: border-box;
}
.pr-fin-input::placeholder { color: var(--color-text-placeholder); }
.pr-fin-input:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.15); }
.pr-fin-check { display: inline-flex; align-items: center; gap: 6px; font-size: 15px; font-weight: 600; color: var(--color-text-secondary); cursor: pointer; }
.pr-fin-error { flex-basis: 100%; color: var(--color-danger-500); font-size: 13px; }
</style>

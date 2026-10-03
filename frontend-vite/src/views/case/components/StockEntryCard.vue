<template>
  <div class="sec-card">
    <div class="sec-header">
      <div class="sec-title">
        <FontAwesomeIcon icon="cubes" :style="{ color: accent }" aria-hidden="true" />
        录入出入库
      </div>
      <span :class="['sec-badge', form.direction === 'in' ? 'sec-badge-in' : 'sec-badge-out']">
        暂存 {{ stagedCount }} 条
      </span>
    </div>

    <form class="sec-form" @submit.prevent>
      <div class="sec-field">
        <label class="sec-label">方向</label>
        <div class="sec-dir">
          <button type="button" :class="['sec-dir-btn', { active: form.direction === 'in' }]" @click="form.direction = 'in'">
            <FontAwesomeIcon icon="truck-loading" aria-hidden="true" />入库
          </button>
          <button type="button" :class="['sec-dir-btn', 'sec-dir-out', { active: form.direction === 'out' }]" @click="form.direction = 'out'">
            <FontAwesomeIcon icon="shipping-fast" aria-hidden="true" />出库
          </button>
        </div>
      </div>

      <div class="sec-field">
        <label class="sec-label">产品</label>
        <UiAutocomplete
          v-model="productQuery"
          :search-fn="searchProducts"
          placeholder="输入产品名称或69码搜索"
          suppress-after-select
          @select="(p: Product) => onSelectProduct(p)"
        >
          <template #option="{ item }">
            <span class="sec-option-name">{{ item.name }}</span>
            <span v-if="item.barcode" class="sec-option-barcode">{{ item.barcode }}</span>
          </template>
        </UiAutocomplete>
      </div>

      <div v-if="!selectedName && !loadingTree" class="sec-tip">
        输入关键词后，<b>在下方下拉里点选一个产品</b>，才会列出它的皮套与配件，逐行填数量。
      </div>

      <div v-if="loadingTree" class="sec-parts-loading"><UiLoadingIcon :loading="true" icon="spinner" /> 载入皮套…</div>

      <div v-else-if="parts.length" class="sec-parts">
        <div class="sec-parts-head">
          <span><b>{{ selectedName }}</b> · 皮套 {{ parts.length }} 项</span>
          <span class="sec-parts-hint">勾选要录的项并填数量</span>
        </div>
        <div
          v-for="row in parts"
          :key="row.caseId"
          :class="['sec-part-row', row.isPart ? 'sec-part-row-part' : 'sec-part-row-main', { 'sec-part-invalid': isInvalid(row) }]"
        >
          <input v-model="row.checked" type="checkbox" class="sec-part-check" :aria-label="`选择 ${row.name}`" />
          <span :class="row.isPart ? 'sec-tag-part' : 'sec-tag-main'">{{ row.isPart ? '配件' : '皮套' }}</span>
          <span class="sec-part-name">{{ row.name }}</span>
          <span class="sec-part-stock" :class="{ 'sec-part-stock-zero': row.stock <= 0 }">库存 {{ row.stock }}</span>
          <input v-model.number="row.qty" type="number" min="1" step="1" class="sec-part-qty" :aria-label="`${row.name} 数量`" @keydown.enter.prevent="emitAdd" />
        </div>
        <div v-if="outWarning" class="sec-warning" role="alert">
          <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />{{ outWarning }}
        </div>
      </div>

      <div v-else-if="selectedName" class="sec-parts-empty">该产品暂无皮套，提交时会自动建立皮套</div>

      <div class="sec-row">
        <div class="sec-field">
          <label class="sec-label">日期</label>
          <UiDatePicker v-model="form.date" style="width: 100%" />
        </div>
        <div class="sec-field">
          <label class="sec-label">备注（选填）</label>
          <input v-model="form.note" class="sec-text-input" placeholder="例如：批次 / 来源" aria-label="备注" />
        </div>
      </div>

      <button
        type="button"
        :class="['sec-add-btn', canAdd ? (form.direction === 'in' ? 'sec-add-in' : 'sec-add-out') : 'sec-add-disabled']"
        :disabled="!canAdd"
        @click="emitAdd"
      >
        <FontAwesomeIcon icon="plus-circle" style="margin-right: 4px" aria-hidden="true" />
        加入暂存单
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
/**
 * StockEntryCard — 出入库录入卡：选产品 → 展开其皮套（主件 + 配件）→ 勾选并填数量 → 批量加入暂存单。
 */
import { ref, computed } from 'vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import UiLoadingIcon from '@/components/ui/UiLoadingIcon.vue'
import { useCaseOptions } from '../composables/useCaseOptions'
import type { CaseStockFormState, StagedRowInput } from '../composables/useCaseStockWorkbench'
import type { Product } from '@/types'

interface EntryRow {
  caseId: string
  name: string
  isPart: boolean
  stock: number
  checked: boolean
  qty: number
}

defineProps<{
  stagedCount: number
}>()

const form = defineModel<CaseStockFormState>('form', { required: true })

const emit = defineEmits<{
  add: [rows: StagedRowInput[]]
}>()

const { searchProducts, fetchCaseTree } = useCaseOptions()

const productQuery = ref('')
const selectedName = ref('')
const parts = ref<EntryRow[]>([])
const loadingTree = ref(false)
// 请求序号：快速连选产品时丢弃过期响应，否则会把 A 的皮套行配到 B 的名下
// （用户按 B 的意图勾选，实际提交 A 的 caseId → 写错 SKU 的出入库）。
let treeSeq = 0

const accent = computed(() => (form.value.direction === 'in' ? 'var(--color-primary-500)' : 'var(--color-danger-500)'))

async function onSelectProduct(p: Product) {
  const seq = ++treeSeq
  selectedName.value = p.name
  productQuery.value = p.name
  parts.value = []
  loadingTree.value = true
  try {
    const tree = await fetchCaseTree(p.id)
    if (seq !== treeSeq) return  // 已被更新的选择作废
    if (!tree) return
    const rows: EntryRow[] = [
      { caseId: String(tree.main.id), name: tree.main.name || p.name, isPart: false, stock: tree.main.current_stock, checked: true, qty: 1 },
      ...tree.parts.map((pt) => ({ caseId: String(pt.id), name: pt.name, isPart: true, stock: pt.current_stock, checked: true, qty: 1 })),
    ]
    parts.value = rows
  } finally {
    if (seq === treeSeq) loadingTree.value = false
  }
}

function isInvalid(row: EntryRow): boolean {
  return form.value.direction === 'out' && row.checked && row.qty > row.stock
}

const outWarning = computed(() => {
  const bad = parts.value.filter((r) => isInvalid(r))
  if (!bad.length) return ''
  return `出库数量超过库存：${bad.map((r) => r.name).join('、')}（提交时后端会拒绝这些项）`
})

const checkedRows = computed(() => parts.value.filter((r) => r.checked && Number.isInteger(r.qty) && r.qty >= 1))

const canAdd = computed(() => !!form.value.date && checkedRows.value.length > 0)

function emitAdd() {
  if (!canAdd.value) return
  emit(
    'add',
    checkedRows.value.map((r) => ({ caseId: r.caseId, caseName: r.name, isPart: r.isPart, quantity: r.qty })),
  )
  // 加入后清空勾选与数量，便于继续录同一方向
  for (const r of parts.value) {
    r.checked = false
    r.qty = 1
  }
}
</script>

<style scoped>
.sec-card {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}
.sec-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.sec-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.sec-badge {
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}
.sec-badge-in { background: var(--color-primary-50); color: var(--color-primary-600); }
.sec-badge-out { background: var(--color-danger-50); color: var(--color-danger-600); }

.sec-form { padding: 16px; }
.sec-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.sec-field { margin-bottom: 12px; }
.sec-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.sec-text-input {
  width: 100%;
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  outline: none;
}
.sec-text-input:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.12); }

.sec-dir { display: inline-flex; gap: 8px; width: 100%; }
.sec-dir-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 38px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  background: white;
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}
.sec-dir-btn:hover { border-color: var(--color-primary-300); color: var(--color-primary-600); }
.sec-dir-btn.active { border-color: transparent; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: white; box-shadow: 0 4px 12px rgba(91, 141, 239, 0.3); }
.sec-dir-btn.sec-dir-out.active { background: linear-gradient(135deg, var(--color-danger-500), var(--color-danger-700)); box-shadow: 0 4px 12px rgba(234, 84, 85, 0.3); }

.sec-option-name { margin-right: 6px; }
.sec-option-barcode { color: var(--color-text-muted); font-size: 11px; }
.sec-tip {
  margin: -4px 0 12px;
  padding: 8px 12px;
  border-radius: 9px;
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  font-size: 12px;
  line-height: 1.5;
}

.sec-parts {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 12px;
}
.sec-parts-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--color-surface, #f8fafc);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  font-size: 12px;
  color: var(--color-text-secondary);
}
.sec-parts-hint { color: var(--color-text-muted); }
.sec-part-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border-light, #f8fafc);
}
.sec-part-row:last-child { border-bottom: none; }
.sec-part-row-main { background: var(--color-primary-50); }
.sec-part-row-main .sec-part-name { font-weight: 700; color: var(--color-primary-700); }
.sec-part-row-part { background: #fff; }
.sec-part-row.sec-part-invalid { background: var(--color-danger-50); }
.sec-part-check { width: 16px; height: 16px; flex-shrink: 0; cursor: pointer; }
.sec-part-name { flex: 1; min-width: 0; font-size: 13px; font-weight: 600; color: var(--color-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sec-tag-main { flex-shrink: 0; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: var(--color-primary-500); color: #fff; }
.sec-tag-part { flex-shrink: 0; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: var(--color-warning-500); color: #fff; }
.sec-part-stock { flex-shrink: 0; font-size: 12px; color: var(--color-text-muted); }
.sec-part-stock-zero { color: var(--color-danger-500); }
.sec-part-qty {
  width: 64px;
  flex-shrink: 0;
  height: 30px;
  text-align: center;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text);
  outline: none;
}
.sec-part-qty:focus { border-color: var(--color-primary-400); }
.sec-parts-loading { padding: 12px; color: var(--color-text-muted); font-size: 13px; display: flex; align-items: center; gap: 6px; }
.sec-parts-empty { padding: 10px 12px; margin-bottom: 12px; border-radius: 9px; background: var(--color-surface, #f8fafc); color: var(--color-text-muted); font-size: 12px; }

.sec-warning {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-top: 1px solid var(--color-danger-100);
  background: var(--color-danger-50);
  color: var(--color-danger-700);
  font-size: 12px;
  font-weight: 600;
}

.sec-add-btn {
  width: 100%;
  padding: 10px 14px;
  border: none;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  color: white;
  transition: box-shadow 0.3s ease, transform 0.3s ease, opacity 0.2s ease;
}
.sec-add-in { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); }
.sec-add-out { background: linear-gradient(135deg, var(--color-danger-500), var(--color-danger-700)); }
.sec-add-in:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(91, 141, 239, 0.3); }
.sec-add-out:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(234, 84, 85, 0.3); }
.sec-add-disabled { opacity: 0.45; cursor: not-allowed; }
</style>

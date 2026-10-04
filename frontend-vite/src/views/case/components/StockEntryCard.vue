<template>
  <div
    class="sec-card"
    @keydown.alt.1.prevent="form.direction = 'in'"
    @keydown.alt.2.prevent="form.direction = 'out'"
  >
    <div class="sec-header">
      <div class="sec-title">
        <FontAwesomeIcon icon="cubes" :style="{ color: accent }" aria-hidden="true" />
        录入出入库
      </div>
      <span :class="['sec-badge', form.direction === 'in' ? 'sec-badge-in' : 'sec-badge-out']">
        暂存 {{ stagedCount }} 条
      </span>
    </div>

    <!-- 快捷行：方向 · 产品 · 数量 · 录入（一次 Enter 落库） -->
    <div class="qe-row">
      <div class="qe-dir" role="group" aria-label="方向">
        <button
          type="button"
          :class="['qe-dir-btn', { active: form.direction === 'in' }]"
          title="Alt+1"
          @click="form.direction = 'in'"
        >
          <FontAwesomeIcon icon="truck-loading" aria-hidden="true" />入库
        </button>
        <button
          type="button"
          :class="['qe-dir-btn', 'qe-dir-out', { active: form.direction === 'out' }]"
          title="Alt+2"
          @click="form.direction = 'out'"
        >
          <FontAwesomeIcon icon="shipping-fast" aria-hidden="true" />出库
        </button>
      </div>

      <div class="qe-search">
        <UiAutocomplete
          ref="acRef"
          v-model="productQuery"
          :search-fn="searchProducts"
          placeholder="扫 / 搜产品名称或69码（↑↓ 选择，Enter 确认）"
          suppress-after-select
          @select="(p: Product) => onSelectProduct(p)"
        >
          <template #option="{ item }">
            <span class="sec-option-name">{{ item.name }}</span>
            <span v-if="item.barcode" class="sec-option-barcode">{{ item.barcode }}</span>
          </template>
        </UiAutocomplete>
      </div>

      <div class="qe-qty">
        <button type="button" class="qe-step" aria-label="减1" @click="adjustQty(-1)">−</button>
        <input
          ref="qtyRef"
          v-model.number="qty"
          type="number"
          min="1"
          step="1"
          inputmode="numeric"
          class="qe-qty-input"
          aria-label="数量"
          @keydown.up.prevent="adjustQty(1)"
          @keydown.down.prevent="adjustQty(-1)"
          @keydown.enter.prevent="onSubmit"
        />
        <button type="button" class="qe-step" aria-label="加1" @click="adjustQty(1)">＋</button>
      </div>

      <button
        type="button"
        class="qe-submit"
        :class="form.direction === 'in' ? 'qe-submit-in' : 'qe-submit-out'"
        :disabled="!canSubmit || submitting"
        :aria-label="`${form.direction === 'in' ? '入库' : '出库'} Enter`"
        @click="onSubmit"
      >
        <UiLoadingIcon :loading="!!submitting" icon="check" />
        <span>{{ form.direction === 'in' ? '入库' : '出库' }}</span>
        <span class="qe-kbd">⏎</span>
      </button>
      <button
        type="button"
        class="qe-stage"
        :disabled="!canSubmit || submitting"
        title="多条一起提交时用"
        @click="onStage"
      >
        <FontAwesomeIcon icon="plus-circle" aria-hidden="true" />暂存
      </button>
    </div>

    <!-- 慢路径收进「详细」：日期 / 备注 -->
    <div class="qe-hint">
      <span>日期 {{ form.date }}</span>
      <span class="qe-dot">·</span>
      <span>备注（{{ form.note || '空' }}）</span>
      <button
        type="button"
        class="qe-detail-toggle"
        :aria-expanded="detailOpen"
        @click="detailOpen = !detailOpen"
      >
        详细 <FontAwesomeIcon icon="chevron-down" :class="{ 'is-open': detailOpen }" aria-hidden="true" />
      </button>
    </div>
    <div v-if="detailOpen" class="qe-detail">
      <div class="sec-field">
        <label class="sec-label">日期</label>
        <UiDatePicker v-model="form.date" style="width: 100%" />
      </div>
      <div class="sec-field">
        <label class="sec-label">备注（选填）</label>
        <input v-model="form.note" class="sec-text-input" placeholder="例如：批次 / 来源" aria-label="备注" />
      </div>
    </div>

    <!-- 选中产品的皮套 + 配件（默认只录皮套） -->
    <div v-if="loadingTree" class="sec-parts-loading"><UiLoadingIcon :loading="true" icon="spinner" /> 载入皮套…</div>
    <div v-else-if="main" class="sec-parts">
      <div class="sec-parts-head">
        <span><b>{{ main.name }}</b> · 皮套库存 {{ main.stock }}</span>
        <span class="sec-parts-hint">默认只录皮套；要录配件请勾选</span>
      </div>
      <div class="sec-part-row sec-part-row-main">
        <input v-model="mainChecked" type="checkbox" class="sec-part-check" :aria-label="`选择 ${main.name}`" />
        <span class="sec-tag-main">皮套</span>
        <span class="sec-part-name">{{ main.name }}</span>
        <span class="sec-part-mirror">× {{ qty }}</span>
      </div>
      <div
        v-for="p in parts"
        :key="p.caseId"
        :class="['sec-part-row', 'sec-part-row-part', { 'sec-part-invalid': isInvalid(p) }]"
      >
        <input v-model="p.checked" type="checkbox" class="sec-part-check" :aria-label="`选择 ${p.name}`" />
        <span class="sec-tag-part">配件</span>
        <span class="sec-part-name">{{ p.name }}</span>
        <span class="sec-part-stock" :class="{ 'sec-part-stock-zero': p.stock <= 0 }">库存 {{ p.stock }}</span>
        <input v-model.number="p.qty" type="number" min="1" step="1" class="sec-part-qty" :aria-label="`${p.name} 数量`" />
      </div>
      <div v-if="outWarning" class="sec-warning" role="alert">
        <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />{{ outWarning }}
      </div>
    </div>
    <div v-else-if="treeError" class="sec-parts-empty">皮套加载失败，请重试（网络或权限异常）</div>
    <div v-else-if="selectedName" class="sec-parts-empty">该产品暂无皮套，提交时会自动建立皮套</div>
  </div>
</template>

<script setup lang="ts">
/**
 * StockEntryCard — 出入库快捷录入条。
 *
 * 一行完成：方向（Alt+1/2）· 产品（扫/搜，↑↓/Enter 选择）· 数量（−/＋、↑↓）· 录入（Enter 直接提交）。
 * 日期/备注收进「详细」折叠；选中产品后列出皮套（默认勾选、数量取快捷行）与配件（默认不勾）。
 * 需多条一起提交时用「暂存」，其余一律「录入」直提。范式对齐 production/ProductionEntryDialog.vue。
 */
import { ref, computed, nextTick } from 'vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiLoadingIcon from '@/components/ui/UiLoadingIcon.vue'
import { useCaseOptions } from '../composables/useCaseOptions'
import type { CaseStockFormState, StagedRowInput } from '../composables/useCaseStockWorkbench'
import type { Product } from '@/types'

interface PartRow {
  caseId: string
  name: string
  stock: number
  checked: boolean
  qty: number
}

defineProps<{
  stagedCount: number
  submitting?: boolean
}>()

const form = defineModel<CaseStockFormState>('form', { required: true })

const emit = defineEmits<{
  add: [rows: StagedRowInput[]]
  submit: [rows: StagedRowInput[]]
}>()

const { searchProducts, fetchCaseTree } = useCaseOptions()

const acRef = ref<{ focusInput?: () => void } | null>(null)
const qtyRef = ref<HTMLInputElement | null>(null)
const productQuery = ref('')
const selectedName = ref('')
const main = ref<{ caseId: string; name: string; stock: number } | null>(null)
const mainChecked = ref(true)
const parts = ref<PartRow[]>([])
const qty = ref(1)
const loadingTree = ref(false)
// 第十四轮：区分「加载失败」与「该产品确实没有皮套」—— fetchCaseTree 出错返回 null，
// 原先一律显示"暂无皮套，提交时会自动建立"，把网络/权限错误误导成正常空态。
const treeError = ref(false)
const detailOpen = ref(false)
// 请求序号：快速连选产品时丢弃过期响应，否则会把 A 的皮套行配到 B 的名下
// （用户按 B 的意图勾选，实际提交 A 的 caseId → 写错 SKU 的出入库）。
let treeSeq = 0

const accent = computed(() => (form.value.direction === 'in' ? 'var(--color-primary-500)' : 'var(--color-danger-500)'))

function adjustQty(delta: number) {
  qty.value = Math.max(1, (Number(qty.value) || 0) + delta)
}

async function onSelectProduct(p: Product) {
  const seq = ++treeSeq
  selectedName.value = p.name
  productQuery.value = p.name
  main.value = null
  parts.value = []
  loadingTree.value = true
  treeError.value = false
  try {
    const tree = await fetchCaseTree(p.id)
    if (seq !== treeSeq) return
    if (!tree) {
      treeError.value = true  // 加载失败（fetchCaseTree 出错返回 null）≠ 没有皮套
      return
    }
    main.value = { caseId: String(tree.main.id), name: tree.main.name || p.name, stock: tree.main.current_stock }
    mainChecked.value = true
    parts.value = tree.parts.map((pt) => ({
      caseId: String(pt.id),
      name: pt.name,
      stock: pt.current_stock,
      checked: false,
      qty: 1,
    }))
    await nextTick()
    qtyRef.value?.focus() // 选完产品直接落到数量框
  } finally {
    if (seq === treeSeq) loadingTree.value = false
  }
}

function isInvalid(p: PartRow): boolean {
  return form.value.direction === 'out' && p.checked && p.qty > p.stock
}

const outWarning = computed(() => {
  const bad = parts.value.filter(isInvalid)
  return bad.length ? `出库数量超过库存：${bad.map((r) => r.name).join('、')}（提交时后端会拒绝这些项）` : ''
})

/** 本次要提交的行：皮套（数量取快捷行）+ 已勾选的配件 */
const rows = computed<StagedRowInput[]>(() => {
  const out: StagedRowInput[] = []
  if (main.value && mainChecked.value && Number.isInteger(qty.value) && qty.value >= 1) {
    out.push({ caseId: main.value.caseId, caseName: main.value.name, isPart: false, quantity: qty.value })
  }
  for (const p of parts.value) {
    if (p.checked && Number.isInteger(p.qty) && p.qty >= 1) {
      out.push({ caseId: p.caseId, caseName: p.name, isPart: true, quantity: p.qty })
    }
  }
  return out
})

const canSubmit = computed(() => !!form.value.date && rows.value.length > 0)

/** 录入后清空并回到搜索框，便于连续录入下一条 */
function resetForNext() {
  qty.value = 1
  for (const p of parts.value) {
    p.checked = false
    p.qty = 1
  }
  productQuery.value = ''
  selectedName.value = ''
  main.value = null
  parts.value = []
  void nextTick(() => acRef.value?.focusInput?.())
}

function onSubmit() {
  if (!canSubmit.value) return
  emit('submit', rows.value)
  resetForNext()
}

/** 暂存：留在当前产品，便于继续加同产品的其它项 */
function onStage() {
  if (!canSubmit.value) return
  emit('add', rows.value)
  qty.value = 1
  for (const p of parts.value) {
    p.checked = false
    p.qty = 1
  }
}
</script>

<style scoped>
.sec-card { border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 13px; overflow: hidden; background: var(--color-surface-card, white); }
.sec-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid var(--color-border-light, #f1f5f9); }
.sec-title { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; color: var(--color-text); }
.sec-badge { padding: 4px 10px; border-radius: 16px; font-size: 12px; font-weight: 600; }
.sec-badge-in { background: var(--color-primary-50); color: var(--color-primary-600); }
.sec-badge-out { background: var(--color-danger-50); color: var(--color-danger-600); }

/* 快捷行：方向 · 产品 · 数量 · 录入 · 暂存 */
.qe-row { display: flex; align-items: center; gap: 8px; padding: 14px 16px 0; flex-wrap: wrap; }
.qe-dir { display: inline-flex; gap: 4px; flex-shrink: 0; }
.qe-dir-btn { display: inline-flex; align-items: center; gap: 5px; height: 38px; padding: 0 12px; border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 10px; background: white; color: var(--color-text-secondary); font-size: 13px; font-weight: 600; cursor: pointer; }
.qe-dir-btn:hover { border-color: var(--color-primary-300); color: var(--color-primary-600); }
.qe-dir-btn.active { border-color: transparent; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: #fff; }
.qe-dir-btn.sec-dir-out.active,
.qe-dir-btn.qe-dir-out.active { background: linear-gradient(135deg, var(--color-danger-500), var(--color-danger-700)); }

.qe-search { flex: 1 1 260px; min-width: 200px; }
.qe-qty { display: inline-flex; align-items: center; gap: 2px; flex-shrink: 0; }
.qe-step { width: 32px; height: 38px; border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 10px; background: white; color: var(--color-text-secondary); font-size: 16px; cursor: pointer; }
.qe-step:hover { border-color: var(--color-primary-300); color: var(--color-primary-600); }
.qe-qty-input { width: 68px; height: 38px; text-align: center; border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 10px; font-size: 14px; font-weight: 600; color: var(--color-text); outline: none; font-variant-numeric: tabular-nums; }
.qe-qty-input:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.12); }

.qe-submit { display: inline-flex; align-items: center; gap: 6px; height: 38px; padding: 0 16px; flex-shrink: 0; border: none; border-radius: 10px; color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; }
.qe-submit-in { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); }
.qe-submit-out { background: linear-gradient(135deg, var(--color-danger-500), var(--color-danger-700)); }
.qe-submit:disabled { opacity: 0.45; cursor: not-allowed; }
.qe-kbd { font-size: 11px; opacity: 0.85; }
.qe-stage { display: inline-flex; align-items: center; gap: 5px; height: 38px; padding: 0 12px; flex-shrink: 0; border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 10px; background: white; color: var(--color-text-secondary); font-size: 13px; font-weight: 600; cursor: pointer; }
.qe-stage:hover:not(:disabled) { border-color: var(--color-primary-300); color: var(--color-primary-600); }
.qe-stage:disabled { opacity: 0.45; cursor: not-allowed; }

/* 慢路径提示行 */
.qe-hint { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 16px 12px; font-size: 12px; color: var(--color-text-muted); }
.qe-dot { opacity: 0.5; }
.qe-detail-toggle { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; border: none; background: transparent; color: var(--color-primary-600); font-size: 12px; font-weight: 600; cursor: pointer; }
.qe-detail-toggle svg { transition: transform 0.2s; }
.qe-detail-toggle svg.is-open { transform: rotate(180deg); }
.qe-detail { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 0 16px 14px; }
@media (max-width: 640px) { .qe-detail { grid-template-columns: 1fr; } }

.sec-field { min-width: 0; }
.sec-label { display: block; font-size: 12px; font-weight: 600; letter-spacing: 0.05em; color: var(--color-text-secondary); margin-bottom: 6px; }
.sec-text-input {
  width: 100%; height: 40px; padding: 0 12px; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px; font-size: 14px; color: var(--color-text); font-family: inherit; background: white; outline: none;
}
.sec-text-input:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.12); }

.sec-option-name { margin-right: 6px; }
.sec-option-barcode { color: var(--color-text-muted); font-size: 11px; }

.sec-parts { border-top: 1px solid var(--color-border-light, #f1f5f9); }
.sec-parts-head {
  display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 8px 16px; background: var(--color-surface, #f8fafc); font-size: 12px; color: var(--color-text-secondary);
}
.sec-parts-hint { color: var(--color-text-muted); }
.sec-part-row { display: flex; align-items: center; gap: 8px; padding: 10px 16px; border-bottom: 1px solid var(--color-border-light, #f8fafc); }
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
.sec-part-mirror { flex-shrink: 0; font-size: 13px; font-weight: 700; color: var(--color-primary-700); font-variant-numeric: tabular-nums; }
.sec-part-qty {
  width: 64px; flex-shrink: 0; height: 30px; text-align: center;
  border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 8px; font-size: 13px; color: var(--color-text); outline: none;
}
.sec-part-qty:focus { border-color: var(--color-primary-400); }
.sec-parts-loading { padding: 12px 16px; color: var(--color-text-muted); font-size: 13px; display: flex; align-items: center; gap: 6px; }
.sec-parts-empty { padding: 10px 16px; color: var(--color-text-muted); font-size: 12px; border-top: 1px solid var(--color-border-light, #f1f5f9); }
.sec-warning {
  display: flex; align-items: center; gap: 6px; padding: 8px 16px;
  background: var(--color-danger-50); color: var(--color-danger-700); font-size: 12px; font-weight: 600;
}
</style>

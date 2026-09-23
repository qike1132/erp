<template>
  <UiDialog
    :open="open"
    max-width-class="max-w-[1600px]"
    :close-on-overlay-click="false"
    @update:open="onOpenUpdate"
  >
    <template #title>
      批量发货
      <span class="osw-title-sub">从左侧选择订单，右侧核对发货明细</span>
    </template>

    <div class="osw-body">
      <!-- ===== 加载中 ===== -->
      <div v-if="loading" class="osw-empty osw-empty--fill"><UiSpinner /></div>

      <!-- ===== 结果态（成功/失败，子组件） ===== -->
      <OutsourceShipResultView v-else-if="result" :result="result" />

      <!-- ===== 双栏工作区：左选订单 / 右编清单 ===== -->
      <template v-else>
        <!-- 移动端 Tab -->
        <div class="osw-tabs">
          <button
            type="button"
            :class="['osw-tab', { 'is-on': mobileTab === 'pick' }]"
            @click="mobileTab = 'pick'"
          >待选产品<span class="osw-tab-cnt">{{ filteredPickGroups.length }}</span></button>
          <button
            type="button"
            :class="['osw-tab', { 'is-on': mobileTab === 'cart' }]"
            @click="mobileTab = 'cart'"
          >已选清单<span class="osw-tab-cnt">{{ cartGroups.length }}</span></button>
        </div>

        <div class="osw-panes" :data-tab="mobileTab">
          <!-- 左栏：待发货产品（挑选，子组件） -->
          <OutsourceShipPickPanel
            v-model:keyword="keyword"
            :groups="pickGroups"
            :selected-names="cartProducts"
            @toggle="togglePick"
            @select-all="selectAllFiltered"
          />
          <!-- 右栏：发货清单（核对编辑，子组件） -->
          <OutsourceShipCartPanel
            :groups="cartGroups"
            @remove="removeProductFromCart"
            @clear="clearCart"
          />
        </div>
      </template>

      <!-- ===== 提交中遮罩（进度反馈 + 防误操作） ===== -->
      <div v-if="submitting" class="osw-submitting" role="status" aria-live="polite">
        <UiSpinner />
        <span>正在生成发货单…（{{ shipSum.toLocaleString() }} 件）</span>
      </div>
    </div>

    <template #footer>
      <!-- 结果态 -->
      <template v-if="result">
        <UiButton v-if="!result.ok" variant="outline" @click="onClose">关闭</UiButton>
        <UiButton v-if="result.ok" variant="primary" @click="finish">完成并关闭</UiButton>
        <UiButton v-else variant="primary" @click="backToEdit">返回修改</UiButton>
      </template>

      <!-- 确认态：底栏原地切换，不跳页 -->
      <div v-else-if="confirmOpen" class="osw-bar osw-bar--confirm">
        <FontAwesomeIcon class="osw-bar-warn" icon="triangle-exclamation" aria-hidden="true" />
        <div class="osw-bar-info">
          将生成 <b>1</b> 张发货单、共 <b>{{ checkedCount }}</b> 道工序 /
          <b>{{ shipSum.toLocaleString() }}</b> 件，并通知贝乐收货账号
        </div>
        <UiButton variant="outline" :disabled="submitting" @click="confirmOpen = false">返回调整</UiButton>
        <UiButton variant="primary" :disabled="submitting" @click="submit">确认发货</UiButton>
      </div>

      <!-- 汇总态：实时合计 + 主操作 -->
      <div v-else class="osw-bar">
        <div class="osw-bar-info" role="status">
          <span>涉及 <b :class="{ 'is-zero': !selectedOrderCount }">{{ selectedOrderCount }}</b> 单</span>
          <span class="osw-sep">·</span>
          <span><b :class="{ 'is-zero': !checkedCount }">{{ checkedCount }}</b> 道工序</span>
          <span class="osw-sep">·</span>
          <span>共 <b :class="{ 'is-zero': !shipSum }">{{ shipSum.toLocaleString() }}</b> 件</span>
          <span v-if="invalidCount" class="osw-bar-err">
            <FontAwesomeIcon icon="triangle-exclamation" aria-hidden="true" />
            {{ invalidCount }} 行数量有误<template v-if="firstInvalidHint">：{{ firstInvalidHint }}</template>
          </span>
        </div>
        <UiButton
          variant="primary"
          :disabled="submitting || checkedCount === 0 || invalidCount > 0"
          @click="confirmOpen = true"
        >
          生成发货单{{ checkedCount > 0 ? `（${shipSum.toLocaleString()} 件）` : '' }}
        </UiButton>
      </div>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * OutsourceShipDialog.vue — 批量发货弹窗（壳 + 状态 + 汇总 + 提交）
 *
 * 交互模型与领域规则见同目录：左栏挑选 = OutsourceShipPickPanel，
 * 右栏清单编辑 = OutsourceShipCartPanel，聚合/拆分/校验 = shipCartModel.ts。
 * 本组件持有全部状态（rows/cartProducts/mergedInputs），经 props 下发、事件回收；
 * 底栏实时合计与提交（按订单分组 payload）在此编排。
 * 数据源 GET /outsource/processes/shippable；提交 POST /outsource/processes/ship-multi（每订单一张发货单，单事务原子）。
 */
import { computed, ref, watch } from 'vue'
import { outsourceApi, type ShippableProcessItem } from '@/api/outsource'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import { toast } from '@/composables/useToast'
import OutsourceShipPickPanel from './OutsourceShipPickPanel.vue'
import OutsourceShipCartPanel from './OutsourceShipCartPanel.vue'
import OutsourceShipResultView from './OutsourceShipResultView.vue'
import { useShipTotals } from './useShipTotals'
import {
  buildOrderOptions, buildPickGroups, buildCartGroups,
  mergeKey, productRows, splitQty, isRowInvalid,
  type PickGroup, type OrderOption, type MergedInput, type ShipResult,
} from './shipCartModel'

const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ (e: 'shipped'): void }>()

const rows = ref<ShippableProcessItem[]>([])
const orders = ref<OrderOption[]>([])
/** 左栏挑选项（按产品名聚合） */
const pickGroups = ref<PickGroup[]>([])
/** 清单中的产品名（保持加入顺序） */
const cartProducts = ref<string[]>([])
/** 合并工序的填写状态，键=产品名||工序名（跨重算保持稳定，避免输入被重置） */
const mergedInputs = ref(new Map<string, MergedInput>())
const loading = ref(false)
const submitting = ref(false)
const keyword = ref('')
const mobileTab = ref<'pick' | 'cart'>('pick')
const confirmOpen = ref(false)
const result = ref<ShipResult | null>(null)

watch(open, (v) => { if (v) load() })

async function load() {
  loading.value = true
  result.value = null
  confirmOpen.value = false
  keyword.value = ''
  mobileTab.value = 'pick'
  cartProducts.value = []
  mergedInputs.value = new Map()
  rows.value = []
  orders.value = []
  pickGroups.value = []
  try {
    const list = await outsourceApi.shippable()
    rows.value = list
    orders.value = buildOrderOptions(list)
    pickGroups.value = buildPickGroups(list)
  } catch {
    toast.error('加载待发货工序失败')
  } finally {
    loading.value = false
  }
}

// ===== 左栏：筛选与挑选 =====
const filteredPickGroups = computed(() => {
  const kw = keyword.value.trim()
  return pickGroups.value.filter((g) => !kw || g.productName.includes(kw))
})

/** 挑选项是否已在清单中 */
function isPickOn(g: PickGroup): boolean {
  return cartProducts.value.includes(g.productName)
}

/** 把某产品加入清单；各工序数量默认=跨订单剩余合计（后续可逐工序自定义） */
function addProduct(productName: string) {
  // 已在清单中则原样保留用户已填数量（全选时重复调用不应累加）
  if (cartProducts.value.includes(productName)) return
  cartProducts.value.push(productName)
  // 同一工序跨订单累加剩余量，作为该合并行的默认数量与上限
  const totals = new Map<string, number>()
  for (const r of productRows(rows.value, productName)) {
    totals.set(r.process_type, (totals.get(r.process_type) ?? 0) + r.remaining)
  }
  const map = mergedInputs.value
  for (const [processType, qty] of totals) {
    const key = mergeKey(productName, processType)
    if (!map.has(key)) map.set(key, { qty, on: true })
  }
}

/** 把某产品移出清单 */
function removeProduct(productName: string) {
  cartProducts.value = cartProducts.value.filter((n) => n !== productName)
  const map = mergedInputs.value
  for (const key of [...map.keys()]) {
    if (key.startsWith(`${productName}||`)) map.delete(key)
  }
}

/** 点卡片 / 复选框：加入或移出该产品 */
function togglePick(g: PickGroup) {
  confirmOpen.value = false
  if (isPickOn(g)) removeProduct(g.productName)
  else addProduct(g.productName)
}

/** 全选：把当前筛选结果加入清单（已在清单中的不重复添加） */
function selectAllFiltered() {
  confirmOpen.value = false
  filteredPickGroups.value.forEach((g) => addProduct(g.productName))
}

function clearCart() {
  confirmOpen.value = false
  cartProducts.value = []
  mergedInputs.value = new Map()
}

/** 卡头 ✕（右栏子组件上抛产品名）：移出该产品的全部工序 */
function removeProductFromCart(productName: string) {
  confirmOpen.value = false
  removeProduct(productName)
}

// ===== 汇总（底栏 / 确认态 / 提交共用，口径见 useShipTotals） =====
const cartGroups = computed(() => buildCartGroups(rows.value, cartProducts.value, mergedInputs.value))

const { checkedRows, checkedCount, shipSum, selectedOrderCount, invalidCount, firstInvalidHint } = useShipTotals(cartGroups)

// ===== 提交与结果 =====
function submit() {
  for (const r of checkedRows.value) {
    if (!isRowInvalid(r)) continue
    const n = Number(r.input.qty)
    if (!Number.isFinite(n) || n < 1) {
      toast.warning(`「${r.processType}」发货数量必须为大于 0 的整数`)
    } else if (!Number.isInteger(n)) {
      toast.warning(`「${r.processType}」发货数量必须为整数`)
    } else {
      toast.warning(`「${r.processType}」发货数量超过剩余未发合计（${r.remaining.toLocaleString()}）`)
    }
    confirmOpen.value = false
    return
  }
  // 合并发货：把选中的所有工序数量平铺为单个明细数组，一次生成一张发货单
  const flatItems: { process_id: number; quantity: number }[] = []
  for (const r of checkedRows.value) {
    for (const { row, quantity } of splitQty(r)) {
      flatItems.push({ process_id: row.process_id, quantity })
    }
  }
  submitting.value = true
  confirmOpen.value = false
  outsourceApi.createMergedShipment(flatItems)
    .then((res) => {
      result.value = { ok: true, shipments: [res] }
      toast.success('已生成 1 张发货单')
      emit('shipped')
    })
    .catch((e) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      result.value = { ok: false, error: msg || '合并发货失败（整批已回滚）' }
    })
    .finally(() => { submitting.value = false })
}

function backToEdit() {
  result.value = null
  confirmOpen.value = false
}

function finish() {
  open.value = false
}

function onClose() {
  if (submitting.value) return
  open.value = false
}

/** 提交中拦截所有关闭来源（遮罩点击 / 右上角 X 的 update:open） */
function onOpenUpdate(v: boolean) {
  if (submitting.value) return
  open.value = v
}
</script>

<style scoped>
.osw-body {
  display: flex; flex-direction: column; gap: 0; min-height: 0;
  height: min(880px, 90vh); position: relative;
}
.osw-empty--fill { flex: 1; justify-content: center; }

.osw-title-sub { font-size: 12px; font-weight: 400; color: var(--color-text-muted, #94a3b8); }

/* ===== 移动端 Tab（桌面隐藏） ===== */
.osw-tabs { display: none; }

/* ===== 双栏工作区 ===== */
.osw-panes {
  flex: 1; min-height: 0; display: flex;
  border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 12px; overflow: hidden;
}

/* ===== 底栏（汇总态 / 确认态原地切换） ===== */
.osw-bar { flex: 1; display: flex; align-items: center; gap: 12px; min-width: 0; flex-wrap: wrap; }
.osw-bar-info {
  flex: 1; min-width: 0; display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-size: 12.5px; color: var(--color-text-secondary, #475569);
}
.osw-bar-info b {
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 14px; font-weight: 800;
  color: var(--color-primary-600, #2563eb); font-variant-numeric: tabular-nums;
}
.osw-bar-info b.is-zero { color: var(--color-text-muted, #94a3b8); }
.osw-sep { color: #cbd5e1; }
.osw-bar-err {
  display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 700;
  color: var(--color-danger-600, #dc2626); background: var(--color-danger-50, #fef2f2);
  border: 1px solid #fecaca; border-radius: 7px; padding: 2px 9px;
}
.osw-bar--confirm { animation: osw-bar-in 0.22s ease; }
.osw-bar--confirm .osw-bar-info b { color: var(--color-warning-600, #d97706); }
.osw-bar-warn { color: var(--color-warning-600, #d97706); font-size: 15px; flex-shrink: 0; }
@keyframes osw-bar-in {
  from { opacity: 0.3; transform: translateY(3px); }
  to { opacity: 1; transform: none; }
}

/* ===== 提交中遮罩 ===== */
.osw-submitting {
  position: absolute; inset: 0; z-index: 5; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px;
  background: rgba(255, 255, 255, 0.82); backdrop-filter: blur(2px); border-radius: 12px;
  font-size: 13.5px; font-weight: 700; color: var(--color-primary-600, #2563eb);
}

/* ===== 结果态样式已随 OutsourceShipResultView 子组件迁移 ===== */

.osw-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 40px 20px; color: var(--color-text-muted, #64748b); }
.osw-empty span { font-size: 14px; }

/* ===== 响应式：移动端双 Tab ===== */
@media (max-width: 768px) {
  .osw-tabs {
    display: flex; gap: 4px; padding: 3px; margin-bottom: 10px; flex-shrink: 0;
    background: var(--color-surface, #f8fafc); border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 11px;
  }
  .osw-tab {
    flex: 1; text-align: center; font: inherit; font-size: 12.5px; font-weight: 700;
    color: var(--color-text-muted, #64748b); background: transparent; border: none;
    padding: 7px 0; border-radius: 8px; cursor: pointer;
  }
  .osw-tab.is-on { background: #fff; color: var(--color-primary-600, #2563eb); box-shadow: 0 1px 4px rgba(15, 23, 42, 0.1); }
  .osw-tab-cnt { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 11px; margin-left: 3px; }

  /* 显隐切换命中子组件根元素（根元素带父作用域属性）；左右栏内部规则已随子组件迁移 */
  .osw-panes[data-tab='pick'] .osw-right { display: none; }
  .osw-panes[data-tab='cart'] .osw-left { display: none; }

  .osw-bar { flex-direction: column; align-items: stretch; }
  .osw-bar-info { justify-content: center; }
  .osw-bar :deep(button) { flex: 1; justify-content: center; }
}
</style>

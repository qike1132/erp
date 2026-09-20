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

      <!-- ===== 结果态（成功/失败） ===== -->
      <div v-else-if="result" class="osw-result-wrap">
        <div v-if="result.ok" class="osw-result osw-result--ok">
          <div class="osw-result-head">
            <FontAwesomeIcon icon="circle-check" aria-hidden="true" />
            <strong>发货完成：已生成 {{ result.shipments.length }} 张发货单</strong>
          </div>
          <div v-for="s in result.shipments" :key="s.id" class="osw-result-row">
            <span class="osw-mono">{{ s.shipment_no }}</span>
            <span>{{ s.customer || '-' }}</span>
            <span class="osw-mono">{{ s.item_count }} 道工序 · {{ s.total_shipped.toLocaleString() }} 件</span>
            <span class="osw-badge">待贝乐收货</span>
          </div>
        </div>

        <div v-else class="osw-result osw-result--fail">
          <div class="osw-result-head">
            <FontAwesomeIcon icon="triangle-exclamation" aria-hidden="true" />
            <strong>发货失败（整批已回滚，数据未变更）</strong>
          </div>
          <div class="osw-result-detail">{{ result.error }}</div>
        </div>
      </div>

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
          <!-- 左栏：待发货产品（按产品名聚合，只管挑选） -->
          <aside class="osw-left">
            <div class="osw-l-toolbar">
              <label class="osw-search">
                <FontAwesomeIcon icon="search" aria-hidden="true" />
                <input
                  v-model="keyword"
                  type="text"
                  placeholder="搜索产品名称"
                  aria-label="搜索产品名称"
                >
              </label>
            </div>
            <div class="osw-l-meta">
              <span>待发货产品 <b>{{ filteredPickGroups.length }}</b> 项</span>
              <button type="button" class="osw-link" @click="selectAllFiltered">全选</button>
            </div>
            <!-- 列表（表头 sticky 在滚动容器内，保证与卡片同宽、右列精确对齐） -->
            <div class="osw-l-list">
              <div class="osw-l-head" aria-hidden="true">
                <span class="osw-l-head-cbx" />
                <span class="osw-l-head-prod">产品名称</span>
                <span />
              </div>
              <div v-if="!filteredPickGroups.length" class="osw-l-empty">没有匹配的产品</div>
              <div
                v-for="g in filteredPickGroups"
                :key="g.key"
                :class="['osw-card', { 'is-on': isPickOn(g) }]"
                @click="togglePick(g)"
              >
                <input
                  type="checkbox"
                  class="osw-cbx"
                  :checked="isPickOn(g)"
                  :aria-label="`勾选 ${g.productName}`"
                  @click.stop="togglePick(g)"
                >
                <!-- 单行：产品名称 + 跨订单角标 -->
                <span class="osw-prod-name" :title="g.productName">{{ g.productName }}</span>
                <span v-if="g.orderCount > 1" class="osw-prod-orders" :title="`该产品分布在 ${g.orderCount} 张订单`">{{ g.orderCount }}单</span>
              </div>
            </div>
          </aside>

          <!-- 右栏：发货清单（只管核对编辑） -->
          <section class="osw-right">
            <div class="osw-r-head">
              <span class="osw-r-title">发货清单</span>
              <span :class="['osw-chip', { 'is-mute': !cartGroups.length }]">{{ cartGroups.length }} 项</span>
              <button
                type="button"
                class="osw-link osw-link--sm"
                :disabled="!cartGroups.length"
                @click="clearCart"
              >清空</button>
            </div>

            <div class="osw-r-list">
              <div v-if="!cartGroups.length" class="osw-cart-empty">
                <div class="osw-cart-empty-ico"><FontAwesomeIcon icon="box-open" aria-hidden="true" /></div>
                <div class="osw-cart-empty-t">发货清单还是空的</div>
                <div class="osw-cart-empty-s">从左侧勾选要发货的产品，在这里核对数量<br>同一工序跨订单合并为一行，数量默认等于剩余合计</div>
              </div>

              <div v-for="p in cartGroups" :key="p.key" class="osw-cart-card">
                <div class="osw-cart-head">
                  <span class="osw-cart-title">{{ p.productName }}</span>
                  <span v-if="productOrderCount(p) > 1" class="osw-cart-orders">{{ productOrderCount(p) }} 单合并</span>
                  <span class="osw-cart-sum"><b>{{ productCheckedSum(p).toLocaleString() }}</b> 件</span>
                  <button
                    type="button"
                    class="osw-rm"
                    :aria-label="`移出 ${p.productName} 的全部发货项`"
                    @click="removeProductFromCart(p)"
                  ><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
                </div>
                <!-- 同一 SKU 的全部工序横向排列在同一行内；每格独立填写数量 -->
                <div class="osw-proc-grid">
                  <div
                    v-for="r in p.processes"
                    :key="r.key"
                    :class="['osw-cell', { 'is-off': !r.input.on }]"
                  >
                    <div class="osw-cell-top">
                      <input
                        v-model="r.input.on"
                        type="checkbox"
                        class="osw-cbx"
                        :aria-label="`发货 ${p.productName} ${r.processType}`"
                      >
                      <span class="osw-proc" :title="r.processType">{{ r.processType }}</span>
                    </div>
                    <div class="osw-cell-stats">
                      <span class="osw-total" :title="`订单总量 ${r.targetQty.toLocaleString()}`">
                        <i>总量</i><b>{{ r.targetQty.toLocaleString() }}</b>
                      </span>
                      <span
                        :class="['osw-remain', { 'is-zero': liveRemaining(r) === 0 }]"
                        :title="`剩余合计 ${r.remaining.toLocaleString()} − 本次发货，发完后剩余`"
                      ><i>剩</i><b>{{ liveRemaining(r).toLocaleString() }}</b></span>
                    </div>
                    <input
                      v-model.number="r.input.qty"
                      type="number"
                      :class="['osw-qty', { 'is-invalid': isRowInvalid(r) }]"
                      min="1"
                      step="1"
                      :max="r.remaining"
                      :disabled="!r.input.on"
                      :aria-label="`${p.productName} ${r.processType} 本次发货数量，上限 ${r.remaining}`"
                      :title="isRowInvalid(r) ? `不能超过剩余未发 ${r.remaining.toLocaleString()}` : `上限 ${r.remaining.toLocaleString()}`"
                      @input="onQtyInput(r, $event)"
                    >
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
      </template>

      <!-- ===== 提交中遮罩（进度反馈 + 防误操作） ===== -->
      <div v-if="submitting" class="osw-submitting" role="status" aria-live="polite">
        <UiSpinner />
        <span>正在生成发货单…（{{ selectedOrderCount }} 单 / {{ shipSum.toLocaleString() }} 件）</span>
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
          将按订单生成 <b>{{ selectedOrderCount }}</b> 张发货单、共 <b>{{ checkedCount }}</b> 道工序 /
          <b>{{ shipSum.toLocaleString() }}</b> 件，并通知贝乐收货账号
        </div>
        <UiButton variant="outline" :disabled="submitting" @click="confirmOpen = false">返回调整</UiButton>
        <UiButton variant="primary" :disabled="submitting" @click="submit">确认发货</UiButton>
      </div>

      <!-- 汇总态：实时合计 + 主操作 -->
      <div v-else class="osw-bar">
        <div class="osw-bar-info" role="status">
          <span>已选 <b :class="{ 'is-zero': !selectedOrderCount }">{{ selectedOrderCount }}</b> 单</span>
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
          生成发货单{{ selectedOrderCount > 0 ? `（${selectedOrderCount} 单 / ${shipSum.toLocaleString()} 件）` : '' }}
        </UiButton>
      </div>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * OutsourceShipDialog.vue — 批量发货（双栏「选购清单」）
 *
 * 交互模型（一栏一件事，行为单一可预期）：
 * - 左栏「待发货订单」只管浏览挑选：点卡片任意处 = 勾选/取消，选中自动移到右栏清单；
 * - 右栏「发货清单」只管核对编辑：数量默认=剩余未发，可整行取消勾选（不发该工序）、✕ 移出整单；
 * - 底栏实时合计；「生成发货单」→ 底栏原地切换确认态（防误触不跳页）；
 * - 结果态：成功=发货单清单；失败=错误明细 + 返回修改（已填数据保留）。
 * 数据源 GET /outsource/processes/shippable；提交 POST /outsource/processes/ship-multi（每订单一张发货单，单事务原子）。
 */
import { computed, ref, watch } from 'vue'
import { outsourceApi, type Shipment, type ShippableProcessItem } from '@/api/outsource'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import { toast } from '@/composables/useToast'

/** 左栏挑选项：按产品名聚合（跨订单、跨客户合并，PO 号不作为展示信息） */
interface PickGroup {
  key: string
  productName: string
  /** 该产品覆盖的订单（勾选时整组加入清单） */
  orderIds: number[]
  /** 覆盖的订单数，用于提示该产品跨多张订单 */
  orderCount: number
}

interface OrderOption {
  order_id: number
  order_no: string
  customer: string
}

/** 合并工序的填写状态：同一 SKU 的同一工序跨订单共享一个数量框 */
interface MergedInput {
  /** 跨订单合计发货数量（提交时按订单顺序拆分到各订单） */
  qty: number
  /** 是否参与本次发货（取消勾选=不发该工序） */
  on: boolean
}

/** 合并后的工序行：同一 SKU 的同一工序跨订单合并为一行 */
interface CartProcessRow {
  /** 合并键：产品名 + 工序名 */
  key: string
  processType: string
  /** 该工序在各订单下的原始行（提交时按订单顺序拆分数量） */
  entries: ShippableProcessItem[]
  /** 跨订单订单总量合计（订单要求的全部数量） */
  targetQty: number
  /** 跨订单剩余未发合计，即该行数量上限 */
  remaining: number
  /** 填写状态（跨重算保持同一响应式对象） */
  input: MergedInput
}

/** 清单中的产品：同一产品名跨订单（含跨客户）合并为一张卡 */
interface CartProduct {
  /** 产品名（合并键） */
  key: string
  productName: string
  /** 该产品覆盖的订单 */
  orderIds: number[]
  /** 按工序合并后的行 */
  processes: CartProcessRow[]
}

const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ (e: 'shipped'): void }>()

/** 提交结果（判别联合：ok=true 必有 shipments，ok=false 必有 error，模板内可窄化） */
type ShipResult = { ok: true; shipments: Shipment[] } | { ok: false; error: string }

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

    // 订单基础信息（提交按订单生成发货单）
    const orderMap = new Map<number, OrderOption>()
    for (const r of list) {
      if (!orderMap.has(r.order_id)) {
        orderMap.set(r.order_id, { order_id: r.order_id, order_no: r.order_no, customer: r.customer })
      }
    }
    orders.value = [...orderMap.values()]

    // 左栏挑选项：两级聚合
    // 1) 订单+产品：同一 SKU 的多道工序会返回多行，先按「订单+产品」去重，保证订单 ID 不重复；
    // 2) 产品名：跨订单、跨客户合并（实测 16 组产品分布在 2-8 张订单），合并为一个挑选项。
    const perOrderProduct = new Map<string, { productName: string; orderId: number }>()
    for (const r of list) {
      const name = r.product_name || '未命名产品'
      const opKey = `${r.order_id}||${name}`
      if (!perOrderProduct.has(opKey)) {
        perOrderProduct.set(opKey, { productName: name, orderId: r.order_id })
      }
    }
    const pickMap = new Map<string, PickGroup>()
    for (const item of perOrderProduct.values()) {
      const key = item.productName
      const g = pickMap.get(key)
      if (g) {
        g.orderIds.push(item.orderId)
      } else {
        pickMap.set(key, {
          key, productName: item.productName,
          orderIds: [item.orderId], orderCount: 1,
        })
      }
    }
    pickGroups.value = [...pickMap.values()]
      .map((g) => ({ ...g, orderCount: g.orderIds.length }))
      .sort((a, b) => a.productName.localeCompare(b.productName))
  } catch {
    toast.error('加载待发货工序失败')
  } finally {
    loading.value = false
  }
}

// ===== 左栏：筛选与挑选（按产品名聚合） =====
const filteredPickGroups = computed(() => {
  const kw = keyword.value.trim()
  return pickGroups.value.filter((g) => !kw || g.productName.includes(kw))
})

/** 挑选项是否已在清单中 */
function isPickOn(g: PickGroup): boolean {
  return cartProducts.value.includes(g.productName)
}

/** 合并键：产品名 + 工序名 */
function mergeKey(productName: string, processType: string): string {
  return `${productName}||${processType}`
}

/** 该产品在各订单下的工序行 */
function productRows(productName: string): ShippableProcessItem[] {
  return rows.value.filter((r) => (r.product_name || '未命名产品') === productName)
}

/** 把某产品加入清单；各工序数量默认=跨订单剩余合计（后续可逐工序自定义） */
function addProduct(productName: string) {
  // 已在清单中则原样保留用户已填数量（全选时重复调用不应累加）
  if (cartProducts.value.includes(productName)) return
  cartProducts.value.push(productName)
  // 同一工序跨订单累加剩余量，作为该合并行的默认数量与上限
  const totals = new Map<string, number>()
  for (const r of productRows(productName)) {
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

// ===== 右栏：清单视图（同一 SKU 的同一工序跨订单合并为一行） =====
const cartGroups = computed<CartProduct[]>(() => {
  const out: CartProduct[] = []
  for (const name of cartProducts.value) {
    const list = productRows(name)
    if (!list.length) continue
    // 按工序名合并：同一 SKU 的同一工序跨订单合成一行
    const procMap = new Map<string, ShippableProcessItem[]>()
    for (const r of list) {
      const arr = procMap.get(r.process_type)
      if (arr) arr.push(r)
      else procMap.set(r.process_type, [r])
    }
    const processes: CartProcessRow[] = []
    for (const [processType, entries] of procMap) {
      const key = mergeKey(name, processType)
      let input = mergedInputs.value.get(key)
      if (!input) {
        input = { qty: entries.reduce((s, e) => s + e.remaining, 0), on: true }
        mergedInputs.value.set(key, input)
      }
      processes.push({
        key, processType, entries,
        targetQty: entries.reduce((s, e) => s + e.target_qty, 0),
        remaining: entries.reduce((s, e) => s + e.remaining, 0),
        input,
      })
    }
    out.push({
      key: name,
      productName: name,
      orderIds: [...new Set(list.map((r) => r.order_id))],
      processes,
    })
  }
  return out
})

/** 产品合计：该产品各工序计入合计的数量之和 */
function productCheckedSum(p: CartProduct): number {
  return p.processes.reduce((s, r) => s + rowQty(r), 0)
}

/**
 * 实时剩余未发：剩余合计 − 本次填写数量（发完后剩余）。
 * 仅用于展示；未勾选（不发该工序）时不扣减。
 * 输入已被 onQtyInput 钳制在上限内，故此处恒为非负，显示 0 即代表该工序已全部发出。
 */
function liveRemaining(r: CartProcessRow): number {
  if (!r.input.on) return r.remaining
  return Math.max(0, r.remaining - (Number(r.input.qty) || 0))
}

/**
 * 数量输入实时纠正（发货数量为个位整数，无小数）：
 * - 空：不处理，允许用户中途清空重填；
 * - 小数：向下取整（1.5 → 1），不虚报数量；
 * - ≤0：恢复为该工序剩余合计上限（即默认全发）；
 * - 超过上限：钳制到上限。
 * 每次纠正都同步写回 DOM：纠正后模型值可能与上一次相同（如已在上限再填超限值），
 * Vue 不会重渲染输入框，非法文本会残留在界面上。
 */
function onQtyInput(r: CartProcessRow, e: Event) {
  const el = e.target as HTMLInputElement
  if (el.value === '') return
  const n = Number(el.value)
  if (!Number.isFinite(n)) return
  let fixed: number | null = null
  if (n <= 0) fixed = r.remaining
  else if (!Number.isInteger(n)) fixed = Math.floor(n)
  else if (n > r.remaining) fixed = r.remaining
  if (fixed === null) return
  r.input.qty = fixed
  el.value = String(fixed)
}

/** 产品覆盖的订单数（用于卡头提示） */
function productOrderCount(p: CartProduct): number {
  return p.orderIds.length
}

/** 卡头 ✕：移出该产品的全部工序 */
function removeProductFromCart(p: CartProduct) {
  confirmOpen.value = false
  removeProduct(p.productName)
}

// ===== 汇总（底栏 / 确认态 / 提交共用） =====
/**
 * 单行计入合计的数量：仅已勾选且取值合法时计入，否则记 0。
 * 非法值不参与求和，避免超限输入把合计拉大（合计口径与实际可提交量一致）。
 */
function rowQty(r: CartProcessRow): number {
  if (!r.input.on || isRowInvalid(r)) return 0
  return Number(r.input.qty) || 0
}

const checkedRows = computed(() =>
  cartGroups.value.flatMap((p) => p.processes).filter((r) => r.input.on),
)
const checkedCount = computed(() => checkedRows.value.length)
const shipSum = computed(() => checkedRows.value.reduce((s, r) => s + rowQty(r), 0))
/** 涉及订单数：按各工序拆分后的实际发货订单去重 */
const selectedOrderCount = computed(() => {
  const ids = new Set<number>()
  for (const r of checkedRows.value) {
    for (const it of splitQty(r)) ids.add(it.row.order_id)
  }
  return ids.size
})

/**
 * 把某工序填写的合计数量按订单顺序拆分到各订单。
 * 依次填满每张订单的剩余量，返回实际发货的 { 订单行, 数量 }（数量为 0 的订单不返回）。
 */
function splitQty(r: CartProcessRow): { row: ShippableProcessItem; quantity: number }[] {
  let left = Number(r.input.qty)
  if (!Number.isFinite(left) || left <= 0) return []
  const out: { row: ShippableProcessItem; quantity: number }[] = []
  for (const row of r.entries) {
    if (left <= 0) break
    const take = Math.min(row.remaining, left)
    if (take > 0) {
      out.push({ row, quantity: take })
      left -= take
    }
  }
  return out
}

/**
 * 工序行数量是否非法：空 / 非有限 / 非整数 / <1 / 超过跨订单剩余合计。
 * 已取消的工序不参与提交，不计入非法（后端 quantity 为 int，前端同口径校验）。
 */
function isRowInvalid(r: CartProcessRow): boolean {
  if (!r.input.on) return false
  const n = Number(r.input.qty)
  return !Number.isFinite(n) || !Number.isInteger(n) || n < 1 || n > r.remaining
}
const invalidCount = computed(() => checkedRows.value.filter(isRowInvalid).length)

/** 首条非法行的提示：明确指出工序名与上限，便于直接定位与修正 */
const firstInvalidHint = computed(() => {
  const r = checkedRows.value.find(isRowInvalid)
  if (!r) return ''
  const n = Number(r.input.qty)
  if (!Number.isFinite(n) || n < 1) return `「${r.processType}」需为大于 0 的整数`
  if (!Number.isInteger(n)) return `「${r.processType}」需为整数`
  return `「${r.processType}」不能超过剩余未发 ${r.remaining.toLocaleString()}`
})

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
  // 按订单分组组装 payload（每订单一张发货单）：合并数量已拆分回各订单
  const payloadMap = new Map<number, { order_id: number; items: { process_id: number; quantity: number }[] }>()
  for (const r of checkedRows.value) {
    for (const { row, quantity } of splitQty(r)) {
      let g = payloadMap.get(row.order_id)
      if (!g) {
        g = { order_id: row.order_id, items: [] }
        payloadMap.set(row.order_id, g)
      }
      g.items.push({ process_id: row.process_id, quantity })
    }
  }
  submitting.value = true
  confirmOpen.value = false
  outsourceApi.createShipmentsBatch([...payloadMap.values()])
    .then((res) => {
      result.value = { ok: true, shipments: res.data }
      toast.success(res.message || `已生成 ${res.total} 张发货单`)
      emit('shipped')
    })
    .catch((e) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      result.value = { ok: false, error: msg || '批量发货失败（整批已回滚）' }
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

/* ---- 左栏 ---- */
.osw-left {
  width: 360px; flex-shrink: 0; display: flex; flex-direction: column; min-height: 0;
  border-right: 1px solid var(--color-border-light, #e2e8f0); background: #fff;
}
.osw-l-toolbar { display: flex; gap: 8px; padding: 12px 12px 8px; flex-shrink: 0; }
.osw-search {
  flex: 1; display: flex; align-items: center; gap: 7px;
  border: 1px solid #cbd5e1; border-radius: 9px; padding: 0 10px; background: #fff;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.osw-search:focus-within { border-color: var(--color-primary-300, #93c5fd); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1); }
.osw-search svg { color: var(--color-text-muted, #94a3b8); font-size: 12px; flex-shrink: 0; }
.osw-search input {
  flex: 1; min-width: 0; border: none; outline: none; background: transparent;
  font: inherit; font-size: 13px; padding: 8px 0; color: var(--color-text, #1e293b);
}
.osw-search input::placeholder { color: var(--color-text-muted, #94a3b8); }

.osw-l-meta {
  display: flex; align-items: center; padding: 2px 16px 8px;
  font-size: 12px; color: var(--color-text-muted, #64748b); flex-shrink: 0;
}
.osw-l-meta b { color: var(--color-text, #1e293b); margin: 0 2px; }
.osw-l-meta .osw-link { margin-left: auto; }

.osw-link {
  border: none; background: transparent; color: var(--color-primary-600, #2563eb);
  font: inherit; font-size: 12.5px; font-weight: 700; cursor: pointer;
  padding: 4px 6px; border-radius: 6px; transition: background 0.15s ease;
}
.osw-link:hover:not(:disabled) { background: var(--color-primary-50, #eff6ff); }
.osw-link:disabled { color: #b6c2d2; cursor: not-allowed; }
.osw-link--sm { font-size: 12px; }

.osw-l-list { flex: 1; overflow-y: auto; padding: 2px 12px 12px; scrollbar-gutter: stable; }
.osw-l-empty { padding: 36px 16px; text-align: center; color: var(--color-text-muted, #94a3b8); font-size: 12.5px; }

/* 列表表头：sticky 在滚动容器内；内边距/列宽与 .osw-card 逐列对齐 */
/* 表头与卡片共用 grid 列定义：勾选 | 产品 | 角标 */
.osw-l-head,
.osw-card {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}
.osw-l-head {
  position: sticky; top: 0; z-index: 1;
  margin-bottom: 6px; padding: 6px 12px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 11px; font-weight: 700; letter-spacing: 0.03em;
  color: var(--color-text-muted, #94a3b8);
  background: #fff;
}
.osw-l-head-prod { min-width: 0; }

.osw-card {
  padding: 10px 12px; margin-bottom: 6px;
  background: #fff; border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 10px;
  cursor: pointer; user-select: none;
  transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}
.osw-card:hover { border-color: var(--color-primary-300, #93c5fd); background: #fbfdff; }
.osw-card.is-on {
  border-color: var(--color-primary-300, #93c5fd); background: var(--color-primary-50, #eff6ff);
  box-shadow: inset 3px 0 0 var(--color-primary-600, #2563eb);
}
.osw-cbx { width: 16px; height: 16px; accent-color: var(--color-primary-600, #2563eb); cursor: pointer; margin: 0; }

/* 单行布局：产品名（完整展示） + 跨订单角标 */
.osw-prod-name {
  min-width: 0; font-size: 13.5px; font-weight: 600; color: var(--color-text, #1e293b);
  /* 产品名完整展示：允许折行，不使用省略号截断 */
  overflow-wrap: anywhere; line-height: 1.45;
}
/* 跨订单角标：同一产品分布在多张订单 */
.osw-prod-orders {
  justify-self: start;
  font-size: 10.5px; font-weight: 700; color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb); border: 1px solid var(--color-warning-200, #fde68a);
  border-radius: 5px; padding: 0 5px; line-height: 1.5; white-space: nowrap;
}

/* ---- 右栏 ---- */
.osw-right { flex: 1; min-width: 0; display: flex; flex-direction: column; background: var(--color-surface, #f8fafc); }
.osw-r-head { display: flex; align-items: center; gap: 8px; padding: 12px 16px 10px; flex-shrink: 0; }
.osw-r-title { font-size: 13px; font-weight: 800; color: var(--color-text, #1e293b); }
.osw-chip {
  font-size: 11.5px; font-weight: 700; font-family: ui-monospace, Menlo, Consolas, monospace;
  background: var(--color-primary-50, #eff6ff); color: var(--color-primary-600, #2563eb);
  border: 1px solid var(--color-primary-200, #bfdbfe); border-radius: 999px; padding: 1px 9px;
}
.osw-chip.is-mute { background: #fff; color: var(--color-text-muted, #94a3b8); border-color: var(--color-border-light, #e2e8f0); }
.osw-r-head .osw-link { margin-left: auto; }

.osw-r-list { flex: 1; overflow-y: auto; padding: 0 16px 14px; scrollbar-gutter: stable; }

.osw-cart-empty {
  border: 1.5px dashed #cbd5e1; border-radius: 14px; background: #fff;
  padding: 44px 24px; text-align: center; color: var(--color-text-muted, #94a3b8);
}
.osw-cart-empty-ico {
  width: 52px; height: 52px; border-radius: 16px; background: var(--color-primary-50, #eff6ff);
  color: var(--color-primary-300, #93c5fd); display: flex; align-items: center; justify-content: center;
  margin: 0 auto 12px; font-size: 20px;
}
.osw-cart-empty-t { font-size: 13.5px; font-weight: 700; color: var(--color-text-secondary, #475569); margin-bottom: 4px; }
.osw-cart-empty-s { font-size: 12px; line-height: 1.7; }

.osw-cart-card {
  background: #fff; border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 12px;
  overflow: hidden; margin-bottom: 10px; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.osw-cart-head {
  display: flex; align-items: center; gap: 9px; padding: 9px 12px; border-bottom: 1px solid #eef2f7;
}
.osw-cart-title {
  min-width: 0; font-size: 13px; font-weight: 800; color: var(--color-text, #1e293b);
  overflow-wrap: anywhere; line-height: 1.45;
}
/* 跨订单合并提示：该产品由多张订单汇总而来 */
.osw-cart-orders {
  flex-shrink: 0; font-size: 10.5px; font-weight: 700; color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb); border: 1px solid var(--color-warning-200, #fde68a);
  border-radius: 5px; padding: 0 5px; line-height: 1.6; white-space: nowrap;
}
.osw-cart-sum { margin-left: auto; font-size: 12px; color: var(--color-text-muted, #64748b); white-space: nowrap; }
.osw-cart-sum b { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; font-weight: 800; color: var(--color-primary-600, #2563eb); }
.osw-rm {
  flex-shrink: 0; width: 24px; height: 24px; border-radius: 7px; border: none; background: transparent;
  color: var(--color-text-muted, #94a3b8); cursor: pointer; font-size: 12px;
  display: flex; align-items: center; justify-content: center; transition: background 0.15s ease, color 0.15s ease;
}
.osw-rm:hover { background: var(--color-danger-50, #fef2f2); color: var(--color-danger-500, #dc2626); }

/* 工序格容器：同一 SKU 的全部工序强制单行横向排列，超出宽度横向滚动 */
.osw-proc-grid {
  display: flex; flex-wrap: nowrap; gap: 8px; padding: 10px 12px;
  overflow-x: auto; overscroll-behavior-x: contain;
}
.osw-proc-grid::-webkit-scrollbar { height: 8px; }
.osw-proc-grid::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
.osw-proc-grid::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
.osw-proc-grid::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 4px; }
/* 单个工序格：纵向三段（勾选+工序名 / 剩余量 / 数量框）；固定宽度不收缩，保证单行可滚动 */
.osw-cell {
  flex: 0 0 152px;
  display: flex; flex-direction: column; gap: 4px;
  padding: 8px 10px; border: 1px solid #eef2f7; border-radius: 8px; background: #fff;
  transition: border-color 0.15s ease, opacity 0.15s ease;
}
.osw-cell:hover { border-color: var(--color-primary-300, #93c5fd); }
.osw-cell.is-off { opacity: 0.45; }
.osw-cell-top { display: flex; align-items: center; gap: 6px; }
.osw-proc {
  flex: 1; min-width: 0; font-size: 12px; font-weight: 600; color: var(--color-text, #1e293b);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* 工序格统计区：标签 + 数值，两个数值与数量框文字共用同一右对齐轴 */
.osw-cell-stats { display: flex; flex-direction: column; gap: 1px; padding-right: 9px; }
.osw-total,
.osw-remain {
  display: flex; align-items: baseline; gap: 6px;
  font-size: 11.5px; line-height: 1.5;
  font-variant-numeric: tabular-nums;
}
.osw-total i,
.osw-remain i {
  flex: 0 0 26px; font-style: normal; font-weight: 500;
  color: var(--color-text-muted, #94a3b8);
}
.osw-total b,
.osw-remain b {
  flex: 1; min-width: 0; text-align: right;
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-weight: 700;
}
.osw-total b { color: var(--color-text-secondary, #475569); }
.osw-remain b { color: var(--color-primary-600, #2563eb); }
/* 发完后无剩余：弱化，避免与「已发完」状态混淆 */
.osw-remain.is-zero b { color: var(--color-text-muted, #94a3b8); font-weight: 500; }
.osw-qty {
  width: 100%; padding: 6px 9px; font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 12.5px; font-weight: 700; text-align: right; color: var(--color-text, #1e293b);
  border: 1px solid #cbd5e1; border-radius: 8px; outline: none;
  font-variant-numeric: tabular-nums; transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.osw-qty:focus { border-color: var(--color-primary-300, #93c5fd); box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12); }
.osw-qty:disabled { background: #f1f5f9; color: var(--color-text-muted, #94a3b8); }
.osw-qty.is-invalid { border-color: #f87171; background: var(--color-danger-50, #fef2f2); }
.osw-qty.is-invalid:focus { border-color: var(--color-danger-500, #dc2626); box-shadow: 0 0 0 3px rgba(220, 38, 38, 0.12); }

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

/* ===== 结果态 ===== */
.osw-result-wrap { flex: 1; overflow-y: auto; }
.osw-result { border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.osw-result--ok { background: var(--color-success-50, #f0fdf4); border: 1px solid var(--color-success-200, #bbf7d0); }
.osw-result--fail { background: var(--color-danger-50, #fef2f2); border: 1px solid #fecaca; }
.osw-result-head { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.osw-result--ok .osw-result-head { color: var(--color-success-700, #15803d); }
.osw-result--fail .osw-result-head { color: #b91c1c; }
.osw-result-row {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  background: #fff; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px; padding: 9px 12px; font-size: 12.5px;
}
.osw-mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-weight: 700; }
.osw-badge {
  margin-left: auto; font-size: 11px; font-weight: 700; color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb); border: 1px solid var(--color-warning-200, #fde68a);
  border-radius: 7px; padding: 2px 9px;
}
.osw-result-detail {
  background: #fff; border: 1px solid #fecaca; border-radius: 10px;
  padding: 10px 12px; font-size: 12.5px; color: #b91c1c;
}

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

  .osw-panes[data-tab='pick'] .osw-right { display: none; }
  .osw-panes[data-tab='cart'] .osw-left { display: none; }
  .osw-left { width: 100%; border-right: none; }

  .osw-cart-head { flex-wrap: wrap; row-gap: 2px; }
  .osw-cart-title { flex: 1 1 100%; }
  /* 移动端：仍保持单行横向滚动，仅放大数量框便于触控 */
  .osw-qty { padding: 8px; }

  .osw-bar { flex-direction: column; align-items: stretch; }
  .osw-bar-info { justify-content: center; }
  .osw-bar :deep(button) { flex: 1; justify-content: center; }
}
</style>
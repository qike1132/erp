<template>
  <section class="osw-right">
    <div class="osw-r-head">
      <span class="osw-r-title">发货清单</span>
      <span :class="['osw-chip', { 'is-mute': !groups.length }]">{{ groups.length }} 项</span>
      <button
        type="button"
        class="osw-link osw-link--sm"
        :disabled="!groups.length"
        @click="emit('clear')"
      >清空</button>
    </div>

    <div class="osw-r-list">
      <div v-if="!groups.length" class="osw-cart-empty">
        <div class="osw-cart-empty-ico"><FontAwesomeIcon icon="box-open" aria-hidden="true" /></div>
        <div class="osw-cart-empty-t">发货清单还是空的</div>
        <div class="osw-cart-empty-s">从左侧勾选要发货的产品，在这里核对数量<br>同一工序跨订单合并为一行，数量默认等于剩余合计</div>
      </div>

      <div v-for="p in groups" :key="p.key" class="osw-cart-card">
        <div class="osw-cart-head">
          <span class="osw-cart-title">{{ p.productName }}</span>
          <span v-if="productOrderCount(p) > 1" class="osw-cart-orders">{{ productOrderCount(p) }} 单合并</span>
          <span class="osw-cart-sum"><b>{{ productCheckedSum(p).toLocaleString() }}</b> 件</span>
          <button
            type="button"
            class="osw-rm"
            :aria-label="`移出 ${p.productName} 的全部发货项`"
            @click="emit('remove', p.productName)"
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
</template>

<script setup lang="ts">
/**
 * OutsourceShipCartPanel.vue — 批量发货弹窗右栏「发货清单」
 *
 * 只管核对编辑：数量默认=剩余未发（由父组件构建），可整行取消勾选（不发该工序）、
 * ✕ 移出整卡（emit remove）。「清空」按钮 emit clear，清单状态归父组件持有。
 * 单元格内的数量纠正（onQtyInput）与实时剩余（liveRemaining）为本组件局部交互；
 * rowQty / isRowInvalid 从领域模型导入，与父组件汇总/提交共用同一口径。
 */
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import { isRowInvalid, rowQty, type CartProduct } from './shipCartModel'

defineProps<{
  /** 清单视图模型（由父组件经 buildCartGroups 计算） */
  groups: CartProduct[]
}>()

const emit = defineEmits<{
  (e: 'remove', productName: string): void
  (e: 'clear'): void
}>()

/** 产品合计：该产品各工序计入合计的数量之和 */
function productCheckedSum(p: CartProduct): number {
  return p.processes.reduce((s, r) => s + rowQty(r), 0)
}

/**
 * 实时剩余未发：剩余合计 − 本次填写数量（发完后剩余）。
 * 仅用于展示；未勾选（不发该工序）时不扣减。
 * 输入已被 onQtyInput 钳制在上限内，故此处恒为非负，显示 0 即代表该工序已全部发出。
 */
function liveRemaining(r: CartProduct['processes'][number]): number {
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
function onQtyInput(r: CartProduct['processes'][number], e: Event) {
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
</script>

<style scoped>
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

/* 两栏共用类：scoped 样式不跨组件，在两个子组件内各持一份 */
.osw-link {
  border: none; background: transparent; color: var(--color-primary-600, #2563eb);
  font: inherit; font-size: 12.5px; font-weight: 700; cursor: pointer;
  padding: 4px 6px; border-radius: 6px; transition: background 0.15s ease;
}
.osw-link:hover:not(:disabled) { background: var(--color-primary-50, #eff6ff); }
.osw-link:disabled { color: #b6c2d2; cursor: not-allowed; }
.osw-link--sm { font-size: 12px; }

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

.osw-cbx { width: 16px; height: 16px; accent-color: var(--color-primary-600, #2563eb); cursor: pointer; margin: 0; }

/* 移动端右栏内部规则：从父组件响应式块迁入（父作用域样式无法命中子组件内部元素） */
@media (max-width: 768px) {
  .osw-cart-head { flex-wrap: wrap; row-gap: 2px; }
  .osw-cart-title { flex: 1 1 100%; }
  /* 移动端：仍保持单行横向滚动，仅放大数量框便于触控 */
  .osw-qty { padding: 8px; }
}
</style>

<template>
  <div
    :class="['mrt', { 'is-suphide': mode === 'supplier' }]"
    role="table"
    :aria-label="`来料进度明细，共 ${rowCount} 项物料`"
  >
    <!-- 表头：列轨由 --cols 统一，数据行与之共用 -->
    <div class="mrt-head" role="row">
      <span class="c-date" role="columnheader">到货日期</span>
      <span class="c-ord" role="columnheader">订单 / 客户 · 产品</span>
      <span class="c-mat" role="columnheader">物料 / 规格</span>
      <span class="c-sup" role="columnheader">供应商</span>
      <span class="c-qty" role="columnheader">已到 / 采购</span>
      <span class="c-pct" role="columnheader">进度</span>
      <span class="c-act" role="columnheader"><span class="mrt-sr">操作</span></span>
    </div>

    <template v-for="g in groups" :key="g.key">
      <!-- 分组行：供应商 / 订单 只是视图模式，不是卡片 -->
      <div v-if="g.label" class="mrt-group" role="row">
        <span class="mrt-g-label" role="cell">{{ g.label }}</span>
        <span class="mrt-g-sub" role="cell">{{ g.sublabel }}</span>
        <span v-if="g.slowCount" class="mrt-g-flag" role="cell">≥{{ SLOW_DAYS }} 天 {{ g.slowCount }} 项</span>
        <span class="mrt-g-right">
          <span class="mrt-g-stat">{{ g.doneCount }}/{{ g.rows.length }} 项到齐</span>
          <span
            v-if="g.progressPct != null"
            class="mrt-g-meter"
            role="img"
            :aria-label="`数量进度 ${g.progressPct}%`"
            :title="`同单位数量进度 ${g.progressPct}%（${fmt(g.receivedTotal ?? 0)} / ${fmt(g.orderedTotal ?? 0)} ${g.unit}）`"
          >
            <i :style="{ width: `${g.progressPct}%` }" />
          </span>
          <span v-if="g.latestDate" class="mrt-g-date">最近到货 {{ shortDate(g.latestDate) }}</span>
        </span>
      </div>

      <div
        v-for="r in g.rows"
        :key="r.key"
        :class="['mrt-row', `st-${statusOf(r)}`, { 'is-slow': r.isSlow }]"
        role="row"
      >
        <span class="c-date" role="cell" :title="`到货登记 ${r.arrivedDate || '—'}`">
          <span class="mrt-date">{{ shortDate(r.arrivedDate) }}</span>
          <span :class="['mrt-age', ageClass(r)]">{{ ageLabel(r.ageDays) }}</span>
        </span>

        <span class="c-ord" role="cell" :title="`${r.orderNo} · ${r.customerName} · ${r.productName}`">
          <span class="mrt-po">{{ r.orderNo }}</span>
          <span class="mrt-sub">{{ r.customerName }} · {{ r.productName }}</span>
        </span>

        <span class="c-mat" role="cell" :title="r.specification ? `${r.materialName} / ${r.specification}` : r.materialName">
          <span class="mrt-material">{{ r.materialName }}</span>
          <span v-if="r.specification" class="mrt-spec">{{ r.specification }}</span>
        </span>

        <span class="c-sup" role="cell" :title="r.supplierName">{{ r.supplierName }}</span>

        <span class="c-qty" role="cell" :title="`采购 ${fmt(r.ordered)} ${r.unit}，已到 ${fmt(r.received)} ${r.unit}，欠 ${fmt(r.remaining)} ${r.unit}`">
          <b>{{ fmt(r.received) }}</b><span class="mrt-of">/ {{ fmt(r.ordered) }}</span><span class="mrt-unit">{{ r.unit }}</span>
        </span>

        <span class="c-pct" role="cell">
          <span class="mrt-meter" aria-hidden="true"><i :class="fillClass(r)" :style="{ width: `${clampPct(r.progress)}%` }" /></span>
          <b :class="['mrt-pct', pctClass(r)]">{{ pctLabel(r) }}</b>
        </span>

        <span class="c-act" role="cell">
          <button
            type="button"
            class="mrt-btn"
            :aria-label="`查看 ${r.orderNo} ${r.supplierName} ${r.materialName} 的来料明细`"
            @click="emit('view-detail', r.supplierName, r.orderNo)"
          >
            明细
          </button>
        </span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * ProgressTable.vue — 来料进度表（纯展示）
 *
 * 为什么是表而不是卡：成熟 ERP（ERPNext 的 % Received 列、Odoo 的 receipt_status
 * badge、metasfresh 的 QtyOrdered/QtyDelivered/QtyToDeliver）都把这件事做成**一行物料**，
 * 因为用户要做的是「逐行对比 + 排序 + 筛选」，卡片把可比较性换成了装饰。
 *
 * 列只回答两个业务事实：**哪天到的**、**到了多少**。
 * 组头（供应商/订单）只给「x/y 项到齐」与最近到货；数量合计仅在组内单位一致时出现。
 */
import type { GroupMode, ProgressGroup, ProgressRow, RowStatus } from '../composables/progressRows'
import { SLOW_DAYS, rowStatus } from '../composables/progressRows'
import { formatQuantity } from '@/utils/quantity'
import '../material-progress-table.scss'

defineProps<{
  groups: ProgressGroup[]
  mode: GroupMode
  rowCount: number
}>()

const emit = defineEmits<{
  'view-detail': [supplierName: string, orderNo: string]
}>()

function fmt(n: number): string {
  return formatQuantity(n)
}

function statusOf(r: ProgressRow): RowStatus {
  return rowStatus(r)
}

/** YYYY-MM-DD → MM-DD（完整日期放 title） */
function shortDate(d: string): string {
  return d ? d.slice(5) : '—'
}

/** 到货距今：今天 / N 天（不写「逾期」——系统没有约定交期，只说事实） */
function ageLabel(days: number | null): string {
  if (days == null) return '—'
  if (days <= 0) return '今天'
  return `${days} 天`
}

function ageClass(r: ProgressRow): string {
  if (r.ageDays == null) return ''
  if (r.isSlow) return 'is-slow'
  return r.ageDays >= 7 ? 'is-warm' : ''
}

function clampPct(n: number): number {
  return Math.min(Math.max(n, 0), 100)
}

function fillClass(r: ProgressRow): string {
  if (rowStatus(r) === 'done') return 'fill-done'
  if (r.isSlow) return 'fill-slow'
  if (r.received <= 0) return 'fill-zero'
  return ''
}

function pctClass(r: ProgressRow): string {
  if (rowStatus(r) === 'done') return 'is-done'
  if (r.isSlow) return 'is-slow'
  if (r.received <= 0) return 'is-zero'
  return ''
}

/** 0% 不写「0%」而写「未到」，100% 写「到齐」——用词替代纯数字 */
function pctLabel(r: ProgressRow): string {
  if (rowStatus(r) === 'done') return '到齐'
  if (r.received <= 0) return '未到'
  return `${r.progress}%`
}
</script>

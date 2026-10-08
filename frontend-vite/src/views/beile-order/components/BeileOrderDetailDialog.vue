<template>
  <!-- 订单详情弹窗（简化版）：一行元信息 + SKU 明细表 + 总数量 -->
  <UiDialog v-model:open="detailOpen" :title="isStockin ? '备货详情' : '订单详情'" max-width-class="max-w-[900px]">
    <div v-if="detailData" class="bo-detail">
      <!-- 简洁元信息条：下单时间 + 客户（原「订单/未确认/已开单」三个徽章已移除） -->
      <div class="bo-meta">
        <span class="bo-meta-item"><span class="lbl">下单时间：</span>{{ detailData.order_date || '-' }}</span>
        <span class="bo-meta-item"><span class="lbl">客户：</span>{{ detailData.customer || '-' }}</span>
      </div>

      <!-- SKU 明细（宽表 + 总数量） -->
      <div class="bo-section">
        <div class="bo-sec-title">SKU 明细 <span class="bo-sec-cnt">共 {{ skuList.length }} 个 SKU</span></div>
        <div class="bo-table-wrap">
          <table class="bo-table">
            <thead>
              <tr>
                <th class="c-img">图片</th>
                <th class="c-name">产品名称</th>
                <th class="c-barcode">产品条码</th>
                <th class="c-qty">订单数量</th>
                <th class="c-qty">生产数量</th>
                <th class="c-note">备注</th>
              </tr>
            </thead>
            <tbody>
              <!-- 无 SKU 明细（部分备货记录）：回落为订单级单行 -->
              <tr v-if="skuList.length === 0 && detailData.product_name">
                <td class="c-img"><div class="bo-thumb"><FontAwesomeIcon icon="box" aria-hidden="true" /></div></td>
                <td class="c-name">{{ detailData.product_name }}</td>
                <td class="c-barcode">{{ detailData.barcode || '-' }}</td>
                <td class="c-qty num" :class="{ 'is-po': detailData.is_ordered === true }">{{ totalOrderQty }}</td>
                <td class="c-qty num">{{ totalProdQty ?? '—' }}</td>
                <td class="c-note" :title="detailData.note || ''">{{ detailData.note || '-' }}</td>
              </tr>
              <tr v-else-if="skuList.length === 0">
                <td colspan="6" class="c-empty">暂无 SKU 明细</td>
              </tr>
              <!-- 逐 SKU 明细 -->
              <tr v-for="sku in skuList" v-else :key="sku.id">
                <td class="c-img">
                  <div class="bo-thumb">
                    <img v-if="sku.product_image" :src="resolveStaticUrl(sku.product_image)" :alt="sku.product_name || ''" @error="onImgError" />
                    <FontAwesomeIcon v-else icon="box" aria-hidden="true" />
                  </div>
                </td>
                <td class="c-name" :title="sku.product_name || ''">{{ sku.product_name || detailData.product_name || '-' }}</td>
                <td class="c-barcode">{{ sku.product_barcode || '-' }}</td>
                <td class="c-qty num" :class="{ 'is-po': skuIsOrdered(detailData, sku) }">{{ fmtNum(skuOrderQty(detailData, sku)) }}</td>
                <td class="c-qty num">{{ skuProductionQty(detailData, sku) != null ? fmtNum(skuProductionQty(detailData, sku)!) : '—' }}</td>
                <td class="c-note" :title="sku.note || detailData.note || ''">{{ sku.note || detailData.note || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <!-- 总数量（右下角，带千分位） -->
        <div class="bo-total">
          <span class="bo-total-item"><span class="k">总数量</span><span class="v num">{{ fmtNum(totalOrderQty) }}</span><span class="u">件</span></span>
          <span class="bo-total-item"><span class="k">总生产数量</span><span class="v num v-blue">{{ totalProdQty != null ? fmtNum(totalProdQty) : '—' }}</span><span class="u">件</span></span>
        </div>
      </div>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="detailOpen = false">关闭</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * BeileOrderDetailDialog.vue — 湖北订单详情弹窗（两级结构之二，简化版）
 *
 * 简化布局：
 * - 一行元信息条：下单时间 / 客户（原「订单信息」两列 kv 网格、「订单/未确认/已开单」三个徽章均已移除）；
 * - SKU 明细：宽表（图片/产品名称/条码/订单数量/生产数量/备注），数量带千分位；
 * - 右下角总数量 / 总生产数量（带千分位）。
 *
 * 数量口径复用 useBeileOrders 的 rowTotal* / skuOrderQty / skuProductionQty，
 * 与列表行 / 导出 XLS / 打印预览同源（AC-12）。
 */
import { computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import { resolveStaticUrl } from '@/api/request'
import {
  rowTotalOrderQty,
  rowTotalProductionQty,
  skuIsOrdered,
  skuOrderQty,
  skuProductionQty,
  type BeileOrderRow,
} from '@/views/beile-order/composables/useBeileOrders'

const props = defineProps<{
  /** 当前查看的订单行 */
  detailData: BeileOrderRow | null
}>()

/** 弹窗开关（父组件 v-model:open） */
const detailOpen = defineModel<boolean>('open', { default: false })

const isStockin = computed(() => props.detailData?.record_type === 'stockin')
const skuList = computed(() => props.detailData?.items || [])
const totalOrderQty = computed(() => (props.detailData ? rowTotalOrderQty(props.detailData) : 0))
const totalProdQty = computed(() => (props.detailData ? rowTotalProductionQty(props.detailData) : null))

/** 数字千分位格式化：1234567 → 1,234,567 */
function fmtNum(v: number): string {
  return v.toLocaleString('en-US')
}

/** 图片加载失败时隐藏 img（回退占位图标） */
function onImgError(e: Event) {
  const img = e.target as HTMLImageElement
  img.style.display = 'none'
}
</script>

<style scoped>
.bo-detail {
  display: flex;
  flex-direction: column;
  font-size: 13px;
  color: var(--color-text);
}

/* 元信息条 */
.bo-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 2px 0 16px;
}
.bo-meta-item {
  font-size: 13px;
  color: var(--color-text-secondary);
}
.bo-meta-item .lbl {
  color: var(--color-text-muted);
}

/* 分区标题（蓝色竖条 + 加粗） */
.bo-section {
  border-top: 1px solid var(--color-border-light, #e2e8f0);
  padding-top: 16px;
}
.bo-sec-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 14px;
}
.bo-sec-title::before {
  content: '';
  width: 3px;
  height: 15px;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
}
.bo-sec-cnt {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
}

/* SKU 表 */
.bo-table-wrap {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 6px;
  overflow: hidden;
}
.bo-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.bo-table thead th {
  padding: 9px 12px;
  font-weight: 600;
  font-size: 12px;
  color: var(--color-text-secondary, #64748b);
  background: var(--color-surface, #f8fafc);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  white-space: nowrap;
  text-align: left;
}
.bo-table tbody td {
  padding: 9px 12px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
  color: var(--color-text);
}
.bo-table tbody tr:hover td {
  background: #fbfcff;
}
.c-img {
  width: 56px;
  text-align: center;
}
.c-name {
  min-width: 200px;
  font-weight: 500;
}
.c-barcode {
  width: 130px;
  color: var(--color-text-secondary);
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 12px;
  white-space: nowrap;
}
.c-qty {
  width: 110px;
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
/* 表头对齐修正（列对齐）：
   `.bo-table thead th` 的 `text-align: left`（选择器权重 0,1,2）会覆盖列级对齐类
   （.c-qty / .c-img 均为 0,1,0），使数值列表头左对齐、其下数字右对齐，
   图片列表头左对齐、其下缩略图居中 —— 表头与数据列错位。
   此处按列还原表头对齐（数值列右对齐、图片列居中），与 tbody 单元格一致。 */
.bo-table thead th.c-qty {
  text-align: right;
}
.bo-table thead th.c-img {
  text-align: center;
}
.c-qty.is-po {
  color: var(--color-primary-700, #2d5ab8);
  font-weight: 700;
}
.c-note {
  color: var(--color-text-secondary);
  font-size: 12px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.c-empty {
  text-align: center;
  color: var(--color-text-muted);
  padding: 28px 12px !important;
}
.num {
  font-variant-numeric: tabular-nums;
}

/* 缩略图占位 */
.bo-thumb {
  width: 36px;
  height: 36px;
  margin: 0 auto;
  border-radius: 4px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: #f7f7f7;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c8c8c8;
  font-size: 14px;
  overflow: hidden;
}
.bo-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

/* 总数量（右下角） */
.bo-total {
  display: flex;
  justify-content: flex-end;
  align-items: baseline;
  gap: 32px;
  padding: 14px 4px 0;
}
.bo-total-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.bo-total .k {
  font-size: 13px;
  color: var(--color-text-muted);
}
.bo-total .v {
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text);
}
.bo-total .v-blue {
  color: var(--color-primary-700, #2d5ab8);
}
.bo-total .u {
  font-size: 12px;
  color: var(--color-text-muted);
}

/* 徽章样式（.bo-type-badge / .bo-open-badge / .bo-confirm-badge）已随
   「订单 / 未确认 / 已开单」三个标签一并移除；列表行 BeileOrderRow 仍保留其自有定义。 */

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; }
}
</style>

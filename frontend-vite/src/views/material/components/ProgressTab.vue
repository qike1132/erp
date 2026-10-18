<template>
  <div class="mr-content">
    <div class="mr-card">
      <div class="mr-card-b mr-card-b--flush">
        <div v-if="pIsFetching && progressOrderRows.length" class="mr-fetching-bar"><div class="mr-fetching-progress" /></div>

        <!-- 状态图例：四档状态色恒带文字（不依赖颜色单独传达） -->
        <div class="mr-legend">
          <span class="lg"><span class="sw" style="background:#3a6bd6" />进行中</span>
          <span class="lg"><span class="sw" style="background:#9a6a00" />未开始</span>
          <span class="lg"><span class="sw" style="background:#1e9e55" />已到齐</span>
          <span class="lg"><span class="sw" style="background:#d03b3b" />逾期（超30天未收齐）</span>
          <span class="lg-note">总进度条按供应商分段，段宽 = 采购量占比</span>
        </div>

        <UiDataTable
          :data="filteredRows"
          :columns="progressColumns"
          :loading="pIsLoading && !progressOrderRows.length"
          :paginator="true"
          :rows="pPerPage"
          :total-records="pCount"
          item-unit="条登记"
          row-key="orderNo"
          @page="emit('page', $event)"
        >
          <template #empty>
            <div class="mr-empty">
              <FontAwesomeIcon icon="inbox" />
              <span>{{ showSearchEmpty ? '当前页无匹配的来料登记（搜索仅作用于当前页，可翻页或清空搜索）' : '暂无进行中的来料登记' }}</span>
            </div>
          </template>
          <template #column-body-orderNo="{ row }">
            <div class="mr-order-link">{{ row.orderNo }}</div>
            <div class="mr-td-date">{{ row.poCreateTime || '-' }}</div>
          </template>
          <template #column-body-customerName="{ row }">
            {{ row.customerName || '-' }}
          </template>
          <template #column-body-productName="{ row }">
            <template v-if="row.skuItems && row.skuItems.length > 1">
              <div v-for="(sku, idx) in row.skuItems" :key="sku.barcode || sku.product_name || idx" class="mr-sku-line">{{ sku.product_name || '-' }}</div>
            </template>
            <span v-else class="mr-sku-line">{{ row.productName || '-' }}</span>
          </template>
          <template #column-body-productQuantity="{ row }">
            <span class="mr-td-qty">{{ row.productQuantity != null ? fmtQty(row.productQuantity) : '-' }}</span>
          </template>
          <template #column-body-groups="{ row }">
            <div class="mr-supplier-groups">
              <SupplierGroupCard
                v-for="grp in row.groups"
                :key="row.orderNo + '|' + grp.supplierName"
                :order-no="row.orderNo"
                :group="grp"
                :collapsed="collapsedGroups.has(row.orderNo + '|' + grp.supplierName)"
                @toggle="toggleGroup(row.orderNo + '|' + grp.supplierName)"
              />
            </div>
          </template>
          <template #column-body-progress="{ row }">
            <div class="mr-seg-row">
              <div class="mr-stack">
                <div
                  v-for="grp in row.groups"
                  :key="grp.supplierName"
                  :class="['mr-seg', segClass(grp)]"
                  :style="{ width: segWidth(row, grp) }"
                  :title="`${grp.supplierName} ${grp.progress}%${grp.overdue ? '（逾期）' : ''}`"
                />
              </div>
              <div class="mr-stack-note">{{ row.progress }}% · {{ row.groups.length }} 家供应商<span v-if="row.hasOverdue" class="is-overdue-txt"> · 有逾期</span></div>
            </div>
          </template>
          <template #column-body-actions="{ row }">
            <div class="mr-action-group"><button type="button" class="mr-action-btn mr-action-view" title="查看供应商详情" aria-label="查看供应商详情" @click="emit('view-supplier', row.groups[0]?.supplierName || '', row.orderNo)"><FontAwesomeIcon icon="eye" /></button></div>
          </template>
        </UiDataTable>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * ProgressTab.vue — 来料进度 Tab（方案A改版）
 *
 * 改版要点：
 *  · 一行 = 一个采购订单（同单多条登记合并），供应商块默认展开——
 *    collapse 语义反转：记"已收起"集合，未记录即展开（旧版记"已展开"，默认全折叠）
 *  · 总进度列 = 按供应商分段堆叠条：段宽 = 该登记采购量占整单比例、
 *    段色 = 组状态四档；2px 表面缝隙分隔相邻段
 *  · 供应商块抽至 SupplierGroupCard；四档状态色与图例、KPI 一致
 */
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import type { ProgressOrderRow, SupplierGroupRow } from '../composables/useMaterialRegistrations'
import SupplierGroupCard from './SupplierGroupCard.vue'
import { reactive } from 'vue'

defineProps<{
  /** 搜索过滤后的行（父级持有搜索词） */
  filteredRows: ProgressOrderRow[]
  /** 未过滤的行（fetching 提示与空态判断用） */
  progressOrderRows: ProgressOrderRow[]
  pIsLoading: boolean
  pIsFetching: boolean
  pPerPage: number
  pPages: number
  /** 后端精确总条数（2026-10-17 审计 P2-43：此前用 pages × perPage 估算） */
  pCount: number
  showSearchEmpty: boolean
}>()

const emit = defineEmits<{
  page: [event: { page: number; rows: number }]
  'view-supplier': [supplierName: string, orderNo: string]
}>()

// 收起语义：默认展开，仅记录用户手动收起的组
const collapsedGroups = reactive(new Set<string>())
function toggleGroup(key: string) {
  if (collapsedGroups.has(key)) collapsedGroups.delete(key)
  else collapsedGroups.add(key)
}

/** 分段色档：逾期 > 已到齐 > 进行中 > 未动（与 SupplierGroupCard 四档一致） */
function segClass(grp: SupplierGroupRow): string {
  if (grp.overdue) return 'seg-overdue'
  if (grp.progress >= 100) return 'seg-done'
  if (grp.progress > 0) return 'seg-ongoing'
  return 'seg-zero'
}

/** 段宽 = 该登记采购量占整单采购量的比例 */
function segWidth(row: ProgressOrderRow, grp: SupplierGroupRow): string {
  const total = row.groups.reduce((s, g) => s + g.items.reduce((x, i) => x + i.ordered_quantity, 0), 0)
  const own = grp.items.reduce((x, i) => x + i.ordered_quantity, 0)
  if (total <= 0) return `${Math.round(100 / row.groups.length)}%`
  return `${Math.max(Math.round((own / total) * 100), 1)}%`
}

/** 订单数量千分位 */
function fmtQty(n: number): string {
  return Number.isInteger(n) ? n.toLocaleString('en-US') : String(Math.round(n * 100) / 100)
}

/** UiDataTable 列定义 */
const progressColumns: TableColumn[] = [
  { field: 'orderNo', header: '订单号/时间', width: '130px', align: 'center' },
  { field: 'customerName', header: '客户', width: '100px', align: 'center' },
  { field: 'productName', header: '产品名称', align: 'left' },
  { field: 'productQuantity', header: '订单数量', width: '100px', align: 'center' },
  { field: 'groups', header: '物料进度（按供应商分组）', align: 'left' },
  { field: 'progress', header: '总进度（按供应商分段）', width: '200px', align: 'center' },
  { field: 'actions', header: '操作', width: '80px', align: 'center' },
]
</script>

<style scoped lang="scss">
/* === Content area === */
.mr-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0;
}

.mr-card { background: white; border-radius: 0; margin-bottom: 0; overflow: hidden; }
.mr-card-b { padding: 24px; }
.mr-card-b--flush { padding: 0; overflow-x: auto; }

.mr-card-b--flush :deep(.p-datatable-tbody > tr) {
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

/* === 状态图例行 === */
.mr-legend {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 20px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
  background: #fafbfe;
  flex-wrap: wrap;
}
.mr-legend .lg { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--color-text-secondary, #475569); }
.mr-legend .sw { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.mr-legend .lg-note { font-size: 11px; color: var(--color-text-muted, #64748b); margin-left: auto; }

.mr-order-link { font-size: 13px; font-weight: 600; color: var(--color-primary-600, #3a6bd6); white-space: nowrap; }
.mr-sku-line { font-size: 14px; color: var(--color-text, #1a1a2e); padding: 2px 0; line-height: 1.4; }
.mr-sku-line + .mr-sku-line { border-top: 1px dashed var(--color-border, #e5e7eb); }

.mr-td-qty { font-size: 14px; font-weight: 600; color: var(--color-text, #1a1a2e); text-align: right; font-variant-numeric: tabular-nums; }
.mr-td-date { font-size: 11px; color: var(--color-text-muted, #64748b); white-space: nowrap; font-variant-numeric: tabular-nums; margin-top: 2px; }

/* === 供应商块容器（块本体在 SupplierGroupCard） === */
.mr-supplier-groups { display: flex; flex-direction: column; gap: 8px; min-width: 420px; }

/* === 总进度：分段堆叠条（2px 表面缝隙分隔相邻段） === */
.mr-seg-row { display: flex; flex-direction: column; gap: 3px; align-items: center; }
.mr-stack { display: flex; gap: 2px; width: 170px; height: 12px; align-items: stretch; }
.mr-stack .mr-seg { border-radius: 2px; min-width: 2px; }
.mr-stack .mr-seg.seg-ongoing { background: #3a6bd6; }
.mr-stack .mr-seg.seg-done { background: #1e9e55; }
.mr-stack .mr-seg.seg-zero { background: #9a6a00; }
.mr-stack .mr-seg.seg-overdue { background: #d03b3b; }
.mr-stack-note { font-size: 10.5px; color: var(--color-text-muted, #64748b); white-space: nowrap; }
.mr-stack-note .is-overdue-txt { color: #d03b3b; font-weight: 700; }

/* === Action Buttons === */
.mr-action-group { display: flex; gap: 6px; }
.mr-action-btn {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  transition: all 0.2s ease;
  cursor: pointer;
}
.mr-action-view { background: var(--color-primary-50, #eff5ff); color: var(--color-primary-600, #5b8def); }
.mr-action-view:hover { background: var(--color-primary-500, #5b8def); color: white; transform: translateY(-1px); }

/* === Empty State === */
.mr-empty {
  text-align: center;
  padding: 40px 20px;
  color: var(--color-text-muted, #64748b);
  font-size: 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.mr-empty i { font-size: 28px; opacity: 0.5; }

/* Fetching progress bar */
.mr-fetching-bar {
  padding: 0 !important;
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
}
.mr-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: mr-progress-slide 1s ease-in-out infinite;
}
@keyframes mr-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>

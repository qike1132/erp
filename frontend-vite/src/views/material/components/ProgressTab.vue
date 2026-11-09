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
          <span class="lg-note">进度 = 已到数量 / 采购数量</span>
        </div>

        <div v-if="!filteredRows.length" class="mr-empty">
          <FontAwesomeIcon icon="inbox" />
          <span>{{ showSearchEmpty ? '当前页无匹配的来料登记（搜索仅作用于当前页，可翻页或清空搜索）' : '暂无进行中的来料登记' }}</span>
        </div>

        <MaterialProgressGrid v-else :rows="filteredRows" @view-supplier="onViewSupplier" />
      </div>

      <UiPagination
        v-if="pCount > 0 || pPages > 1"
        :current-page="pPage"
        :total-pages="Math.max(1, pPages)"
        :total-items="pCount > 0 ? pCount : undefined"
        :page-size="pPerPage"
        :page-size-options="[10, 20, 50, 100]"
        item-unit="条登记"
        @update:current-page="onPage"
        @update:page-size="onPageSize"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * ProgressTab.vue — 来料进度 Tab（整页网格表容器）
 *
 * 2026-11-09 改版：取消「7 列表格 + 供应商卡片」，整页改为一张网格表
 * （MaterialProgressGrid），外观与合并方式对齐 /purchase「工厂汇总」表。
 * 分页由 UiPagination 承担，向父级沿用 0 基页码契约（UiDataTable 时代的行为不变）。
 */
import UiPagination from '@/components/ui/UiPagination.vue'
import MaterialProgressGrid from './MaterialProgressGrid.vue'
import type { ProgressOrderRow } from '../composables/useMaterialRegistrations'

const props = defineProps<{
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
  /** 受控页码：避免 total 变化时自动复位到第 1 页 */
  pPage: number
  showSearchEmpty: boolean
}>()

const emit = defineEmits<{
  page: [event: { page: number; rows: number }]
  'view-supplier': [supplierName: string, orderNo: string]
}>()

function onViewSupplier(supplierName: string, orderNo: string) {
  emit('view-supplier', supplierName, orderNo)
}

/** UiPagination 用 1 基页码，父级沿用 0 基契约 */
function onPage(page: number) {
  emit('page', { page: page - 1, rows: props.pPerPage })
}

function onPageSize(rows: number) {
  emit('page', { page: 0, rows })
}
</script>

<style scoped lang="scss">
.mr-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0;
}

.mr-card { background: white; border-radius: 0; margin-bottom: 0; overflow: hidden; }
.mr-card-b { padding: 24px; }
.mr-card-b--flush { padding: 0; }

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
.mr-legend .lg { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--color-text-secondary, #475569); }
.mr-legend .sw { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
.mr-legend .lg-note { font-size: 12px; color: var(--color-text-muted, #64748b); margin-left: auto; }

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
.mr-empty svg { font-size: 28px; opacity: 0.5; }

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

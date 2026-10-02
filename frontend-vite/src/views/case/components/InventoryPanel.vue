<template>
  <div class="ip-wrap">
    <!-- 统计卡 -->
    <div class="ip-stat-row">
      <UiStatCard accent="blue">
        <template #label>皮套种类</template>
        {{ invStats?.total_items ?? invTotal }}
      </UiStatCard>
      <UiStatCard accent="green">
        <template #label>当前总库存</template>
        {{ invStats?.total_stock ?? 0 }}
      </UiStatCard>
      <UiStatCard accent="purple">
        <template #label>累计入库</template>
        {{ invStats?.total_in ?? 0 }}
      </UiStatCard>
      <UiStatCard accent="red">
        <template #label>累计出库</template>
        {{ invStats?.total_out ?? 0 }}
      </UiStatCard>
    </div>

    <div class="ip-section">
      <div class="ip-header">
        <div class="ip-title">
          <FontAwesomeIcon icon="warehouse" style="color: var(--color-primary-500)" aria-hidden="true" />
          皮套库存
          <small class="ip-sub">主件可展开查看配件</small>
        </div>
        <div class="ip-actions">
          <UiSearchInput v-model="invSearch" placeholder="搜索皮套名称 / 69码" @search="onInvSearchInput" />
          <button class="ip-btn ip-btn-ghost" aria-label="刷新" @click="invRefetch()">
            <FontAwesomeIcon icon="sync-alt" style="margin-right: 4px" aria-hidden="true" />刷新
          </button>
          <button class="ip-btn ip-btn-ghost" aria-label="导出 Excel" @click="exportInventory()">
            <FontAwesomeIcon icon="file-excel" style="margin-right: 4px" aria-hidden="true" />导出
          </button>
        </div>
      </div>

      <div v-if="invIsFetching && inventoryList.length" class="ip-fetching-bar"><div class="ip-fetching-progress" /></div>

      <div v-if="invIsLoading && !inventoryList.length" class="ip-empty">
        <UiLoadingIcon :loading="true" icon="spinner" size="lg" /><span>加载中…</span>
      </div>
      <div v-else-if="!inventoryList.length" class="ip-empty">
        <FontAwesomeIcon icon="warehouse" aria-hidden="true" /><span>暂无库存数据</span>
      </div>

      <table v-else class="ip-table">
        <thead>
          <tr>
            <th class="left">皮套 / SKU</th>
            <th>69码</th>
            <th>单位</th>
            <th>期初</th>
            <th>入库</th>
            <th>出库</th>
            <th>结存</th>
            <th>流水</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="node in inventoryList" :key="node.id">
            <tr :class="['ip-row', 'ip-parent', { 'ip-open': isOpen(node.id) }]" @click="toggle(node.id)">
              <td class="left">
                <span class="ip-caret"><FontAwesomeIcon icon="chevron-right" aria-hidden="true" /></span>
                <strong class="ip-name">{{ node.name }}</strong>
                <span v-if="node.children.length" class="ip-tag">主件 · {{ node.children.length }} 配件</span>
              </td>
              <td><small class="ip-barcode">{{ node.barcode || '-' }}</small></td>
              <td>{{ node.unit || '-' }}</td>
              <td>{{ node.initial_stock }}</td>
              <td class="ip-in">{{ node.total_in }}</td>
              <td class="ip-out">{{ node.total_out }}</td>
              <td><span :class="['ip-stock', stockClass(node.current_stock)]">{{ node.current_stock }}</span></td>
              <td><button class="ip-btn ip-btn-ghost" aria-label="查看流水" @click.stop="openLogDrawer(node)">流水</button></td>
            </tr>
            <tr
              v-for="child in node.children"
              v-show="isOpen(node.id)"
              :key="child.id"
              class="ip-row ip-child"
            >
              <td class="left ip-indent">
                {{ child.name }}
                <span class="ip-tag ip-tag-part">配件</span>
              </td>
              <td><small class="ip-barcode">{{ child.barcode || '-' }}</small></td>
              <td>{{ child.unit || '-' }}</td>
              <td>{{ child.initial_stock }}</td>
              <td class="ip-in">{{ child.total_in }}</td>
              <td class="ip-out">{{ child.total_out }}</td>
              <td><span :class="['ip-stock', stockClass(child.current_stock)]">{{ child.current_stock }}</span></td>
              <td><button class="ip-btn ip-btn-ghost" aria-label="查看流水" @click.stop="openLogDrawer(node, child)">流水</button></td>
            </tr>
          </template>
        </tbody>
      </table>

      <div v-if="invTotalPages > 1" class="ip-pager">
        <button class="ip-btn ip-btn-ghost" :disabled="invPage <= 1" @click="goPage(invPage - 1)">上一页</button>
        <span class="ip-page-info">{{ invPage }} / {{ invTotalPages }}</span>
        <button class="ip-btn ip-btn-ghost" :disabled="invPage >= invTotalPages" @click="goPage(invPage + 1)">下一页</button>
      </div>
    </div>

    <InventoryLogDrawer
      v-model:visible="drawerOpen"
      :selected-case="selectedCase"
      :log-total-pages="logTotalPages"
      :log-per-page="logPerPage"
      :log-is-loading="logIsLoading"
      :log-is-fetching="logIsFetching"
      :log-list="logList"
      :on-log-page-change="onLogPageChange"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * InventoryPanel — 皮套库存查询：统计卡 + 主件分组的库存表（可展开配件）+ 单 SKU 流水抽屉。
 */
import { ref } from 'vue'
import UiStatCard from '@/components/ui/UiStatCard.vue'
import UiSearchInput from '@/components/ui/UiSearchInput.vue'
import UiLoadingIcon from '@/components/ui/UiLoadingIcon.vue'
import InventoryLogDrawer from './InventoryLogDrawer.vue'
import { caseApi } from '@/api'
import type { CaseItem, CaseInventoryNode } from '@/api/case'
import { useCaseInventory } from '../composables/useCaseInventory'

const {
  invSearch,
  invPage,
  invPerPage,
  invIsLoading,
  invIsFetching,
  invRefetch,
  inventoryList,
  invTotal,
  invTotalPages,
  invStats,
  onInvSearchInput,
  onInvPageChange,
  openLogDrawer: openDrawer,
  selectedCase,
  drawerOpen,
  logPerPage,
  logTotalPages,
  logIsLoading,
  logIsFetching,
  logList,
  onLogPageChange,
} = useCaseInventory()

// ===== 展开状态 =====
const expanded = ref<Set<number>>(new Set())
function isOpen(id: number) {
  return expanded.value.has(id)
}
function toggle(id: number) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function stockClass(stock: number): string {
  if (stock <= 0) return 'ip-stock-zero'
  if (stock <= 10) return 'ip-stock-low'
  return 'ip-stock-ok'
}

function openLogDrawer(node: CaseInventoryNode, child?: CaseItem) {
  openDrawer({ ...(child ?? node) } as CaseInventoryNode)
}

function goPage(page: number) {
  if (page < 1 || page > invTotalPages.value) return
  onInvPageChange({ page: page - 1, rows: invPerPage.value })
}

function exportInventory() {
  void caseApi.exportXlsx({ scope: 'inventory', search: invSearch.value || undefined })
}
</script>

<style scoped>
.ip-wrap { display: flex; flex-direction: column; gap: 16px; }
.ip-stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
@media (max-width: 768px) { .ip-stat-row { grid-template-columns: repeat(2, 1fr); } }

.ip-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}
.ip-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-wrap: wrap; gap: 8px;
}
.ip-title { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 700; color: var(--color-text); }
.ip-sub { color: var(--color-text-muted); font-weight: 400; }
.ip-actions { display: flex; gap: 8px; align-items: center; }

.ip-btn {
  padding: 6px 12px; border-radius: 9px; font-size: 12px; font-weight: 600;
  cursor: pointer; display: inline-flex; align-items: center;
}
.ip-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ip-btn-ghost { border: 2px solid var(--color-border-light, #e2e8f0); background: white; color: var(--color-text-secondary); }
.ip-btn-ghost:hover:not(:disabled) { background: var(--color-primary-50); color: var(--color-primary-600); }

.ip-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.ip-table thead th {
  background: var(--color-surface); padding: 9px 12px; text-align: center;
  font-size: 12px; font-weight: 600; color: var(--color-text-secondary);
  border-bottom: 2px solid var(--color-border);
}
.ip-table td { padding: 9px 12px; border-bottom: 1px solid var(--color-border-light); text-align: center; font-variant-numeric: tabular-nums; }
.ip-table th.left, .ip-table td.left { text-align: left; }
.ip-parent { cursor: pointer; background: #fbfcff; }
.ip-parent:hover { background: var(--color-primary-50); }
.ip-caret { display: inline-block; width: 14px; color: var(--color-text-muted); transition: transform 0.2s; }
.ip-parent.ip-open .ip-caret { transform: rotate(90deg); }
.ip-child td { background: #fcfdff; }
.ip-indent { padding-left: 36px !important; color: var(--color-text-secondary); }

.ip-name { color: var(--color-text); }
.ip-barcode { color: var(--color-text-muted); }
.ip-in { color: var(--color-success-600); font-weight: 600; }
.ip-out { color: var(--color-danger-500); font-weight: 600; }
.ip-stock { font-weight: 800; }
.ip-stock-ok { color: var(--color-success-600); }
.ip-stock-low { color: var(--color-warning-600, #d48806); }
.ip-stock-zero { color: var(--color-danger-500); }

.ip-tag {
  display: inline-flex; align-items: center; font-size: 11px; padding: 2px 7px;
  border-radius: 6px; background: var(--color-primary-50); color: var(--color-primary-700);
  font-weight: 600; margin-left: 6px;
}
.ip-tag-part { background: var(--color-border-light); color: var(--color-text-secondary); font-weight: 500; }

.ip-pager { display: flex; align-items: center; justify-content: center; gap: 12px; padding: 12px; }
.ip-page-info { font-size: 13px; color: var(--color-text-secondary); }

.ip-empty {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 32px 0; color: var(--color-text-muted);
}
.ip-empty i { font-size: 28px; opacity: 0.5; }

.ip-fetching-bar { height: 2px; background: var(--color-primary-100, #e0f2fe); overflow: hidden; }
.ip-fetching-progress { height: 100%; width: 30%; background: var(--color-primary-500); animation: ip-slide 1s ease-in-out infinite; }
@keyframes ip-slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(400%); } }
</style>

<template>
  <div class="pct-wrap">
    <!-- 屏幕表格（不打印） -->
    <div class="pct-screen">
      <div class="pct-toolbar">
        <span class="pct-title"><i class="fas fa-clipboard-check" aria-hidden="true" /> 已完成打样项目</span>
        <div class="pct-actions">
          <button type="button" class="pct-btn" @click="$emit('export')" title="导出 Excel">
            <i class="fas fa-file-excel" aria-hidden="true" /> 导出 Excel
          </button>
          <button type="button" class="pct-btn pct-btn--print" @click="$emit('print')" title="打印">
            <i class="fas fa-print" aria-hidden="true" /> 打印
          </button>
        </div>
      </div>

      <div v-if="loading" class="pct-loading">
        <UiSpinner size="sm" />
        <span>加载中...</span>
      </div>
      <div v-else-if="items.length === 0" class="pct-empty">
        <i class="fas fa-inbox" aria-hidden="true" />
        <span>暂无已完成项目</span>
      </div>
      <div v-else class="pct-table-scroll">
        <table class="pct-table">
          <thead>
            <tr>
              <th>序列号</th>
              <th>产品名</th>
              <th>版师</th>
              <th>完成时间</th>
              <th>部位数量</th>
              <th>操作人</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in items"
              :key="row.id"
              class="pct-row"
              role="button"
              tabindex="0"
              @click="$emit('select', row.id)"
              @keyup.enter="$emit('select', row.id)"
            >
              <td>{{ row.sequence_no || '-' }}</td>
              <td class="pct-name">{{ row.product_name || '-' }}</td>
              <td>{{ row.pattern_maker_name || '-' }}</td>
              <td>{{ row.completed_at || '-' }}</td>
              <td>{{ row.parts_count }}</td>
              <td>{{ row.operator_name || '-' }}</td>
              <td><span class="pct-status">已完成</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 打印内容：Teleport 到 body，仅打印时显示 -->
    <Teleport to="body">
      <div class="pct-print-sheet">
        <h2 class="pct-print-title">已完成打样项目</h2>
        <table class="pct-table">
          <thead>
            <tr>
              <th>序列号</th>
              <th>产品名</th>
              <th>版师</th>
              <th>完成时间</th>
              <th>部位数量</th>
              <th>操作人</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id">
              <td>{{ row.sequence_no || '-' }}</td>
              <td class="pct-name">{{ row.product_name || '-' }}</td>
              <td>{{ row.pattern_maker_name || '-' }}</td>
              <td>{{ row.completed_at || '-' }}</td>
              <td>{{ row.parts_count }}</td>
              <td>{{ row.operator_name || '-' }}</td>
              <td>已完成</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import UiSpinner from '@/components/ui/UiSpinner.vue'
import type { CompletedTableRow } from '@/api/patternRoom'

defineProps<{
  items: CompletedTableRow[]
  loading: boolean
}>()

defineEmits<{
  select: [id: number]
  export: []
  print: []
}>()
</script>

<style scoped>
.pct-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.pct-screen {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pct-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--color-border-light, #e5e7eb);
  flex-shrink: 0;
}

.pct-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.pct-actions {
  display: inline-flex;
  gap: 6px;
}

.pct-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: #fff;
  font-size: 12px;
  color: var(--color-text-primary);
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}

.pct-btn:hover {
  border-color: #16a34a;
  color: #16a34a;
  background: #16a34a0a;
}

.pct-btn--print:hover {
  border-color: #ff9f43;
  color: #ff9f43;
  background: #ff9f4308;
}

.pct-loading,
.pct-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex: 1;
  color: var(--color-text-secondary, #9ca3af);
  font-size: 13px;
}

.pct-empty {
  flex-direction: column;
  gap: 8px;
}

.pct-empty i {
  font-size: 32px;
  opacity: 0.5;
}

.pct-table-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.pct-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.pct-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 8px 10px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text-secondary, #6b7280);
  background: #f9fafb;
  border-bottom: 1px solid var(--color-border-light, #e5e7eb);
  white-space: nowrap;
}

.pct-table td {
  padding: 7px 10px;
  border-bottom: 1px solid #f3f4f6;
  color: var(--color-text-primary);
  white-space: nowrap;
}

.pct-table tbody tr:nth-child(even) {
  background: #fafafa;
}

.pct-row {
  cursor: pointer;
  transition: background 0.12s;
}

.pct-row:hover {
  background: #ff9f4310;
}

.pct-name {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pct-status {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  background: #16a34a1a;
  color: #16a34a;
  font-size: 11px;
  font-weight: 600;
}

/* ============ 打印隔离：body 添加 pct-printing 后仅显示表格 ============ */
:global(body.pct-printing > *) {
  display: none !important;
}

:global(body.pct-printing > .pct-print-sheet) {
  display: block !important;
  padding: 20px;
}

@media print {
  @page {
    margin: 0;
  }
}

.pct-print-sheet {
  display: none;
}

.pct-print-title {
  font-size: 18px;
  text-align: center;
  margin: 0 0 12px;
  color: #111827;
}
</style>

<template>
  <div class="m-data-table" role="table">
    <div v-if="loading" class="m-dt-loading">
      <MSkeleton variant="list" :count="3" />
    </div>

    <template v-else>
      <!-- Column Headers -->
      <div class="m-dt-header" role="rowgroup">
        <div class="m-dt-row m-dt-row--head" role="row">
          <div
            v-for="col in columns"
            :key="col.key"
            :class="['m-dt-cell', 'm-dt-cell--head', col.align ? `m-dt-cell--${col.align}` : '']"
            :style="col.width ? { flex: '0 0 ' + col.width } : { flex: 1 }"
            role="columnheader"
          >
            {{ col.label }}
          </div>
        </div>
      </div>

      <!-- Data Rows -->
      <div class="m-dt-body" role="rowgroup">
        <div
          v-for="(row, idx) in data"
          :key="rowKey ? (row[rowKey] as PropertyKey) : idx"
          :class="['m-dt-row', { 'm-dt-row--clickable': clickable }]"
          role="row"
          @click="clickable && $emit('rowClick', row)"
        >
          <div
            v-for="col in columns"
            :key="col.key"
            :class="['m-dt-cell', col.align ? `m-dt-cell--${col.align}` : '']"
            :style="col.width ? { flex: '0 0 ' + col.width } : { flex: 1 }"
            role="cell"
          >
            <slot :name="'cell-' + col.key" :row="row" :value="row[col.key]">
              <span v-if="col.format" class="m-dt-cell-text">{{ col.format(row[col.key], row) }}</span>
              <span v-else class="m-dt-cell-text">{{ row[col.key] }}</span>
            </slot>
          </div>
        </div>

        <MEmpty v-if="!data.length" title="暂无数据" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts" generic="T extends Record<string, unknown>">
import MSkeleton from './MSkeleton.vue'
import MEmpty from './MEmpty.vue'

export interface MTableColumn<T extends Record<string, unknown> = Record<string, unknown>> {
  key: string
  label: string
  width?: string
  align?: 'left' | 'center' | 'right'
  format?: (val: unknown, row: T) => string
}

defineProps<{
  columns: MTableColumn<T>[]
  data: T[]
  loading?: boolean
  clickable?: boolean
  rowKey?: string
}>()

defineEmits<{
  (e: 'rowClick', row: T): void
}>()
</script>

<style scoped>
.m-data-table {
  background: var(--m-bg-surface);
  border-radius: var(--m-radius-card);
  overflow: hidden;
  box-shadow: var(--m-shadow-card);
}

.m-dt-header {
  background: var(--m-bg-grouped);
  border-bottom: var(--m-border-light);
}

.m-dt-row {
  display: flex;
  align-items: center;
  border-bottom: var(--m-border-subtle);
}

.m-dt-row:last-child {
  border-bottom: none;
}

.m-dt-row--head {
  background: var(--m-bg-grouped);
}

.m-dt-row--clickable {
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: background 0.15s var(--m-ease-smooth);
}

.m-dt-row--clickable:active {
  background: rgba(0, 0, 0, 0.02);
}

.m-dt-cell {
  padding: 12px 10px;
  min-width: 0;
}

.m-dt-cell--head {
  font-size: var(--m-font-label-sm);
  font-weight: var(--m-font-weight-semibold);
  color: var(--m-text-secondary);
  text-transform: none;
  letter-spacing: 0;
}

.m-dt-cell--center {
  text-align: center;
}
.m-dt-cell--right {
  text-align: right;
}

.m-dt-cell-text {
  font-size: var(--m-font-body);
  color: var(--m-text-primary);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
}

.m-dt-loading {
  padding: 0;
}
</style>

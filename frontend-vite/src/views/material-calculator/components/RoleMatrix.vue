<template>
  <div class="mc-matrix">
    <div class="mc-matrix-head">
      <FontAwesomeIcon icon="table-cells" aria-hidden="true" />
      <span class="mc-matrix-title">跨角色对比矩阵</span>
      <span class="mc-matrix-sub">{{ scopes.length }} 个作用域 · {{ rows.length }} 行</span>
    </div>

    <div v-if="!rows.length" class="mc-matrix-empty">各作用域暂无物料可比对</div>

    <div v-else class="mc-matrix-scroll">
      <table class="mc-matrix-table">
        <thead>
          <tr>
            <th class="mc-mx-col-name">物料</th>
            <th>规格</th>
            <th>供应商</th>
            <th>单位</th>
            <th v-for="s in scopes" :key="s.key" class="mc-mx-num">{{ s.roleName }}</th>
            <th class="mc-mx-num mc-mx-col-total">合计</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.key" :class="{ 'mc-mx-split-row': row.unitConflict }">
            <td class="mc-mx-col-name">
              <span class="mc-mx-cat" :class="`mc-mx-cat-${row.category}`">{{ categoryLabel(row.category) }}</span>
              <span class="mc-mx-name">{{ row.materialName }}</span>
              <span
                v-if="row.unitConflict"
                class="mc-mx-split-tag"
                title="该物料在不同作用域单位不一致，已按单位拆行（绝不跨单位相加）"
              >单位拆行</span>
            </td>
            <td>{{ row.specification || '—' }}</td>
            <td>{{ row.supplierName || '—' }}</td>
            <td>{{ row.unit || '—' }}</td>
            <td v-for="s in scopes" :key="s.key" class="mc-mx-num">{{ cellText(row, s.key) }}</td>
            <td class="mc-mx-num mc-mx-col-total">{{ totalText(row) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
// 跨角色对比矩阵表：数据完全来自纯函数 roleMatrix.deriveRoleMatrix（不在此处重算/重排）。
import type { MatrixCategory, MatrixRow, MatrixScope } from '@/utils/roleMatrix'

defineProps<{
  /** 列：作用域（默认 BOM 恒首，顺序由后端/纯函数决定，前端不重排）。 */
  scopes: MatrixScope[]
  /** 行：已按 A-8 排序展平的叶子行。 */
  rows: MatrixRow[]
}>()

const CATEGORY_LABELS: Record<MatrixCategory, string> = {
  filling: '填充',
  fabric: '面料',
  accessory: '辅料',
}

function categoryLabel(category: MatrixCategory): string {
  return CATEGORY_LABELS[category] ?? category
}

/** 数值格式化：整数原样，非整数最多 3 位小数去尾零。矩阵内保留原始单位数值（不做克→kg）。 */
function numText(v: number): string {
  if (Number.isInteger(v)) return String(v)
  return String(parseFloat(v.toFixed(3)))
}

function cellText(row: MatrixRow, scopeKey: string): string {
  const v = row.cells[scopeKey]
  return v == null ? '—' : numText(v)
}

function totalText(row: MatrixRow): string {
  return `${numText(row.total)}${row.unit ? ' ' + row.unit : ''}`
}
</script>

<style scoped>
.mc-matrix {
  border-top: 1px solid var(--color-border-light, #f1f5f9);
  padding: 12px 16px 16px;
}

.mc-matrix-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--color-text);
}

.mc-matrix-title {
  font-size: 14px;
  font-weight: 700;
}

.mc-matrix-sub {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.mc-matrix-empty {
  padding: 16px;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-muted, #94a3b8);
}

.mc-matrix-scroll {
  overflow: auto;
  max-height: 340px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
}

.mc-matrix-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  white-space: nowrap;
}

.mc-matrix-table th,
.mc-matrix-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--color-border-light, #eef2f7);
  text-align: left;
}

.mc-matrix-table thead th {
  position: sticky;
  top: 0;
  background: var(--color-surface-card, #f8fafc);
  font-weight: 700;
  color: var(--color-text-secondary);
  z-index: 1;
}

.mc-mx-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.mc-mx-col-name {
  position: sticky;
  left: 0;
  background: var(--color-surface-card, #fff);
  z-index: 1;
}

.mc-mx-col-total {
  font-weight: 700;
  color: var(--color-primary-700);
}

.mc-mx-name {
  font-weight: 600;
  color: var(--color-text);
}

.mc-mx-cat {
  display: inline-block;
  margin-right: 6px;
  padding: 0 5px;
  border-radius: 4px;
  font-size: 11px;
  color: #fff;
  background: var(--color-text-muted, #94a3b8);
}

.mc-mx-cat-filling { background: var(--color-primary-600, #2563eb); }
.mc-mx-cat-fabric { background: var(--color-success-600, #16a34a); }
.mc-mx-cat-accessory { background: var(--color-warning-600, #d97706); }

.mc-mx-split-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 0 5px;
  border-radius: 4px;
  font-size: 10px;
  color: var(--color-danger-600, #dc2626);
  border: 1px solid var(--color-danger-200, #fecaca);
}

.mc-mx-split-row td {
  background: var(--color-warning-50, #fffbeb);
}
</style>

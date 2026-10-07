<template>
  <UiDialog v-model:open="openModel" :title="`该组包含 ${records.length} 条记录，请选择要${actionLabel}的一条`" max-width-class="max-w-[640px]">
    <UiDataTable
      :data="records"
      :columns="columns"
      :paginator="false"
      row-key="id"
    >
      <template #column-body-status="{ row }">
        {{ (row as Record<string, unknown>).status ?? '' }}
      </template>
      <template #column-body-note="{ row }">
        {{ noteText(row as Record<string, unknown>) }}
      </template>
      <template #column-body-actions="{ row }">
        <div class="rp-action-group">
          <button
            v-if="action === 'edit'"
            class="rp-btn-icon rp-btn-edit"
            :aria-label="`${actionLabel} ${cellNo(row as Record<string, unknown>)}`"
            @click="emit('pick', row as Record<string, unknown>)"
          >
            <FontAwesomeIcon icon="pen-to-square" aria-hidden="true" />
          </button>
          <button
            v-else
            class="rp-btn-icon rp-btn-danger"
            :aria-label="`${actionLabel} ${cellNo(row as Record<string, unknown>)}`"
            @click="emit('pick', row as Record<string, unknown>)"
          >
            <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
          </button>
        </div>
      </template>
    </UiDataTable>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * ReportRecordPicker.vue — 聚合行还原出多条记录时的选择弹窗（报表页）。
 *
 * 只做「选哪条」：行内按钮渲染与触发动作一致的那个（编辑弹窗只给笔、
 * 删除弹窗只给垃圾桶），选中后 emit pick(record)，写操作仍由父级走
 * useReportRowActions 的单条流程。
 *
 * 列取值键按维度可配（noKey/dateKey/noteKey）：订单/备货用 order_no/order_date，
 * 备注在 items 内（noteKey 缺省 → recordNote）；出货/抵扣用 stockout_no/stockout_date/note；
 * 退货用 return_no/return_date/note。
 */
import { computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { recordNote, type ReportAction } from '../composables/useReportRowActions'

const props = withDefaults(defineProps<{
  open: boolean
  records: object[]
  action: ReportAction
  /** 单号列取值键（缺省 order_no） */
  noKey?: string
  /** 时间列取值键（缺省 order_date） */
  dateKey?: string
  /** 备注列取值键；缺省则走 recordNote（订单/备货备注在 items 内） */
  noteKey?: string
}>(), {
  noKey: 'order_no',
  dateKey: 'order_date',
  noteKey: undefined,
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  pick: [record: Record<string, unknown>]
}>()

const openModel = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})

const actionLabel = computed(() => (props.action === 'edit' ? '编辑' : '删除'))

const columns = computed<TableColumn[]>(() => [
  { field: props.noKey, header: '单号', align: 'center' },
  { field: props.dateKey, header: '时间', align: 'center' },
  { field: 'quantity', header: '数量', align: 'center' },
  { field: 'status', header: '状态', align: 'center' },
  { field: 'note', header: '备注', align: 'left' },
  { field: 'actions', header: '操作', align: 'center' },
])

function cellNo(row: Record<string, unknown>): string {
  return String(row[props.noKey] ?? '')
}

function noteText(row: Record<string, unknown>): string {
  return props.noteKey ? String(row[props.noteKey] ?? '') : recordNote(row)
}
</script>

<style scoped>
/* 与 ReportTable 的操作列同一套（36×36 / FontAwesome / 同配色，hover 只换背景不带位移） */
.rp-action-group {
  display: flex;
  gap: 4px;
  justify-content: center;
}
.rp-btn-icon {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s ease;
}
.rp-btn-edit {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.rp-btn-edit:hover {
  background: var(--color-warning-100);
}
.rp-btn-danger {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
}
.rp-btn-danger:hover {
  background: var(--color-danger-100);
}
</style>

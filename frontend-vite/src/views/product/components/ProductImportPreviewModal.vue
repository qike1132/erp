<template>
  <UiDialog
    v-model:open="openModel"
    title="产品导入预览"
    max-width-class="max-w-[1000px]"
  >
    <p class="pi-sub">
      文件「{{ result?.filename || '未命名' }}」· 解析出 {{ result?.row_count ?? 0 }} 行
      <span class="pi-badge">尚未写入数据库</span>
    </p>

    <div class="pi-sum">
      <span class="chip chip-new">新增 <b>{{ summary.create }}</b></span>
      <span class="chip chip-fill">补全 <b>{{ summary.backfill }}</b></span>
      <span class="chip chip-skip">跳过 <b>{{ summary.skip }}</b></span>
      <span class="chip chip-err">错误 <b>{{ summary.error }}</b></span>
    </div>

    <!-- 客户未匹配 / 文件内重复这类提示必须单独可见，不能只藏在行里 -->
    <ul v-if="warnings.length" class="pi-warn">
      <li v-for="(w, i) in warnings" :key="i">{{ w }}</li>
    </ul>

    <table class="pi-table">
      <thead>
        <tr>
          <th class="c-row">行</th>
          <th class="c-name">产品名称</th>
          <th class="c-cust">客户</th>
          <th class="c-price">价格</th>
          <th class="c-factory">工厂</th>
          <th class="c-action">动作</th>
          <th>说明 / 将改动</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.row_no" :class="`row-${row.action}`">
          <td class="c-row">{{ row.row_no }}</td>
          <td class="c-name">{{ row.name || '（空）' }}</td>
          <td class="c-cust">
            <span v-if="!row.customer_name" class="cust-none">—</span>
            <span v-else :class="row.customer_matched ? '' : 'cust-missing'">{{ row.customer_name }}</span>
          </td>
          <td class="c-price">{{ row.price || '—' }}</td>
          <td class="c-factory">{{ row.factory || '—' }}</td>
          <td class="c-action"><span :class="`pill pill-${row.action}`">{{ actionText(row.action) }}</span></td>
          <td class="c-note">
            <span v-if="row.changes?.length" class="delta">{{ row.changes.join(' · ') }}</span>
            <span v-else-if="row.messages?.length" class="note-msg">{{ row.messages.join('；') }}</span>
            <span v-else class="note-empty">{{ actionText(row.action) }}</span>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="pi-legend">
      <span><i class="sw sw-new" />新增：库中不存在，将新建</span>
      <span><i class="sw sw-fill" />补全：已存在，只填空白字段（不覆盖人工改过的值）</span>
      <span><i class="sw sw-skip" />跳过：重复或无改动</span>
      <span><i class="sw sw-err" />错误：本行无法导入</span>
    </div>

    <template #footer>
      <span class="pi-foot-note">{{ footNote }}</span>
      <UiButton variant="outline" @click="openModel = false">取消</UiButton>
      <UiButton variant="primary" :disabled="!canConfirm" @click="emit('confirm')">
        {{ importing ? '导入中…' : '确认导入' }}
      </UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * ProductImportPreviewModal — 产品批量导入的预览确认弹窗
 *
 * 「只看不改」：预览只用于核对，发现不对就改 Excel 重传。确认后由父组件把**同一份
 * 文件**重发给 `POST /batch/batch-import`（真正的写入在那里发生）。
 */
import { computed } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import type { ProductImportPreviewResult, ProductImportPreviewRow } from '@/types/api'

const props = defineProps<{
  /** 预览结果；未预览时为 null */
  result: ProductImportPreviewResult | null
  /** 确认导入进行中（按钮转「导入中…」并禁用） */
  importing?: boolean
}>()

const emit = defineEmits<{ confirm: [] }>()

const openModel = defineModel<boolean>('open', { required: true })

const ACTION_TEXT: Record<string, string> = {
  create: '新增', backfill: '补全', skip: '跳过', error: '错误',
}

function actionText(action: string): string {
  return ACTION_TEXT[action] ?? action
}

const rows = computed<ProductImportPreviewRow[]>(() => props.result?.rows ?? [])

const summary = computed(() => ({
  create: props.result?.summary?.create ?? 0,
  backfill: props.result?.summary?.backfill ?? 0,
  skip: props.result?.summary?.skip ?? 0,
  error: props.result?.summary?.error ?? 0,
}))

/** 行级提示汇总（客户未匹配、文件内重复等），按行号顺序去重展示 */
const warnings = computed(() =>
  rows.value.flatMap((r) => r.messages ?? []).filter((m, i, arr) => arr.indexOf(m) === i),
)

const writable = computed(() => summary.value.create + summary.value.backfill)

/** 没有任何可导入的行时不允许确认（避免「点进去什么也没发生」） */
const canConfirm = computed(() => writable.value > 0 && !props.importing)

const footNote = computed(() => {
  if (!rows.value.length) return '没有解析到任何数据行'
  if (!writable.value) return '没有可导入的行，请检查文件后重传'
  const skipped = summary.value.skip + summary.value.error
  return `确认后将写入 ${writable.value} 条（新增 ${summary.value.create} + 补全 ${summary.value.backfill}）`
    + (skipped ? `，跳过 ${skipped} 条` : '')
})
</script>

<style scoped>
.pi-sub {
  margin: 0 0 10px;
  font-size: 12.5px;
  color: var(--color-text-muted);
}
.pi-badge {
  margin-left: 8px;
  font-size: 10.5px;
  font-weight: 700;
  color: var(--color-ocean-text, #02669e);
  background: var(--color-ocean-light, #d4f1f4);
  padding: 2px 8px;
  border-radius: 999px;
}

.pi-sum {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 13px;
  border-radius: 10px;
  font-size: 12.5px;
  font-weight: 600;
}
.chip b { font-size: 15px; font-weight: 800; }
.chip-new { background: var(--color-primary-50); color: var(--color-primary-700); }
.chip-fill { background: var(--color-success-50); color: var(--color-success-700); }
.chip-skip { background: var(--color-slate-100); color: var(--color-text-secondary); }
.chip-err { background: var(--color-danger-50); color: var(--color-danger-700); }

.pi-warn {
  margin: 0 0 12px;
  padding: 9px 13px 9px 30px;
  background: var(--color-warning-50);
  border-radius: 10px;
  font-size: 12px;
  color: var(--color-warning-700);
  list-style: disc;
}
.pi-warn li { margin: 2px 0; }

.pi-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.pi-table th {
  text-align: left;
  font-weight: 600;
  font-size: 11.5px;
  padding: 9px;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-slate-50);
}
.pi-table td { padding: 9px; border-bottom: 1px solid var(--color-border-light); vertical-align: top; }
.c-row { width: 44px; color: var(--color-text-muted); }
.c-name { width: 150px; font-weight: 600; color: var(--color-text); }
.c-cust { width: 120px; }
.c-price { width: 78px; }
.c-factory { width: 72px; }
.c-action { width: 74px; }
.c-note { color: var(--color-text-muted); }

.cust-missing { color: var(--color-danger-600); font-weight: 600; }
.cust-none { color: var(--color-text-placeholder, #94a3b8); }

.pill {
  display: inline-block;
  font-size: 10.5px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}
.pill-create { background: var(--color-primary-50); color: var(--color-primary-700); }
.pill-backfill { background: var(--color-success-50); color: var(--color-success-700); }
.pill-skip { background: var(--color-slate-200); color: var(--color-text-secondary); }
.pill-error { background: var(--color-danger-50); color: var(--color-danger-700); }

.row-skip td { background: var(--color-slate-50); }
.row-error td { background: #fffafa; }
.delta { color: var(--color-success-700); font-weight: 600; }
.note-msg { color: var(--color-warning-700); }
.note-empty { color: var(--color-text-muted); }

.pi-legend {
  margin-top: 14px;
  font-size: 11.5px;
  color: var(--color-text-muted);
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.pi-legend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.sw-new { background: var(--color-primary-100, #d6e4ff); }
.sw-fill { background: var(--color-success-100, #d0f3df); }
.sw-skip { background: var(--color-slate-200); }
.sw-err { background: var(--color-danger-100, #fbd0d0); }

.pi-foot-note { margin-right: auto; font-size: 11.5px; color: var(--color-text-muted); }
</style>

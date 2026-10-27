<template>
  <div class="osp-inventory">
    <div class="osp-card-main">
      <div v-if="partial !== 'none'" class="osp-partial" role="status">
        <FontAwesomeIcon icon="triangle-exclamation" aria-hidden="true" />
        <span>{{ partialInfo.banner }}</span>
        <button v-if="partialInfo.retryable" class="osp-retry-btn" aria-label="重试加载完整列表" @click="manualRetry">
          重试
        </button>
      </div>
      <!-- 错误态判据用 presets（不含搜索选中产品）：pendingProducts 非空时拉取失败不得被「未配置」表格掩盖（OCR-4 M4） -->
      <div v-if="isError && presets.length === 0" class="osp-empty osp-error">
        <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />
        <span>工序预设加载失败</span>
        <button class="osp-retry-btn" aria-label="重试" @click="manualRetry">重试</button>
      </div>
      <div v-else-if="isFetching && productCards.length === 0" class="osp-empty">
        <UiSpinner />
      </div>
      <div v-else-if="productCards.length === 0" class="osp-empty">
        <FontAwesomeIcon icon="box-open" aria-hidden="true" />
        <span>暂无产品</span>
        <span class="osp-empty-sub">使用上方搜索框选择产品，即可配置其外发工序</span>
      </div>
      <template v-else>
        <div class="osp-table-wrap">
          <table class="osp-table">
            <thead>
              <tr>
                <th class="osp-th-left" style="width: 220px;">产品名称</th>
                <th class="osp-th-center" style="width: 130px;">产品条码</th>
                <th class="osp-th-center" style="width: 80px;">工厂</th>
                <th class="osp-th-center" style="width: 90px;">工序数</th>
                <th class="osp-th-left">工序</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="card in productCards" :key="card.product_id">
                <td class="osp-td-name" style="width: 220px;" :title="card.product_name">{{ card.product_name || '未命名产品' }}</td>
                <td class="osp-td-center osp-td-mono" style="width: 130px;">{{ card.product_barcode || '-' }}</td>
                <td class="osp-td-center" style="width: 80px;">
                  <span v-if="card.factory" class="osp-factory-chip">{{ card.factory }}</span>
                  <span v-else>-</span>
                </td>
                <td class="osp-td-center" style="width: 90px;"><strong class="osp-count-num">{{ card.processes.length }}</strong></td>
                <td class="osp-td-left osp-proc-cell">
                  <div class="osp-proc-inner">
                    <div class="osp-proc-chips">
                      <div
                        v-for="pt in visibleProcesses(card)"
                        :key="pt.id"
                        :class="['osp-proc-chip', pt.is_active ? 'osp-proc-on' : 'osp-proc-off']"
                        :title="`${pt.process_type}${pt.remark ? ' · ' + pt.remark : ''}（顺序 ${pt.sort_order}）`"
                      >
                        <span class="osp-proc-name">{{ pt.process_type }}</span>
                        <button
                          v-if="canManage"
                          class="osp-chip-del"
                          :aria-label="`删除工序 ${pt.process_type}`"
                          @click.stop="handleDelete(pt)"
                        >
                          <FontAwesomeIcon icon="times" aria-hidden="true" />
                        </button>
                      </div>
                      <span v-if="card.processes.length === 0" class="osp-no-proc">未配置</span>
                      <button
                        v-else-if="card.processes.length > INITIAL_VISIBLE_PROCESSES"
                        class="osp-chip-more"
                        :aria-label="expandedProducts.has(card.product_id) ? '收起部分工序' : `展开其余 ${card.processes.length - INITIAL_VISIBLE_PROCESSES} 道工序`"
                        @click="toggleProcesses(card.product_id)"
                      >
                        {{ expandedProducts.has(card.product_id) ? '收起' : `+${card.processes.length - INITIAL_VISIBLE_PROCESSES} 道工序` }}
                      </button>
                    </div>
                    <div v-if="canManage" class="osp-add-bar">
                      <button class="osp-add-btn" :disabled="saving" aria-label="添加工序" @click="openAddDialog(card)">
                        <FontAwesomeIcon icon="plus" aria-hidden="true" /> 添加工序
                      </button>
                    </div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>

    <OutsourceAddProcessDialog
      v-model:open="addOpen"
      v-model:target="addTarget"
      :product-cards="productCards"
      :refresh="refreshAfterAdd"
      @remove-pending="emit('removePending', $event)"
    />

    <UiConfirmDialog
      :open="confirmDialog.open"
      :text="confirmDialog.text"
      :sub="confirmDialog.sub"
      :type="confirmDialog.type"
      @confirm="confirmDialog.onConfirm"
      @cancel="confirmDialog.onCancel"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { outsourceApi } from '@/api'
import type { OutsourceProcessType } from '@/api/outsource'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import OutsourceAddProcessDialog from './OutsourceAddProcessDialog.vue'
import { useApiMutation } from '@/composables/useApiMutation'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useAuthStore } from '@/stores/auth'
import { PARTIAL_META, useOutsourcePresetTypes } from '../composables/useOutsourcePresetTypes'

const props = defineProps<{
  pendingProducts: { product_id: number; product_name: string; product_barcode: string | null; factory: string | null }[]
}>()

const emit = defineEmits<{
  removePending: [productId: number]
}>()

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('outsource_manage'))

const {
  presets,
  partial,
  isError,
  isFetching,
  refetchAfterMutation,
  manualRetry,
} = useOutsourcePresetTypes()

const partialInfo = computed(() => PARTIAL_META[partial.value] ?? PARTIAL_META.none)

/** 单产品首屏最多渲染的工序 chip；其余需用户显式展开，避免万级 DOM 卡死 */
const INITIAL_VISIBLE_PROCESSES = 50
const expandedProducts = ref<Set<number>>(new Set())

function visibleProcesses(card: ProductCard): OutsourceProcessType[] {
  if (expandedProducts.value.has(card.product_id)) return card.processes
  return card.processes.slice(0, INITIAL_VISIBLE_PROCESSES)
}

function toggleProcesses(productId: number): void {
  const next = new Set(expandedProducts.value)
  if (next.has(productId)) next.delete(productId)
  else next.add(productId)
  expandedProducts.value = next
}

interface ProductCard {
  product_id: number
  product_name: string
  product_barcode: string | null
  factory: string | null
  processes: OutsourceProcessType[]
}

const byProduct = computed<Map<number, OutsourceProcessType[]>>(() => {
  const map = new Map<number, OutsourceProcessType[]>()
  for (const pt of presets.value) {
    if (!map.has(pt.product_id)) map.set(pt.product_id, [])
    map.get(pt.product_id)!.push(pt)
  }
  for (const list of map.values()) {
    list.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.id - b.id)
  }
  return map
})

const productCards = computed<ProductCard[]>(() => {
  const seen = new Set<number>()
  const cards: ProductCard[] = []
  for (const [pid, list] of byProduct.value) {
    const first = list[0]
    cards.push({
      product_id: pid,
      product_name: first?.product_name || '',
      product_barcode: first?.product_barcode || null,
      factory: first?.factory || null,
      processes: list,
    })
    seen.add(pid)
  }
  for (const p of props.pendingProducts) {
    if (!seen.has(p.product_id)) {
      cards.push({
        product_id: p.product_id,
        product_name: p.product_name,
        product_barcode: p.product_barcode,
        factory: p.factory ?? null,
        processes: [],
      })
      seen.add(p.product_id)
    }
  }
  return cards.sort((a, b) => a.product_name.localeCompare(b.product_name, 'zh'))
})

const addOpen = ref(false)
const addTarget = ref<ProductCard | null>(null)
const saving = ref(false)

function openAddDialog(card: ProductCard) {
  addTarget.value = card
  addOpen.value = true
}

async function refreshAfterAdd() {
  saving.value = true
  try {
    await refetchAfterMutation()
  } finally {
    saving.value = false
  }
}

const deleteMutation = useApiMutation((id: number) => outsourceApi.deleteProcessType(id), {
  successMsg: '工序已删除',
  errorMsg: '删除失败',
  onSuccess: async () => {
    await refetchAfterMutation()
  },
})

async function handleDelete(pt: OutsourceProcessType) {
  const ok = await confirmDialog.confirm(`确认删除「${pt.process_type}」工序？`, '删除后该产品的外发工序配置将同步更新。')
  if (!ok) return
  await deleteMutation.run(pt.id)
}

/** 删除工序的统一确认框（走 UiConfirmDialog，支持回车确认/Esc 取消） */
const confirmDialog = useConfirmDialog()
</script>

<style scoped>
/* 单行排版：文件贴 400 行门禁，规则不变 */
.osp-inventory { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.osp-card-main { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.osp-table-wrap { flex: 1; min-height: 0; overflow-y: auto; scrollbar-gutter: stable; }
.osp-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 13px;
}
.osp-table thead {
  background: var(--color-surface, #f8fafc);
  position: sticky;
  top: 0;
  z-index: 1;
}
.osp-table thead th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-right: 1px solid #d8dce2;
  border-bottom: 2px solid #b8bec6;
  color: var(--color-text-secondary);
  text-align: center;
  white-space: nowrap;
}
.osp-table thead th:last-child { border-right: none; }
.osp-th-left { text-align: left !important; }
.osp-th-center { text-align: center !important; }
.osp-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-right: 1px solid #d8dce2;
  border-bottom: 1px solid #d8dce2;
  text-align: center;
  vertical-align: middle;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.osp-table tbody td:last-child { border-right: none; }
.osp-table tbody tr:hover { background: var(--color-primary-50); }
.osp-td-left { text-align: left !important; }
.osp-td-center { text-align: center !important; }
.osp-td-name { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 0; }
.osp-td-mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; color: var(--color-text-secondary); }
.osp-factory-chip {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-primary-600);
  background: var(--color-primary-50);
  border: 1px solid var(--color-primary-200);
  border-radius: 6px;
  padding: 1px 8px;
}
.osp-count-num { color: var(--color-primary-600); font-size: 15px; }

.osp-proc-cell { vertical-align: top; }
.osp-proc-inner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 0;
  flex-wrap: wrap;
}
.osp-proc-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.osp-proc-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border-radius: 9px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.osp-proc-chip:hover { transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,0.08); }
.osp-proc-on { background: var(--color-primary-50); color: var(--color-primary-700); border: 1px solid var(--color-primary-200); }
.osp-proc-off { background: #f1f5f9; color: var(--color-text-muted); border: 1px solid #e2e8f0; }
.osp-proc-name { white-space: nowrap; }
.osp-chip-del {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 11px;
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  line-height: 1;
}
.osp-chip-del:hover { color: var(--color-danger-500); background: rgba(239, 68, 68, 0.1); }
.osp-no-proc { font-size: 12.5px; color: var(--color-text-muted); }

.osp-add-bar { flex-shrink: 0; }
.osp-add-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  border: 1.5px dashed var(--color-primary-300);
  border-radius: 9px;
  background: white;
  color: var(--color-primary-600);
  font-size: 12.5px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
  font-family: inherit;
  white-space: nowrap;
}
.osp-add-btn:hover { background: var(--color-primary-50); border-color: var(--color-primary-400); transform: translateY(-1px); }
.osp-add-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.osp-partial { display: flex; align-items: center; gap: 8px; padding: 8px 14px; font-size: 12.5px;
  border-bottom: 1px solid var(--color-warning-200, #fde68a);
  background: var(--color-warning-50, #fffbeb); color: var(--color-warning-800, #92400e); }
.osp-partial span { flex: 1; min-width: 0; }
.osp-partial .osp-retry-btn { margin-top: 0; padding: 3px 12px; }
.osp-chip-more { border: 1px dashed var(--color-primary-300); border-radius: 7px;
  background: transparent; color: var(--color-primary-700); font-size: 12px; padding: 4px 9px; cursor: pointer; }
.osp-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.osp-empty span { font-size: 14px; }
.osp-empty-sub { font-size: 12px; opacity: 0.85; }
.osp-error svg { color: var(--color-danger-500); }
.osp-retry-btn { margin-top: 6px; padding: 6px 18px; border: 1px solid var(--color-border, #cbd5e1); border-radius: 8px; background: white; color: var(--color-text); font-size: 13px; cursor: pointer; }
.osp-retry-btn:hover { border-color: var(--color-primary-400); color: var(--color-primary-600); }
</style>

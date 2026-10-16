<template>
  <div class="osp-inventory">
    <div class="osp-card-main">
      <div v-if="isLoading && productCards.length === 0" class="osp-empty">
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
                        v-for="pt in card.processes"
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
import { useQuery } from '@tanstack/vue-query'
import { outsourceApi } from '@/api'
import type { OutsourceProcessType } from '@/api/outsource'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import OutsourceAddProcessDialog from './OutsourceAddProcessDialog.vue'
import { useApiMutation } from '@/composables/useApiMutation'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{
  pendingProducts: { product_id: number; product_name: string; product_barcode: string | null; factory: string | null }[]
}>()

const emit = defineEmits<{
  removePending: [productId: number]
}>()

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('outsource_manage'))

const {
  data: listData,
  isLoading,
  refetch,
} = useQuery({
  queryKey: ['outsource-process-types'],
  queryFn: () => outsourceApi.processTypes({ per_page: 500 }),
  staleTime: 15_000,
})

const presets = computed<OutsourceProcessType[]>(() => listData.value?.data ?? [])

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
    await refetch()
  } finally {
    saving.value = false
  }
}

const deleteMutation = useApiMutation((id: number) => outsourceApi.deleteProcessType(id), {
  successMsg: '工序已删除',
  errorMsg: '删除失败',
  onSuccess: async () => {
    await refetch()
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
.osp-inventory {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.osp-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.osp-table-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-gutter: stable;
}
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
</style>

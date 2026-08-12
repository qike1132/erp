<template>
  <div class="osp-inventory">
    <!-- 工具条：产品搜索 -->
    <div class="osp-toolbar">
      <div class="osp-toolbar-left">
        <div class="osp-search-field">
          <UiAutocomplete
            v-model="searchText"
            :searchFn="searchProducts"
            placeholder="搜索产品名称/条码，选中后为其配置工序"
            appendTo="self"
            suppress-after-select
            :search-delay-ms="500"
            :show-loading="false"
            @select="onPickProduct($event as ProductSuggestion)"
          >
            <template #option="{ item }">
              <div class="osp-ac-option">
                <span class="osp-ac-name">{{ item.name }}</span>
                <span v-if="item.barcode" class="osp-ac-barcode">{{ item.barcode }}</span>
              </div>
            </template>
          </UiAutocomplete>
        </div>
        <button class="osp-action-btn" @click="searchText = ''; refetch()" aria-label="重置">
          <FontAwesomeIcon icon="redo" aria-hidden="true" />
        </button>
        <span v-if="productCards.length > 0" class="osp-total-hint">共 {{ productCards.length }} 个产品</span>
      </div>
    </div>

    <!-- 产品表格：与订单列表同款样式 -->
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
                <!-- 工序列：chips 横向展示 + 添加工序按钮 -->
                <td class="osp-td-left osp-proc-cell">
                  <div class="osp-proc-inner">
                    <div class="osp-proc-chips">
                      <div
                        v-for="pt in card.processes"
                        :key="pt.id"
                        :class="['osp-proc-chip', pt.is_active ? 'osp-proc-on' : 'osp-proc-off']"
                        :title="`${pt.process_type}${pt.remark ? ' · ' + pt.remark : ''}（顺序 ${pt.sort_order}）`"
                        @click="canManage && openEdit(pt)"
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
                    <!-- 添加工序按钮 -->
                    <div v-if="canManage" class="osp-add-bar">
                      <button class="osp-add-btn" :disabled="saving" @click="openAddDialog(card)">
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

    <!-- 添加工序弹窗：常用工序标签一键添加 -->
    <UiDialog v-model:open="addOpen" :title="`为「${addTarget?.product_name || ''}」添加工序`" max-width-class="max-w-[560px]">
      <div class="osp-form">
        <div class="osp-form-row">
          <label class="osp-form-label">常用工序（点击即添加）</label>
          <div class="osp-quick-tags">
            <button
              v-for="tag in COMMON_PROCESSES"
              :key="tag"
              type="button"
              class="osp-quick-tag"
              :class="{ 'osp-quick-tag--added': isAdded(tag), 'osp-quick-tag--disabled': isAdded(tag) }"
              :disabled="isAdded(tag) || saving"
              @click="quickAdd(tag)"
            >
              <FontAwesomeIcon v-if="isAdded(tag)" icon="check" aria-hidden="true" />
              {{ tag }}
            </button>
          </div>
        </div>
        <div class="osp-form-row">
          <label class="osp-form-label">或输入自定义工序名称</label>
          <div class="osp-add-row">
            <input
              v-model="addInput"
              class="osp-text-input"
              placeholder="输入工序名称，多个用逗号分隔"
              maxlength="200"
              @keyup.enter="handleAdd()"
            />
            <UiButton variant="primary" :disabled="saving" @click="handleAdd()">
              {{ saving ? '添加中…' : '添加' }}
            </UiButton>
          </div>
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" @click="addOpen = false">关闭</UiButton>
      </template>
    </UiDialog>

    <!-- 编辑工序弹窗 -->
    <UiDialog v-model:open="editOpen" title="编辑工序" max-width-class="max-w-[480px]">
      <div class="osp-form">
        <div class="osp-form-row">
          <label class="osp-form-label">工序名称<span class="osp-req">*</span></label>
          <input v-model="editForm.processType" class="osp-text-input" maxlength="50" placeholder="输入工序名称" />
        </div>
        <div class="osp-form-row">
          <label class="osp-form-label">工序顺序</label>
          <UiInputNumber v-model="editForm.sortOrder" :min="0" :max="9999" />
        </div>
        <div class="osp-form-row">
          <label class="osp-form-label">启用</label>
          <UiSwitch v-model="editForm.isActive" />
        </div>
        <div class="osp-form-row">
          <label class="osp-form-label">备注</label>
          <input v-model="editForm.remark" class="osp-text-input" placeholder="选填" maxlength="200" />
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" @click="editOpen = false">取消</UiButton>
        <UiButton variant="primary" :disabled="saving" @click="handleEditSave">
          {{ saving ? '保存中…' : '保存' }}
        </UiButton>
      </template>
    </UiDialog>
  </div>
</template>

<script setup lang="ts">
/**
 * OutsourcePresetTab.vue — SKU 外发工序预设管理
 *
 * 布局与订单列表一致（表格）：每行一个产品（名称/条码/工厂/工序数），
 * 最后一列为工序——chips 横向展示已配置工序 + 「添加工序」按钮，
 * 点击按钮弹出常用工序标签面板，点标签即添加；也支持输入自定义名称
 * （逗号分隔一次添加多道）。工序 chip 点击可编辑、× 删除。
 * 预设是「返单自动带出工序」的数据源。管理操作按 outsource_manage 权限控制。
 */
import { computed, reactive, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { outsourceApi, productApi } from '@/api'
import type { OutsourceProcessType } from '@/api/outsource'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import UiInputNumber from '@/components/ui/UiInputNumber.vue'
import UiSwitch from '@/components/ui/UiSwitch.vue'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/composables/useToast'

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('outsource_manage'))

/** 常用外发工序标签 */
const COMMON_PROCESSES = ['电绣', '转印', '配件', '裁剪', '缝制', '包装', '绣花', '质检']

// ===== 数据：拉取全部预设，按产品分组 =====
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

/** 产品行：产品信息 + 工序列表 */
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

/** 已搜索选中但尚无预设的产品（保证能直接为其配置） */
const pendingProducts = ref<{ product_id: number; product_name: string; product_barcode: string | null }[]>([])

/** 产品行列表：全部已配置工序的产品 + 搜索选中无工序的产品，按名称排序 */
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
  for (const p of pendingProducts.value) {
    if (!seen.has(p.product_id)) {
      cards.push({
        product_id: p.product_id,
        product_name: p.product_name,
        product_barcode: p.product_barcode,
        factory: null,
        processes: [],
      })
      seen.add(p.product_id)
    }
  }
  return cards.sort((a, b) => a.product_name.localeCompare(b.product_name, 'zh'))
})

// ===== 产品搜索 =====
const searchText = ref('')

type ProductSuggestion = { id: number; name: string; barcode?: string }

async function searchProducts(q: string): Promise<ProductSuggestion[]> {
  if (!q.trim()) return []
  try {
    const res = await productApi.search(q)
    const list = Array.isArray(res) ? res : ((res as unknown as { items?: unknown[] }).items ?? [])
    return (list as Array<Record<string, unknown>>).slice(0, 8).map((p) => ({
      id: Number(p.id),
      name: String(p.name ?? ''),
      barcode: p.barcode ? String(p.barcode) : undefined,
    }))
  } catch {
    return []
  }
}

function onPickProduct(p: ProductSuggestion) {
  if (!byProduct.value.has(p.id)) {
    pendingProducts.value = [
      ...pendingProducts.value.filter((x) => x.product_id !== p.id),
      { product_id: p.id, product_name: p.name, product_barcode: p.barcode || null },
    ]
  }
  searchText.value = ''
  refetch()
}

// ===== 添加工序弹窗：常用标签 + 自定义输入 =====
const addOpen = ref(false)
const addTarget = ref<ProductCard | null>(null)
const addInput = ref('')
const saving = ref(false)

function openAddDialog(card: ProductCard) {
  addTarget.value = card
  addInput.value = ''
  addOpen.value = true
}

/** 判断常用标签是否已为该产品配置（置灰 + 勾选） */
function isAdded(tag: string): boolean {
  if (!addTarget.value) return false
  return addTarget.value.processes.some((p) => p.process_type === tag)
}

/** 点击常用标签：直接为该产品添加该工序 */
async function quickAdd(tag: string) {
  if (!addTarget.value || isAdded(tag)) return
  saving.value = true
  try {
    const res = await outsourceApi.batchCreateProcessTypes(addTarget.value.product_id, [tag])
    toast.success(res.message || `已添加「${tag}」`)
    await refreshAfterAdd()
  } catch (e) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(msg || '添加失败')
  } finally {
    saving.value = false
  }
}

/** 自定义输入：逗号分隔一次添加多道 */
async function handleAdd() {
  if (!addTarget.value) return
  const names = addInput.value
    .split(/[,，\n]/)
    .map((n) => n.trim())
    .filter(Boolean)
  if (names.length === 0) {
    toast.warning('请输入工序名称')
    return
  }
  saving.value = true
  try {
    const res = await outsourceApi.batchCreateProcessTypes(addTarget.value.product_id, names)
    toast.success(res.message || '工序已添加')
    addInput.value = ''
    await refreshAfterAdd()
  } catch (e) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(msg || '添加失败')
  } finally {
    saving.value = false
  }
}

async function refreshAfterAdd() {
  // 该产品已有预设后从 pending 移除，由 byProduct 接管；刷新后同步弹窗目标
  pendingProducts.value = pendingProducts.value.filter((x) => x.product_id !== addTarget.value?.product_id)
  await refetch()
  const refreshed = productCards.value.find((c) => c.product_id === addTarget.value?.product_id)
  if (refreshed) addTarget.value = refreshed
}

// ===== 编辑工序 =====
const editOpen = ref(false)
const editId = ref<number | null>(null)
const editForm = reactive({
  processType: '',
  sortOrder: 0,
  isActive: true,
  remark: '',
})

function openEdit(pt: OutsourceProcessType) {
  editId.value = pt.id
  editForm.processType = pt.process_type
  editForm.sortOrder = pt.sort_order ?? 0
  editForm.isActive = pt.is_active
  editForm.remark = pt.remark || ''
  editOpen.value = true
}

async function handleEditSave() {
  if (!editForm.processType.trim()) {
    toast.warning('请填写工序名称')
    return
  }
  saving.value = true
  try {
    await outsourceApi.updateProcessType(editId.value!, {
      process_type: editForm.processType.trim(),
      sort_order: editForm.sortOrder,
      is_active: editForm.isActive,
      remark: editForm.remark,
    })
    toast.success('工序已更新')
    editOpen.value = false
    refetch()
  } catch (e) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(msg || '保存失败')
  } finally {
    saving.value = false
  }
}

async function handleDelete(pt: OutsourceProcessType) {
  if (!window.confirm(`确认删除「${pt.process_type}」工序？`)) return
  try {
    await outsourceApi.deleteProcessType(pt.id)
    toast.success('工序已删除')
    refetch()
  } catch {
    toast.error('删除失败')
  }
}
</script>

<style scoped>
.osp-inventory {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

/* 工具条 */
.osp-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  flex-shrink: 0;
}
.osp-toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.osp-search-field { width: 360px; max-width: 100%; }
.osp-total-hint { font-size: 12.5px; color: var(--color-text-muted); font-weight: 600; }
.osp-action-btn {
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  font-family: inherit;
  line-height: inherit;
}
.osp-action-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}
.osp-ac-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  align-items: flex-start;
}
.osp-ac-name { color: var(--color-text); font-weight: 500; font-size: 13px; }
.osp-ac-barcode { color: var(--color-text-muted); font-size: 12px; font-family: ui-monospace, Menlo, Consolas, monospace; }

/* 主体（与订单列表同款表格） */
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
.osp-table tbody tr:last-child td { border-bottom: none; }
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

/* 工序列 */
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

/* 添加工序按钮 */
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

/* 常用工序标签 */
.osp-quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 4px 0;
}
.osp-quick-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 16px;
  border-radius: 999px;
  border: 1.5px solid var(--color-primary-300);
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s ease, transform 0.15s ease, opacity 0.15s ease;
  font-family: inherit;
}
.osp-quick-tag:hover:not(:disabled) {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}
.osp-quick-tag--added {
  background: var(--color-success-50);
  border-color: var(--color-success-300);
  color: var(--color-success-700);
}
.osp-quick-tag--disabled { cursor: default; opacity: 0.85; }

.osp-add-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

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

/* 表单 */
.osp-form { display: flex; flex-direction: column; gap: 14px; }
.osp-form-row { display: flex; flex-direction: column; gap: 6px; }
.osp-form-label { font-size: 12.5px; font-weight: 600; color: var(--color-text-secondary); }
.osp-req { color: var(--color-danger-500); margin-left: 2px; }
.osp-text-input {
  width: 100%;
  padding: 8px 12px;
  font-size: 13px;
  color: var(--color-text);
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  box-sizing: border-box;
  font-family: inherit;
}
.osp-text-input:focus {
  outline: none;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}
</style>

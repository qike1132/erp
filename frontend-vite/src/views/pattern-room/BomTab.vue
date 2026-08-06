<template>
  <div class="pr-bom-tab">
    <!-- 筛选栏 -->
    <div class="pr-filters">
      <div class="pr-fg">
        <label>关键字</label>
        <input type="text" v-model="filters.keyword" placeholder="产品名/编号/客户" @keyup.enter="loadBomList(1)" />
      </div>
      <div class="pr-fg">
        <label>状态</label>
        <select v-model="filters.status" @change="loadBomList(1)">
          <option value="">全部</option>
          <option value="draft">草稿</option>
          <option value="sampling">打样中</option>
          <option value="confirmed">已确认</option>
          <option value="archived">已归档</option>
        </select>
      </div>
      <div class="pr-fg">
        <label>版本</label>
        <select v-model="filters.current_version" @change="loadBomList(1)">
          <option value="">全部</option>
          <option v-for="v in ['T1', 'T2', 'T3', 'T4', 'T5']" :key="v" :value="v">{{ v }}</option>
        </select>
      </div>
      <button class="pr-btn pr-btn-ghost" @click="resetFilters">
        <i class="fas fa-redo" /> 重置
      </button>
      <button v-if="canManage" class="pr-btn pr-btn-primary" @click="openCreateDialog">
        <i class="fas fa-plus" /> 新建 BOM
      </button>
    </div>

    <!-- 表格 -->
    <div class="pr-card">
      <div class="pr-card-b pr-card-b--flush">
        <table class="pr-tbl" style="min-width: 980px;">
          <thead>
            <tr>
              <th style="width: 160px;">打样编号</th>
              <th>产品名称</th>
              <th style="width: 140px;">客户</th>
              <th style="width: 90px;">当前版本</th>
              <th style="width: 100px;">状态</th>
              <th style="width: 100px;">创建人</th>
              <th style="width: 150px;">更新时间</th>
              <th style="width: 220px;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="isLoading && !bomList.length">
              <td colspan="8" class="pr-empty"><UiSpinner /></td>
            </tr>
            <tr v-else-if="!bomList.length">
              <td colspan="8" class="pr-empty"><i class="fas fa-inbox" /><span>暂无 BOM 数据</span></td>
            </tr>
            <template v-else>
              <tr v-if="isFetching" class="pr-fetching-row">
                <td colspan="8" class="pr-fetching-bar"><div class="pr-fetching-progress" /></td>
              </tr>
              <tr v-for="row in bomList" :key="row.id" class="pr-bom-row">
                <td class="pr-td-bold">{{ row.bom_no }}</td>
                <td>{{ row.product_name }}</td>
                <td>{{ row.customer_name || '-' }}</td>
                <td>
                  <span class="pr-version-badge">{{ row.current_version }}</span>
                </td>
                <td>
                  <UiStatusBadge :variant="statusVariant(row.status)">{{ row.status_label }}</UiStatusBadge>
                </td>
                <td>{{ row.created_by_name || '-' }}</td>
                <td class="pr-td-small pr-td-muted">{{ row.updated_at }}</td>
                <td>
                  <div class="pr-action-group">
                    <button class="pr-action-btn" title="编辑 BOM" @click="openEditDialog(row)">
                      <i class="fas fa-pen" />
                    </button>
                    <button class="pr-action-btn" title="查看拆分图" @click="$emit('view-breakdown', row.id)">
                      <i class="fas fa-sitemap" />
                    </button>
                    <button class="pr-action-btn" title="版本对比" @click="$emit('view-compare', row.id)">
                      <i class="fas fa-code-compare" />
                    </button>
                    <button class="pr-action-btn pr-action-danger" title="删除" @click="handleDelete(row)">
                      <i class="fas fa-trash" />
                    </button>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
        <UiPagination
          v-if="totalPages > 1"
          :current-page="page"
          :total-pages="totalPages"
          @update:current-page="loadBomList"
        />
      </div>
    </div>

    <!-- 创建/编辑对话框 -->
    <UiDialog
      v-model:open="dialogOpen"
      :title="dialogMode === 'create' ? '新建 BOM' : `编辑 BOM - ${form.bom_no || ''}`"
      max-width-class="max-w-[1100px]"
    >
      <template #title-icon>
        <i class="fas fa-clipboard-list" style="color: var(--color-primary-500);"></i>
      </template>
      <div class="pr-dialog-body">
        <!-- 元信息表单 -->
        <div class="pr-form-grid">
          <div class="pr-form-field">
            <label>产品名称 <span class="pr-req">*</span></label>
            <input v-model="form.product_name" type="text" placeholder="请输入产品名称" />
          </div>
          <div class="pr-form-field">
            <label>客户名称</label>
            <input v-model="form.customer_name" type="text" placeholder="请输入客户名称" />
          </div>
          <div class="pr-form-field" v-if="dialogMode === 'edit'">
            <label>状态</label>
            <select v-model="form.status">
              <option value="draft">草稿</option>
              <option value="sampling">打样中</option>
              <option value="confirmed">已确认</option>
              <option value="archived">已归档</option>
            </select>
          </div>
          <div class="pr-form-field pr-form-field--full">
            <label>备注</label>
            <textarea v-model="form.remark" rows="2" placeholder="可选"></textarea>
          </div>
        </div>

        <!-- BOM 树形编辑器 -->
        <div class="pr-tree-section">
          <div class="pr-tree-header">
            <h4><i class="fas fa-list-tree" /> BOM 物料结构</h4>
            <div class="pr-tree-actions">
              <button class="pr-btn pr-btn-sm pr-btn-ghost" @click="expandAll(true)">
                <i class="fas fa-expand" /> 全部展开
              </button>
              <button class="pr-btn pr-btn-sm pr-btn-ghost" @click="expandAll(false)">
                <i class="fas fa-compress" /> 全部收起
              </button>
              <button class="pr-btn pr-btn-sm pr-btn-primary" @click="addRootItem">
                <i class="fas fa-plus" /> 添加根节点
              </button>
            </div>
          </div>

          <div class="pr-tree-container">
            <div v-if="!form.items.length" class="pr-tree-empty">
              <i class="fas fa-inbox" />
              <span>暂无物料节点，点击"添加根节点"开始</span>
            </div>
            <BomTreeNode
              v-for="(item, idx) in form.items"
              :key="idx"
              :item="item"
              :depth="0"
              @add-child="onAddChild"
              @remove="onRemove"
              @move="onMove"
            />
          </div>
        </div>
      </div>
      <template #footer>
        <UiButton variant="outline" @click="dialogOpen = false">取消</UiButton>
        <UiButton v-if="dialogMode === 'create'" variant="primary" :disabled="submitting" @click="handleCreate">
          <i v-if="submitting" class="fas fa-spinner fa-spin" /> 创建
        </UiButton>
        <template v-else>
          <UiButton variant="success" :disabled="submitting" @click="handleSaveMeta">
            <i v-if="submitting" class="fas fa-spinner fa-spin" /> 保存元信息
          </UiButton>
          <UiButton variant="primary" :disabled="submitting" @click="handleSaveItems">
            <i v-if="submitting" class="fas fa-spinner fa-spin" /> 保存 BOM 树
          </UiButton>
        </template>
      </template>
    </UiDialog>

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
/**
 * BomTab.vue — BOM 管理 Tab
 *
 * 职责：
 * - BOM 列表查询（分页 + 筛选）
 * - 新建/编辑 BOM（含树形编辑器）
 * - 删除 BOM
 * - 触发 view-breakdown / view-compare 事件跳转其他 Tab
 */
import { ref, reactive, computed, onMounted } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { keepPreviousData } from '@tanstack/vue-query'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiStatusBadge from '@/components/ui/UiStatusBadge.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { showToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { patternRoomApi } from '@/api/patternRoom'
import type { PatternRoomBom, BomItem } from '@/api/patternRoom'
import BomTreeNode from './components/BomTreeNode.vue'

const emit = defineEmits<{
  'count-update': [count: number]
  'view-breakdown': [bomId: number]
  'view-compare': [bomId: number]
}>()

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('product_manage'))
const confirmDialog = useConfirmDialog()

// 筛选与分页
const filters = reactive({
  keyword: '',
  status: '',
  current_version: '',
})
const page = ref(1)
const perPage = 20
const totalPages = ref(1)
const bomCount = ref(0)

// 列表查询
const {
  data: listData,
  isLoading,
  isFetching,
  refetch,
} = useQuery({
  queryKey: ['pattern-room-bom-list', page, filters],
  queryFn: async () => {
    const params: Record<string, unknown> = { page: page.value, per_page: perPage }
    if (filters.keyword) params.keyword = filters.keyword
    if (filters.status) params.status = filters.status
    if (filters.current_version) params.current_version = filters.current_version
    const res = await patternRoomApi.listBom(params)
    totalPages.value = res.pages ?? 1
    bomCount.value = res.total ?? 0
    emit('count-update', bomCount.value)
    return res
  },
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

const bomList = computed<PatternRoomBom[]>(() => listData.value?.items ?? [])

async function loadBomList(p?: number) {
  if (typeof p === 'number') page.value = p
  await refetch()
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.current_version = ''
  page.value = 1
  refetch()
}

function statusVariant(status: string): 'default' | 'primary' | 'success' | 'warning' | 'info' {
  const map: Record<string, 'default' | 'primary' | 'success' | 'warning' | 'info'> = {
    draft: 'default',
    sampling: 'info',
    confirmed: 'success',
    archived: 'warning',
  }
  return map[status] || 'default'
}

// ==================== 创建/编辑对话框 ====================

const dialogOpen = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const submitting = ref(false)
const editingBomId = ref<number | null>(null)

const form = reactive<{
  bom_no: string
  product_name: string
  customer_name: string
  status: string
  remark: string
  items: BomItem[]
}>({
  bom_no: '',
  product_name: '',
  customer_name: '',
  status: 'draft',
  remark: '',
  items: [],
})

function openCreateDialog() {
  dialogMode.value = 'create'
  editingBomId.value = null
  form.bom_no = ''
  form.product_name = ''
  form.customer_name = ''
  form.status = 'draft'
  form.remark = ''
  form.items = []
  dialogOpen.value = true
}

async function openEditDialog(row: PatternRoomBom) {
  dialogMode.value = 'edit'
  editingBomId.value = row.id
  form.bom_no = row.bom_no
  form.product_name = row.product_name
  form.customer_name = row.customer_name
  form.status = row.status
  form.remark = row.remark
  form.items = []
  dialogOpen.value = true

  // 加载详情
  try {
    const res = await patternRoomApi.getBom(row.id)
    if (res.bom?.items) {
      form.items = res.bom.items
    }
  } catch (e) {
    showToast('加载 BOM 详情失败', 'error')
  }
}

async function handleCreate() {
  if (!form.product_name.trim()) {
    showToast('产品名称不能为空', 'warning')
    return
  }
  submitting.value = true
  try {
    const res = await patternRoomApi.createBom({
      product_name: form.product_name.trim(),
      customer_name: form.customer_name,
      remark: form.remark,
      items: form.items,
    })
    if (res.success) {
      showToast(`创建成功：${res.bom_no}`, 'success')
      dialogOpen.value = false
      await refetch()
    }
  } catch (e: any) {
    showToast(e?.detail || '创建失败', 'error')
  } finally {
    submitting.value = false
  }
}

async function handleSaveMeta() {
  if (!editingBomId.value) return
  if (!form.product_name.trim()) {
    showToast('产品名称不能为空', 'warning')
    return
  }
  submitting.value = true
  try {
    const res = await patternRoomApi.updateBom(editingBomId.value, {
      product_name: form.product_name.trim(),
      customer_name: form.customer_name,
      status: form.status,
      remark: form.remark,
    })
    if (res.success) {
      showToast('元信息保存成功', 'success')
      await refetch()
    }
  } catch (e: any) {
    showToast(e?.detail || '保存失败', 'error')
  } finally {
    submitting.value = false
  }
}

async function handleSaveItems() {
  if (!editingBomId.value) return
  if (!form.items.length) {
    showToast('请至少添加一个物料节点', 'warning')
    return
  }
  submitting.value = true
  try {
    const res = await patternRoomApi.saveBomItems(editingBomId.value, form.items)
    if (res.success) {
      showToast(`BOM 树保存成功（${res.message || ''}）`, 'success')
      await refetch()
    }
  } catch (e: any) {
    showToast(e?.detail || '保存失败', 'error')
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row: PatternRoomBom) {
  const ok = await confirmDialog.confirm(
    `确定删除 BOM "${row.bom_no}"？`,
    '此操作不可恢复，所有节点、版本快照、变更日志将一并删除',
    'danger',
  )
  if (!ok) return
  try {
    await patternRoomApi.deleteBom(row.id)
    showToast('删除成功', 'success')
    await refetch()
  } catch (e: any) {
    showToast(e?.detail || '删除失败', 'error')
  }
}

// ==================== BOM 树操作 ====================

function addRootItem() {
  form.items.push({
    sort_order: form.items.length,
    material_name: '',
    category: 'fabric',
    quantity: 1,
    unit: '个',
    spec: '',
    current_supplier_name: '',
    current_version: 'T1',
    remark: '',
    children: [],
    versions: [],
    _expanded: true,
  })
}

function onAddChild(parent: BomItem) {
  if (!parent.children) parent.children = []
  parent.children.push({
    sort_order: parent.children.length,
    material_name: '',
    category: parent.category,
    quantity: 1,
    unit: '个',
    spec: '',
    current_supplier_name: '',
    current_version: parent.current_version,
    remark: '',
    children: [],
    versions: [],
    _expanded: true,
  })
  parent._expanded = true
}

function onRemove(item: BomItem) {
  // 递归查找并删除
  const removeFromList = (list: BomItem[]): boolean => {
    const idx = list.indexOf(item)
    if (idx >= 0) {
      list.splice(idx, 1)
      return true
    }
    for (const it of list) {
      if (it.children && removeFromList(it.children)) return true
    }
    return false
  }
  removeFromList(form.items)
}

function onMove(payload: { item: BomItem; direction: 'up' | 'down' }) {
  const findList = (target: BomItem): BomItem[] | null => {
    const search = (list: BomItem[]): BomItem[] | null => {
      if (list.includes(target)) return list
      for (const it of list) {
        if (it.children) {
          const r = search(it.children)
          if (r) return r
        }
      }
      return null
    }
    return search(form.items)
  }
  const list = findList(payload.item)
  if (!list) return
  const idx = list.indexOf(payload.item)
  if (payload.direction === 'up' && idx > 0) {
    const prev = list[idx - 1]!
    const cur = list[idx]!
    list[idx - 1] = cur
    list[idx] = prev
  } else if (payload.direction === 'down' && idx < list.length - 1) {
    const next = list[idx + 1]!
    const cur = list[idx]!
    list[idx + 1] = cur
    list[idx] = next
  }
  list.forEach((it, i) => (it.sort_order = i))
}

function expandAll(expanded: boolean) {
  const walk = (list: BomItem[]) => {
    list.forEach((it) => {
      it._expanded = expanded
      if (it.children) walk(it.children)
    })
  }
  walk(form.items)
}

onMounted(() => {
  refetch()
})
</script>

<style scoped>
.pr-bom-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  min-height: 0;
}

.pr-filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.pr-fg {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pr-fg label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.pr-fg input,
.pr-fg select {
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 13px;
  background: white;
  color: var(--color-text);
  outline: none;
  transition: border-color 0.2s;
}

.pr-fg input:focus,
.pr-fg select:focus {
  border-color: var(--color-primary-400);
}

.pr-fg input {
  width: 180px;
}

.pr-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 2px solid var(--color-border-light);
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  background: white;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.pr-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-700);
}

.pr-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  border-color: transparent;
}

.pr-btn-primary:hover {
  color: white;
  opacity: 0.9;
}

.pr-btn-ghost {
  background: transparent;
}

.pr-btn-sm {
  padding: 5px 10px;
  font-size: 12px;
}

.pr-card {
  background: white;
  border-radius: 12px;
  border: 1px solid var(--color-border-light);
  overflow: hidden;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.pr-card-b {
  flex: 1;
  overflow: auto;
  min-height: 0;
}

.pr-card-b--flush {
  padding: 0;
}

.pr-tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.pr-tbl th {
  background: var(--color-surface);
  padding: 10px 14px;
  text-align: left;
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--color-border);
  position: sticky;
  top: 0;
  z-index: 1;
}

.pr-tbl td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-border-light);
  color: var(--color-text);
  vertical-align: middle;
}

.pr-bom-row:hover {
  background: var(--color-primary-50);
}

.pr-td-bold {
  font-weight: 600;
  color: var(--color-primary-700);
}

.pr-td-small {
  font-size: 12px;
}

.pr-td-muted {
  color: var(--color-text-muted);
}

.pr-empty {
  text-align: center;
  padding: 40px 14px;
  color: var(--color-text-muted);
}

.pr-empty i {
  margin-right: 8px;
}

.pr-fetching-row {
  height: 3px;
}

.pr-fetching-bar {
  padding: 0;
  height: 3px;
  background: transparent;
  border: none;
}

.pr-fetching-progress {
  height: 3px;
  background: linear-gradient(90deg, transparent, var(--color-primary-500), transparent);
  animation: pr-fetching 1.5s ease-in-out infinite;
}

@keyframes pr-fetching {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.pr-version-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 36px;
  padding: 3px 8px;
  background: linear-gradient(135deg, var(--color-purple-50), var(--color-purple-100));
  color: var(--color-purple-700);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
}

.pr-action-group {
  display: inline-flex;
  gap: 4px;
}

.pr-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.2s;
}

.pr-action-btn:hover {
  border-color: var(--color-primary-400);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
}

.pr-action-btn.pr-action-danger:hover {
  border-color: var(--color-danger-400);
  color: var(--color-danger-600);
  background: var(--color-danger-50);
}

/* Dialog */
.pr-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.pr-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.pr-form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pr-form-field--full {
  grid-column: 1 / -1;
}

.pr-form-field label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.pr-req {
  color: var(--color-danger-500);
}

.pr-form-field input,
.pr-form-field select,
.pr-form-field textarea {
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.2s;
  resize: vertical;
}

.pr-form-field input:focus,
.pr-form-field select:focus,
.pr-form-field textarea:focus {
  border-color: var(--color-primary-400);
}

.pr-tree-section {
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  overflow: hidden;
}

.pr-tree-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border-light);
}

.pr-tree-header h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
}

.pr-tree-actions {
  display: flex;
  gap: 8px;
}

.pr-tree-container {
  padding: 12px;
  min-height: 200px;
  max-height: 50vh;
  overflow-y: auto;
}

.pr-tree-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--color-text-muted);
  gap: 12px;
}

.pr-tree-empty i {
  font-size: 32px;
  opacity: 0.5;
}
</style>

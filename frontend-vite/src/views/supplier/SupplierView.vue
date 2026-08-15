<template>
  <div class="sp-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <button class="sp-action-btn sp-action-btn-primary" @click="formOpen = true">
          <FontAwesomeIcon icon="plus" aria-hidden="true" /> 添加供应商
        </button>
      </div>

      <!-- Search bar -->
      <div class="sp-toolbar">
        <div class="sp-search-wrapper">
          <UiSearchInput v-model="searchTerm" placeholder="搜索供应商名称..." @search="onSearchInput" @clear="clearSearch" /></div>
      </div>

      <!-- Content area -->
      <div class="sp-content">
        <!-- Loading (initial only) -->
        <div v-if="isLoading && suppliers.length === 0" class="sp-loading-state">
          <UiSpinner />
        </div>

        <!-- Empty -->
        <div v-else-if="suppliers.length === 0" class="sp-empty-state">
          <FontAwesomeIcon icon="truck" aria-hidden="true" />
          <span>{{ searchTerm ? '没有匹配的供应商' : '暂无供应商，请先添加' }}</span>
          <small v-if="searchTerm">试试其他关键词</small>
        </div>

        <!-- Table -->
        <div v-else class="sp-table-wrap">
          <div v-if="isFetching" class="sp-fetching-bar"><div class="sp-fetching-progress" /></div>
          <table>
            <thead>
              <tr>
                <th style="text-align: left">供应商名称</th>
                <th style="text-align: left">联系人</th>
                <th style="text-align: left">联系电话</th>
                <th style="text-align: left">地址</th>
                <th style="text-align: left">创建时间</th>
                <th style="text-align: center">状态</th>
                <th style="text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in suppliers" :key="row.id">
                <td>
                  <span class="sp-name">{{ row.name }}</span>
                </td>
                <td>{{ row.contact_person || '-' }}</td>
                <td>{{ row.phone || '-' }}</td>
                <td>{{ row.address || '-' }}</td>
                <td>{{ formatDate(row.created_at) }}</td>
                <td>
                  <span
                    class="sp-status-badge"
                    :class="row.status ? 'sp-status-active' : 'sp-status-inactive'"
                    :title="row.status ? '点击禁用' : '点击启用'"
                    @click="handleToggle(row)"
                  >{{ row.status ? '启用' : '禁用' }}</span>
                </td>
                <td>
                  <div class="sp-action-group">
                    <button class="sp-action-btn sp-action-edit" title="编辑" @click="openEditDialog(row)" aria-label="编辑">
                      <FontAwesomeIcon icon="edit" aria-hidden="true" />
                    </button>
                    <button
                      class="sp-action-btn sp-action-delete"
                      title="删除"
                      :disabled="actionId === row.id"
                      @click="handleDelete(row)"
                     aria-label="删除">
                      <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>

          <!-- Pagination -->
          <UiPagination v-if="totalItems > perPage" :current-page="currentPage" :total-pages="totalPages" :total-items="totalItems" @update:current-page="goPage" />
        </div>
      </div>
    </div>

    <!-- Add Dialog -->
    <UiDialog :open="formOpen" title="添加新供应商" max-width-class="max-w-[560px]" @update:open="formOpen = $event">
      <form @submit.prevent="handleAdd" class="sp-dialog-form">
        <div class="sp-form-field">
          <label class="sp-form-label"><FontAwesomeIcon icon="building" aria-hidden="true" /> 供应商名称 <span class="sp-required">*</span></label>
          <input v-model="form.name" type="text" class="sp-form-input" required placeholder="例如：广州面料有限公司" name="supplier-name" autocomplete="off" />
        </div>
        <div class="sp-form-row">
          <div class="sp-form-field">
            <label class="sp-form-label"><FontAwesomeIcon icon="user" aria-hidden="true" /> 联系人</label>
            <input v-model="form.contact_person" type="text" class="sp-form-input" placeholder="例如：李经理" name="contact" autocomplete="off" />
          </div>
          <div class="sp-form-field">
            <label class="sp-form-label"><FontAwesomeIcon icon="phone" aria-hidden="true" /> 联系电话</label>
            <input v-model="form.phone" type="text" class="sp-form-input" placeholder="例如：13800138000" name="phone" autocomplete="tel" />
          </div>
        </div>
        <div class="sp-form-field">
          <label class="sp-form-label"><FontAwesomeIcon icon="map-marker-alt" aria-hidden="true" /> 地址</label>
          <input v-model="form.address" type="text" class="sp-form-input" placeholder="例如：广州市白云区" name="address" autocomplete="off" />
        </div>
        <div class="sp-form-field">
          <label class="sp-form-label"><FontAwesomeIcon icon="sticky-note" aria-hidden="true" /> 备注</label>
          <textarea v-model="form.remark" rows="2" class="sp-form-input" placeholder="例如：长期合作供应商" />
        </div>
      </form>
      <template #footer>
        <UiButton variant="ghost" size="sm" @click="formOpen = false">取消</UiButton>
        <UiButton variant="primary" size="sm" :disabled="!form.name || submitting" @click="handleAdd">
          <FontAwesomeIcon icon="plus" aria-hidden="true" />
          {{ submitting ? '提交中…' : '添加供应商' }}
        </UiButton>
      </template>
    </UiDialog>

    <!-- Edit Dialog -->
    <UiDialog :open="editDialogVisible" title="编辑供应商" max-width-class="max-w-[560px]" @update:open="editDialogVisible = $event">
      <form @submit.prevent="handleEdit" class="sp-dialog-form">
        <div class="sp-form-field">
          <label class="sp-form-label"><FontAwesomeIcon icon="building" aria-hidden="true" /> 供应商名称 <span class="sp-required">*</span></label>
          <input v-model="editForm.name" type="text" class="sp-form-input" required placeholder="请输入供应商名称" name="supplier-name" autocomplete="off" />
        </div>
        <div class="sp-form-row">
          <div class="sp-form-field">
            <label class="sp-form-label"><FontAwesomeIcon icon="user" aria-hidden="true" /> 联系人</label>
            <input v-model="editForm.contact_person" type="text" class="sp-form-input" name="contact" autocomplete="off" />
          </div>
          <div class="sp-form-field">
            <label class="sp-form-label"><FontAwesomeIcon icon="phone" aria-hidden="true" /> 联系电话</label>
            <input v-model="editForm.phone" type="text" class="sp-form-input" name="phone" autocomplete="tel" />
          </div>
        </div>
        <div class="sp-form-field">
          <label class="sp-form-label"><FontAwesomeIcon icon="map-marker-alt" aria-hidden="true" /> 地址</label>
          <input v-model="editForm.address" type="text" class="sp-form-input" name="address" autocomplete="off" />
        </div>
        <div class="sp-form-field">
          <label class="sp-form-label"><FontAwesomeIcon icon="sticky-note" aria-hidden="true" /> 备注</label>
          <textarea v-model="editForm.remark" rows="2" class="sp-form-input" />
        </div>
      </form>
      <template #footer>
        <UiButton variant="ghost" size="sm" @click="editDialogVisible = false">取消</UiButton>
        <UiButton variant="primary" size="sm" :disabled="editSubmitting" @click="handleEdit">
          <FontAwesomeIcon icon="save" aria-hidden="true" />
          {{ editSubmitting ? '保存中…' : '保存' }}
        </UiButton>
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
 * SupplierView.vue — 供应商管理页面
 *
 * 职责：
 * - 展示供应商列表（服务端分页 + 搜索防抖）
 * - 新增 / 编辑 / 删除供应商
 * - 使用 TanStack Vue Query 管理服务端状态
 */
import { ref, reactive, computed } from 'vue'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { supplierApi } from '@/api'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { showToast } from '@/composables/useToast'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { formatDate } from '@/utils/format'
import type { Supplier } from '@/types'

/** 当前正在执行删除操作的供应商 ID（0 表示无操作） */
const actionId = ref<number | ''>(0)
const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()

/** 搜索关键词（即时绑定输入框） */
const searchTerm = ref('')
/** 当前页码 */
const currentPage = ref(1)
/** 每页条数 */
const perPage = 20

const { debounceSearch } = useDebouncedSearch()
/** 防抖后的搜索关键词，用于触发查询 */
const debouncedSearch = ref('')

/** 搜索输入防抖处理（300ms），避免频繁请求 */
function onSearchInput() {
  debounceSearch(() => {
    debouncedSearch.value = searchTerm.value
    currentPage.value = 1
  })
}

/** 清空搜索条件并重置到第一页 */
function clearSearch() {
  searchTerm.value = ''
  debouncedSearch.value = ''
  currentPage.value = 1
}

/** 供应商列表查询（服务端分页 + 搜索） */
const { data: result, isLoading, isFetching } = useQuery({
  queryKey: ['suppliers-list', () => debouncedSearch.value, () => currentPage.value],
  queryFn: () => supplierApi.list({ per_page: perPage, page: currentPage.value, search: debouncedSearch.value || undefined }),
  staleTime: 30_000,
  gcTime: 60_000,
  placeholderData: keepPreviousData,
})

/** 当前页供应商列表 */
const suppliers = computed<Supplier[]>(() => result.value?.suppliers ?? [])
/** 总记录数（用于分页） */
const totalItems = computed(() => result.value?.total ?? suppliers.value.length)
/** 总页数（至少为 1） */
const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / perPage)))

/** 跳转到指定页 */
function goPage(p: number) {
  currentPage.value = p
}

// ===== 新增供应商表单 =====
const formOpen = ref(false)
const submitting = ref(false)
const form = reactive({ name: '', contact_person: '', phone: '', address: '', remark: '' })

/** 提取错误消息：优先取后端 detail，否则返回默认消息 */
function extractErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail || fallback
}

/** 校验表单：名称必填，电话格式可选校验 */
function validateSupplierForm(name: string, phone: string): string | null {
  if (!name?.trim()) return '供应商名称不能为空'
  if (phone && !/^[\d\-+\s()]{6,20}$/.test(phone)) return '联系电话格式不正确'
  return null
}

/** 提交新增供应商 */
async function handleAdd() {
  const error = validateSupplierForm(form.name, form.phone)
  if (error) {
    showToast(error, 'warning')
    return
  }
  submitting.value = true
  try {
    await supplierApi.create(form)
    showToast('添加成功', 'success')
    Object.assign(form, { name: '', contact_person: '', phone: '', address: '', remark: '' })
    formOpen.value = false
    queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, '添加失败'), 'error')
  } finally {
    submitting.value = false
  }
}

/** 删除供应商（带确认对话框） */
async function handleDelete(row: Supplier) {
  if (!(await confirmDialog.confirm(`确定要删除供应商"${row.name}"吗？如果该供应商已关联BOM或采购订单，将无法删除。`))) return
  actionId.value = row.id
  try {
    await supplierApi.delete(row.id)
    showToast('删除成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, '删除失败'), 'error')
  } finally {
    actionId.value = 0
  }
}

/** 切换供应商启用/禁用状态 */
async function handleToggle(row: Supplier) {
  const target = row.status ? '禁用' : '启用'
  if (!(await confirmDialog.confirm(`确定要${target}供应商"${row.name}"吗？`))) return
  actionId.value = row.id
  try {
    await supplierApi.toggleStatus(row.id)
    showToast(`${target}成功`, 'success')
    queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, `${target}失败`), 'error')
  } finally {
    actionId.value = 0
  }
}

// ===== 编辑供应商表单 =====
const editDialogVisible = ref(false)
const editSubmitting = ref(false)
const editForm = reactive({ id: 0, name: '', contact_person: '', phone: '', address: '', remark: '' })

/** 打开编辑弹窗，填充当前行数据 */
function openEditDialog(row: Supplier) {
  Object.assign(editForm, {
    id: row.id,
    name: row.name,
    contact_person: row.contact_person,
    phone: row.phone,
    address: row.address,
    remark: row.remark,
  })
  editDialogVisible.value = true
}

/** 提交编辑供应商 */
async function handleEdit() {
  const error = validateSupplierForm(editForm.name, editForm.phone)
  if (error) {
    showToast(error, 'warning')
    return
  }
  editSubmitting.value = true
  try {
    await supplierApi.update(editForm.id, editForm)
    showToast('保存成功', 'success')
    editDialogVisible.value = false
    queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, '保存失败'), 'error')
  } finally {
    editSubmitting.value = false
  }
}
</script>

<style scoped>
/* === Layout === */
.sp-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.sp-card-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.sp-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}

.sp-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

/* === Icon Boxes === */
.sp-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}

.sp-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

/* === Header Actions === */
.sp-header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* === Action Button (Design Spec §10) === */
.sp-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 7px 14px;
  border: 2px solid var(--color-border-light);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text);
}

.sp-action-btn-primary {
  color: var(--color-primary-600);
}

.sp-action-btn-primary:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

/* === Toolbar (Search) === */
.sp-toolbar {
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  flex-shrink: 0;
}

.sp-search-wrapper {
  position: relative;
}

.sp-search-input-group {
  position: relative;
  display: flex;
  align-items: center;
}

.sp-search-icon {
  position: absolute;
  left: 14px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
  z-index: 2;
}

.sp-search-input {
  width: 100%;
  padding: 12px 40px 12px 42px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 11px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  background: white;
  font-family: inherit;
  color: var(--color-text);
}

.sp-search-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }

.sp-search-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

.sp-search-clear {
  position: absolute;
  right: 10px;
  background: none;
  border: none;
  color: var(--color-text-muted, #94a3b8);
  cursor: pointer;
  padding: 6px;
  border-radius: 50%;
  transition: background 0.2s ease, color 0.2s ease;
}

.sp-search-clear:hover {
  background: var(--color-surface, #f1f5f9);
  color: var(--color-text-secondary);
}

/* === Content Area === */
.sp-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* === Table === */
.sp-table-wrap {
  padding: 0 24px 24px;
}

.sp-table-wrap table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.sp-table-wrap thead th {
  padding: 10px 14px;
  background: var(--color-surface, #f8fafc);
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}

.sp-table-wrap tbody td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  color: var(--color-text);
  vertical-align: middle;
  transition: background 0.2s ease;
}

.sp-table-wrap tbody tr:last-child td {
  border-bottom: none;
}

.sp-table-wrap tbody tr:hover td {
  background: var(--color-primary-50);
}

.sp-name {
  font-weight: 600;
  color: var(--color-text);
}

/* === Status Badge === */
.sp-status-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease, color 0.2s ease, transform 0.2s ease;
  text-align: center;
  min-width: 56px;
}

.sp-status-active {
  background: var(--color-success-50, #ecfdf5);
  color: var(--color-success-700, #047857);
  border: 1px solid var(--color-success-200, #a7f3d0);
}

.sp-status-active:hover {
  background: var(--color-danger-50, #fef2f2);
  color: var(--color-danger-700, #b91c1c);
  border-color: var(--color-danger-200, #fecaca);
  transform: translateY(-1px);
}

.sp-status-inactive {
  background: var(--color-surface, #f1f5f9);
  color: var(--color-text-muted, #94a3b8);
  border: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-status-inactive:hover {
  background: var(--color-success-50, #ecfdf5);
  color: var(--color-success-700, #047857);
  border-color: var(--color-success-200, #a7f3d0);
  transform: translateY(-1px);
}

/* === Action Buttons (Table) === */
.sp-action-group {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.sp-action-edit,
.sp-action-delete {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: 2px solid transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
  cursor: pointer;
  padding: 0;
}

.sp-action-edit {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  border-color: var(--color-primary-200);
}

.sp-action-edit:hover {
  background: var(--color-primary-500);
  color: white;
  border-color: transparent;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 148, 191, 0.25);
}

.sp-action-delete {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
  border-color: var(--color-danger-200);
}

.sp-action-delete:hover {
  background: var(--color-danger-500);
  color: white;
  border-color: transparent;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(234, 84, 85, 0.25);
}

.sp-action-delete:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* === Empty & Loading States === */
.sp-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
}

.sp-empty-state i {
  font-size: 28px;
  opacity: 0.5;
}

.sp-empty-state small {
  font-size: 12px;
  opacity: 0.6;
}

.sp-loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-primary-500);
  font-size: 14px;
}

.sp-loading-state i {
  font-size: 20px;
}

/* Fetching progress bar */
.sp-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.sp-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: sp-progress-slide 1s ease-in-out infinite;
}
@keyframes sp-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* === Required Mark === */
.sp-required {
  color: var(--color-danger-500);
  font-weight: 600;
}

/* === Dialog Form === */
.sp-dialog-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sp-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.sp-form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sp-form-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.sp-form-label i {
  margin-right: 4px;
  color: var(--color-primary-500);
  font-size: 11px;
}

.sp-form-input {
  width: 100%;
  padding: 10px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  background: white;
  font-family: inherit;
  color: var(--color-text);
  box-sizing: border-box;
}

.sp-form-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }

.sp-form-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

textarea.sp-form-input {
  resize: vertical;
  min-height: 60px;
}
</style>

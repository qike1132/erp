<template>
  <div class="sp-container">
    <div class="sp-card sp-card-main">
      <div class="sp-card-header">
        <div class="sp-header-left">
          <HeaderTabs />
        </div>
        <div class="sp-header-right">
          <button class="sp-action-btn sp-action-btn-primary" @click="formOpen = true">
            <i class="fas fa-plus" /> 添加供应商
          </button>
        </div>
      </div>

      <!-- Search bar -->
      <div class="sp-toolbar">
        <div class="sp-search-wrapper">
          <div class="sp-search-input-group">
            <i class="fas fa-search sp-search-icon" />
            <input
              v-model="searchTerm"
              type="text"
              placeholder="搜索供应商名称..."
              class="sp-search-input"
              @input="onSearchInput"
            />
            <button
              v-if="searchTerm"
              class="sp-search-clear"
              @click="clearSearch"
            >
              <i class="fas fa-times" />
            </button>
          </div>
        </div>
      </div>

      <!-- Content area -->
      <div class="sp-content">
        <!-- Loading (initial only) -->
        <div v-if="isLoading && suppliers.length === 0" class="sp-loading-state">
          <i class="fas fa-spinner fa-spin" />
          <span>加载中...</span>
        </div>

        <!-- Empty -->
        <div v-else-if="suppliers.length === 0" class="sp-empty-state">
          <i class="fas fa-truck" />
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
                <td>{{ row.created_at ? row.created_at.split('T')[0] : '-' }}</td>
                <td>
                  <div class="sp-action-group">
                    <button class="sp-action-btn sp-action-edit" title="编辑" @click="openEditDialog(row)">
                      <i class="fas fa-edit" />
                    </button>
                    <button
                      class="sp-action-btn sp-action-delete"
                      title="删除"
                      :disabled="actionId === row.id"
                      @click="handleDelete(row)"
                    >
                      <i class="fas fa-trash-alt" />
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
          <label class="sp-form-label"><i class="fas fa-building" /> 供应商名称 <span class="sp-required">*</span></label>
          <input v-model="form.name" type="text" class="sp-form-input" required placeholder="例如：广州面料有限公司" />
        </div>
        <div class="sp-form-row">
          <div class="sp-form-field">
            <label class="sp-form-label"><i class="fas fa-user" /> 联系人</label>
            <input v-model="form.contact_person" type="text" class="sp-form-input" placeholder="例如：李经理" />
          </div>
          <div class="sp-form-field">
            <label class="sp-form-label"><i class="fas fa-phone" /> 联系电话</label>
            <input v-model="form.phone" type="text" class="sp-form-input" placeholder="例如：13800138000" />
          </div>
        </div>
        <div class="sp-form-field">
          <label class="sp-form-label"><i class="fas fa-map-marker-alt" /> 地址</label>
          <input v-model="form.address" type="text" class="sp-form-input" placeholder="例如：广州市白云区" />
        </div>
        <div class="sp-form-field">
          <label class="sp-form-label"><i class="fas fa-sticky-note" /> 备注</label>
          <textarea v-model="form.remark" rows="2" class="sp-form-input" placeholder="例如：长期合作供应商" />
        </div>
      </form>
      <template #footer>
        <UiButton variant="ghost" size="sm" @click="formOpen = false">取消</UiButton>
        <UiButton variant="primary" size="sm" :disabled="!form.name || submitting" @click="handleAdd">
          <i class="fas fa-plus" />
          {{ submitting ? '提交中...' : '添加供应商' }}
        </UiButton>
      </template>
    </UiDialog>

    <!-- Edit Dialog -->
    <UiDialog :open="editDialogVisible" title="编辑供应商" max-width-class="max-w-[560px]" @update:open="editDialogVisible = $event">
      <form @submit.prevent="handleEdit" class="sp-dialog-form">
        <div class="sp-form-field">
          <label class="sp-form-label"><i class="fas fa-building" /> 供应商名称 <span class="sp-required">*</span></label>
          <input v-model="editForm.name" type="text" class="sp-form-input" />
        </div>
        <div class="sp-form-row">
          <div class="sp-form-field">
            <label class="sp-form-label"><i class="fas fa-user" /> 联系人</label>
            <input v-model="editForm.contact_person" type="text" class="sp-form-input" />
          </div>
          <div class="sp-form-field">
            <label class="sp-form-label"><i class="fas fa-phone" /> 联系电话</label>
            <input v-model="editForm.phone" type="text" class="sp-form-input" />
          </div>
        </div>
        <div class="sp-form-field">
          <label class="sp-form-label"><i class="fas fa-map-marker-alt" /> 地址</label>
          <input v-model="editForm.address" type="text" class="sp-form-input" />
        </div>
        <div class="sp-form-field">
          <label class="sp-form-label"><i class="fas fa-sticky-note" /> 备注</label>
          <textarea v-model="editForm.remark" rows="2" class="sp-form-input" />
        </div>
      </form>
      <template #footer>
        <UiButton variant="ghost" size="sm" @click="editDialogVisible = false">取消</UiButton>
        <UiButton variant="primary" size="sm" :disabled="editSubmitting" @click="handleEdit">
          <i class="fas fa-save" />
          {{ editSubmitting ? '保存中...' : '保存' }}
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
import { ref, reactive, computed, watch } from 'vue'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { supplierApi } from '@/api'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import type { Supplier } from '@/types'

const actionId = ref<number | ''>(0)
const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()

const searchTerm = ref('')
const currentPage = ref(1)
const perPage = 20

let searchTimer: ReturnType<typeof setTimeout> | null = null
const debouncedSearch = ref('')
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    debouncedSearch.value = searchTerm.value
    currentPage.value = 1
  }, 300)
}
function clearSearch() {
  searchTerm.value = ''
  debouncedSearch.value = ''
  currentPage.value = 1
}

const { data: result, isLoading, isFetching } = useQuery({
  queryKey: ['suppliers-list', () => debouncedSearch.value, () => currentPage.value],
  queryFn: () => supplierApi.list({ per_page: perPage, page: currentPage.value, search: debouncedSearch.value || undefined }) as Promise<any>,
  staleTime: 30_000,
  gcTime: 60_000,
  placeholderData: keepPreviousData,
})

const suppliers = computed<Supplier[]>(() => result.value?.data ?? result.value?.suppliers ?? [])
const totalItems = computed(() => result.value?.total ?? suppliers.value.length)
const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / perPage)))

function goPage(p: number) {
  currentPage.value = p
}

// Add form
const formOpen = ref(false)
const submitting = ref(false)
const form = reactive({ name: '', contact_person: '', phone: '', address: '', remark: '' })

async function handleAdd() {
  if (!form.name) return
  submitting.value = true
  try {
    await supplierApi.create(form)
    showToast('添加成功', 'success')
    Object.assign(form, { name: '', contact_person: '', phone: '', address: '', remark: '' })
    formOpen.value = false
    queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '添加失败', 'error')
  } finally {
    submitting.value = false
  }
}

// Delete
async function handleDelete(row: Supplier) {
  if (!(await confirmDialog.confirm(`确定要删除供应商"${row.name}"吗？如果该供应商已关联BOM或采购订单，将无法删除。`))) return
  actionId.value = row.id
  try {
    await supplierApi.delete(row.id)
    showToast('删除成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '删除失败', 'error')
  } finally {
    actionId.value = 0
  }
}

// Edit form
const editDialogVisible = ref(false)
const editSubmitting = ref(false)
const editForm = reactive({ id: 0, name: '', contact_person: '', phone: '', address: '', remark: '' })

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

async function handleEdit() {
  editSubmitting.value = true
  try {
    await supplierApi.update(editForm.id, editForm)
    showToast('保存成功', 'success')
    editDialogVisible.value = false
    queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '保存失败', 'error')
  } finally {
    editSubmitting.value = false
  }
}
</script>

<style scoped>
/* === Layout === */
.sp-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* === Main Card === */
.sp-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1), transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.sp-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 16px 48px rgba(0,0,0,0.12);
  transform: translateY(-3px);
}

.sp-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.sp-card-header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  padding: 14px 24px 10px;
  flex-shrink: 0;
  gap: 12px;
}
.sp-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}
.sp-header-right {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
}
.sp-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
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
  transition: all 0.3s ease;
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
  transition: all 0.3s ease;
  background: white;
  font-family: inherit;
  color: var(--color-text);
}

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
  transition: all 0.2s ease;
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
  transition: all 0.2s ease;
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
  transition: all 0.3s ease;
  background: white;
  font-family: inherit;
  color: var(--color-text);
  box-sizing: border-box;
}

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

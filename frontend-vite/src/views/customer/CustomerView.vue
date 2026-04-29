<template>
  <div class="cu-container">
    <div class="cu-card cu-card-main">
      <!-- 卡片头部 -->
      <div class="cu-card-header">
        <div class="cu-card-title-group">
          <div class="cu-icon-box cu-icon-blue">
            <i class="fas fa-building" />
          </div>
          <div>
            <h3>客户管理</h3>
            <small>管理所有客户信息与状态</small>
          </div>
        </div>
        <div class="cu-header-actions">
          <span class="cu-count-badge">{{ customers.length }}</span>
          <button class="cu-action-btn cu-action-primary" @click="openForm('add')">
            <i class="fas fa-plus" style="margin-right: 4px; font-size: 11px" />新建客户
          </button>
        </div>
      </div>

      <!-- 统计指标 -->
      <div class="cu-metrics">
        <div class="cu-metric-card cu-metric-all" :class="{ active: statusFilter === 'all' }" @click="statusFilter = 'all'; currentPage = 1">
          <div class="cu-metric-icon cu-icon-blue"><i class="fas fa-building" /></div>
          <div class="cu-metric-content">
            <span class="cu-metric-number">{{ customers.length }}</span>
            <span class="cu-metric-label">全部客户</span>
          </div>
        </div>
        <div class="cu-metric-card cu-metric-active" :class="{ active: statusFilter === 'active' }" @click="statusFilter = 'active'; currentPage = 1">
          <div class="cu-metric-icon cu-icon-green"><i class="fas fa-circle-check" /></div>
          <div class="cu-metric-content">
            <span class="cu-metric-number">{{ activeCount }}</span>
            <span class="cu-metric-label">已启用</span>
          </div>
        </div>
        <div class="cu-metric-card cu-metric-inactive" :class="{ active: statusFilter === 'inactive' }" @click="statusFilter = 'inactive'; currentPage = 1">
          <div class="cu-metric-icon cu-icon-red"><i class="fas fa-circle-xmark" /></div>
          <div class="cu-metric-content">
            <span class="cu-metric-number">{{ inactiveCount }}</span>
            <span class="cu-metric-label">已禁用</span>
          </div>
        </div>
      </div>

      <!-- 搜索栏 -->
      <div class="cu-search-bar">
        <div class="cu-search-wrapper">
          <i class="fas fa-search cu-search-icon" />
          <input v-model="searchTerm" class="cu-search-input" placeholder="搜索客户名称、联系人或电话..." @input="currentPage = 1" />
          <button v-if="searchTerm" class="cu-search-clear" @click="searchTerm = ''; currentPage = 1">
            <i class="fas fa-times" />
          </button>
        </div>
      </div>

      <!-- 数据表格 -->
      <div class="cu-table-wrap">
        <div v-if="isLoading" class="cu-empty">
          <i class="fas fa-spinner fa-spin" />
          <span>加载中...</span>
        </div>
        <template v-else-if="pagedCustomers.length === 0">
          <div class="cu-empty">
            <i class="fas fa-building" />
            <span>暂无客户数据</span>
            <button class="cu-action-btn cu-action-primary" @click="openForm('add')">立即添加</button>
          </div>
        </template>
        <table v-else class="cu-table">
          <thead>
            <tr>
              <th style="text-align: left">客户名称</th>
              <th>联系人</th>
              <th>联系电话</th>
              <th style="text-align: left">地址</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in pagedCustomers" :key="row.id">
              <td style="text-align: left">
                <div class="cu-customer-cell">
                  <div class="cu-customer-avatar">{{ row.name.charAt(0) }}</div>
                  <div class="cu-customer-info">
                    <span class="cu-customer-name">{{ row.name }}</span>
                    <span v-if="row.customer_code" class="cu-customer-code">{{ row.customer_code }}</span>
                  </div>
                </div>
              </td>
              <td><span :class="row.contact ? 'cu-text-body' : 'cu-text-muted'">{{ row.contact || '未填写' }}</span></td>
              <td><span :class="row.phone ? 'cu-text-body' : 'cu-text-muted'">{{ row.phone || '未填写' }}</span></td>
              <td style="text-align: left"><span :class="row.address ? 'cu-text-body' : 'cu-text-muted'">{{ row.address || '未填写' }}</span></td>
              <td>
                <span :class="['cu-status', row.status ? 'cu-status-on' : 'cu-status-off']">
                  <i class="cu-dot" />{{ row.status ? '启用' : '停用' }}
                </span>
              </td>
              <td><span class="cu-text-muted">{{ row.create_time || '-' }}</span></td>
              <td>
                <div class="cu-actions">
                  <button class="cu-icon-btn cu-icon-edit" title="编辑" @click="openForm('edit', row)"><i class="fas fa-pen-to-square" /></button>
                  <button class="cu-icon-btn cu-icon-toggle" title="切换状态" @click="handleToggle(row)"><i :class="row.status ? 'fas fa-lock' : 'fas fa-lock-open'" /></button>
                  <button class="cu-icon-btn cu-icon-delete" title="删除" @click="handleDelete(row)"><i class="fas fa-trash" /></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- 分页 -->
        <div v-if="filteredTotal > perPage" class="cu-table-footer">
          <span class="cu-total-text">共 {{ filteredTotal }} 条</span>
          <UiPagination :current-page="currentPage" :total-pages="totalPages" @update:current-page="currentPage = $event" />
        </div>
      </div>
    </div>

    <!-- 新建/编辑弹窗 -->
    <UiDialog :open="formVisible" :title="formMode === 'add' ? '新建客户' : '编辑客户'" @update:open="formVisible = $event">
      <form @submit.prevent="handleSubmit">
        <div class="cu-form-group">
          <label>客户名称 <span class="cu-required">*</span></label>
          <input v-model="form.name" class="cu-form-input" placeholder="请输入客户名称" />
        </div>
        <div class="cu-form-grid">
          <div class="cu-form-group"><label>联系人</label><input v-model="form.contact" class="cu-form-input" placeholder="联系人姓名" /></div>
          <div class="cu-form-group"><label>联系电话</label><input v-model="form.phone" class="cu-form-input" placeholder="联系电话" /></div>
        </div>
        <div class="cu-form-group"><label>地址</label><input v-model="form.address" class="cu-form-input" placeholder="详细地址" /></div>
        <div class="cu-form-group">
          <label>备注</label>
          <textarea v-model="form.note" rows="3" placeholder="选填" class="cu-form-textarea" style="resize: none" />
        </div>
      </form>
      <template #footer>
        <button class="cu-action-btn" @click="formVisible = false">取消</button>
        <button class="cu-action-btn cu-action-primary" :disabled="submitting" @click="handleSubmit">
          {{ submitting ? '提交中...' : formMode === 'add' ? '创建' : '保存修改' }}
        </button>
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
import { ref, reactive, computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { customerApi } from '@/api'
import { useApiMutation } from '@/composables/useApiMutation'
import type { Customer } from '@/types'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'

// ===== 列表查询 =====
const { data: result, isLoading } = useQuery({
  queryKey: ['customers-list'],
  queryFn: () => customerApi.list({ per_page: 200 }) as Promise<any>,
  staleTime: 30_000,
})

const customers = computed<Customer[]>(() => {
  const raw = result.value?.customers ?? result.value?.data ?? []
  return raw.map((c: any) => ({ ...c, status: c.status === true || c.status === 'active' }))
})

// ===== 统计 =====
const activeCount = computed(() => customers.value.filter((c) => c.status).length)
const inactiveCount = computed(() => customers.value.filter((c) => !c.status).length)

// ===== 搜索与筛选 =====
const searchTerm = ref('')
const statusFilter = ref<'all' | 'active' | 'inactive'>('all')

const filteredCustomers = computed(() => {
  let list = customers.value
  if (searchTerm.value) {
    const term = searchTerm.value.toLowerCase()
    list = list.filter(
      (c) =>
        c.name.toLowerCase().includes(term) ||
        (c.contact && c.contact.toLowerCase().includes(term)) ||
        (c.phone && c.phone.includes(term)),
    )
  }
  if (statusFilter.value === 'active') list = list.filter((c) => c.status)
  if (statusFilter.value === 'inactive') list = list.filter((c) => !c.status)
  return list
})

// ===== 客户端分页 =====
const currentPage = ref(1)
const perPage = 20
const filteredTotal = computed(() => filteredCustomers.value.length)
const totalPages = computed(() => Math.ceil(filteredTotal.value / perPage) || 1)
const pagedCustomers = computed(() => {
  const start = (currentPage.value - 1) * perPage
  return filteredCustomers.value.slice(start, start + perPage)
})

// ===== 表单 =====
const formVisible = ref(false)
const formMode = ref<'add' | 'edit'>('add')
const submitting = ref(false)
const form = reactive({ id: 0, name: '', contact: '', phone: '', address: '', note: '' })

function resetForm() {
  Object.assign(form, { id: 0, name: '', contact: '', phone: '', address: '', note: '' })
}

function openForm(mode: 'add' | 'edit', row?: Customer) {
  formMode.value = mode
  if (mode === 'edit' && row) {
    Object.assign(form, {
      id: row.id,
      name: row.name,
      contact: row.contact || '',
      phone: row.phone || '',
      address: row.address || '',
      note: row.note || '',
    })
  } else {
    resetForm()
  }
  formVisible.value = true
}

// ===== Mutations =====
const addMutation = useApiMutation((data: typeof form) => customerApi.create(data), {
  invalidateKeys: ['customers-list'],
  successMsg: '客户创建成功',
})

const editMutation = useApiMutation((data: typeof form) => customerApi.update(data.id, data), {
  invalidateKeys: ['customers-list'],
  successMsg: '修改已保存',
})

const toggleMutation = useApiMutation((id: number) => customerApi.toggleStatus(id), {
  invalidateKeys: ['customers-list'],
})

const deleteMutation = useApiMutation((id: number) => customerApi.delete(id), {
  invalidateKeys: ['customers-list'],
  successMsg: '客户已删除',
})
const confirmDialog = useConfirmDialog()

async function handleSubmit() {
  if (!form.name) return
  submitting.value = true
  try {
    if (formMode.value === 'add') await addMutation.mutate(form)
    else await editMutation.mutate(form)
    formVisible.value = false
  } catch {
    /* useApiMutation already shows error */
  } finally {
    submitting.value = false
  }
}

const actionId = ref<number | null>(null)

async function handleToggle(row: Customer) {
  const action = row.status ? '禁用' : '启用'
  if (!(await confirmDialog.confirm(`确定要${action}客户「${row.name}」吗？`))) return
  actionId.value = row.id
  try {
    await toggleMutation.mutate(row.id)
  } finally {
    actionId.value = null
  }
}

async function handleDelete(row: Customer) {
  if (!(await confirmDialog.confirm(`删除客户「${row.name}」后不可恢复，确认继续？`))) return
  actionId.value = row.id
  try {
    await deleteMutation.mutate(row.id)
  } finally {
    actionId.value = null
  }
}
</script>

<style scoped>
/* Container */
.cu-container {
  padding: 12px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card */
.cu-card {
  background: white;
  border-radius: 14px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}
.cu-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 16px 48px rgba(0,0,0,0.12);
  transform: translateY(-2px);
}
.cu-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* Card Header */
.cu-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px 10px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.cu-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.cu-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.cu-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}
.cu-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* Icon Box */
.cu-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.cu-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}
.cu-icon-green {
  background: linear-gradient(135deg, var(--color-success-100), var(--color-success-200));
  color: var(--color-success-700);
}
.cu-icon-red {
  background: linear-gradient(135deg, var(--color-danger-100), var(--color-danger-200));
  color: var(--color-danger-700);
}

/* Count Badge */
.cu-count-badge {
  padding: 6px 14px;
  border-radius: 20px;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  font-size: 13px;
  font-weight: 600;
}

/* Action Button */
.cu-action-btn {
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  color: var(--color-text-secondary);
}
.cu-action-primary {
  color: var(--color-primary-600);
}
.cu-action-primary:hover:not(:disabled) {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.cu-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Metrics */
.cu-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.cu-metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  cursor: pointer;
  transition: all 0.3s ease;
}
.cu-metric-card:hover {
  transform: translateY(-1px);
}
.cu-metric-card.active {
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 1px var(--color-primary-500);
}
.cu-metric-all.active { background: var(--color-primary-50); }
.cu-metric-active.active { background: var(--color-success-50); border-color: var(--color-success-500); box-shadow: 0 0 0 1px var(--color-success-500); }
.cu-metric-inactive.active { background: var(--color-danger-50); border-color: var(--color-danger-500); box-shadow: 0 0 0 1px var(--color-danger-500); }
.cu-metric-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.cu-metric-content {
  display: flex;
  flex-direction: column;
}
.cu-metric-number {
  font-size: 22px;
  font-weight: 800;
  color: var(--color-text);
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.cu-metric-label {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 2px;
}

/* Search */
.cu-search-bar {
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.cu-search-wrapper {
  position: relative;
  max-width: 360px;
}
.cu-search-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  font-size: 13px;
}
.cu-search-input {
  width: 100%;
  padding: 10px 36px 10px 38px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 11px;
  background: var(--color-surface, #f8fafc);
  font-size: 13px;
  outline: none;
  transition: all 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
}
.cu-search-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cu-search-clear {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: none;
  background: var(--color-border-light);
  color: var(--color-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  transition: all 0.2s ease;
}
.cu-search-clear:hover {
  background: var(--color-text-muted);
  color: white;
}

/* Table */
.cu-table-wrap {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.cu-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.cu-table thead th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  color: var(--color-text-secondary);
  text-align: center;
}
.cu-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  text-align: center;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.cu-table tbody tr:hover {
  background: var(--color-primary-50);
}

/* Customer cell */
.cu-customer-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cu-customer-avatar {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.cu-customer-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cu-customer-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}
.cu-customer-code {
  font-size: 11px;
  color: var(--color-text-muted);
  font-family: 'SF Mono', 'Fira Code', monospace;
  letter-spacing: 0.02em;
}

/* Text */
.cu-text-body { font-size: 13px; color: var(--color-text); }
.cu-text-muted { font-size: 13px; color: var(--color-text-muted); font-variant-numeric: tabular-nums; }

/* Status */
.cu-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}
.cu-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}
.cu-status-on { color: var(--color-success-600); }
.cu-status-on .cu-dot { background: var(--color-success-500); box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.15); }
.cu-status-off { color: var(--color-text-muted); }
.cu-status-off .cu-dot { background: var(--color-border); }

/* Actions */
.cu-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.cu-icon-btn {
  width: 30px;
  height: 30px;
  border: none;
  background: transparent;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--color-text-muted);
  transition: all 0.2s ease;
  font-size: 13px;
}
.cu-icon-btn:hover { background: var(--color-border-light); }
.cu-icon-edit:hover { color: var(--color-primary-500); background: var(--color-primary-50); }
.cu-icon-toggle:hover { color: var(--color-warning-500); background: var(--color-warning-50); }
.cu-icon-delete:hover { color: var(--color-danger-500); background: var(--color-danger-50); }

/* Table Footer */
.cu-table-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  border-top: 1px solid var(--color-border-light);
}
.cu-total-text {
  font-size: 13px;
  color: var(--color-text-muted);
}

/* Empty */
.cu-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.cu-empty i { font-size: 28px; opacity: 0.5; }
.cu-empty span { font-size: 14px; }

/* Dialog Form */
.cu-form-group {
  margin-bottom: 14px;
}
.cu-form-group label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.cu-required { color: var(--color-danger-500); }
.cu-form-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  transition: all 0.3s ease;
  outline: none;
  font-family: inherit;
  color: var(--color-text);
  background: white;
}
.cu-form-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cu-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.cu-form-textarea {
  width: 100%;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  outline: none;
  transition: all 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
}
.cu-form-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

/* Responsive */
@media (max-width: 900px) {
  .cu-metrics { grid-template-columns: 1fr; gap: 8px; }
  .cu-form-grid { grid-template-columns: 1fr; }
}
</style>

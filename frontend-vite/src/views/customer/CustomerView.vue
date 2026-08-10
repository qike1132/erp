<template>
  <div class="cu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <div class="cu-header-left">
          <HeaderTabs />
        </div>
        <div class="cu-header-right">
          <div class="cu-tabs">
            <button class="cu-tab-btn active" @click="openForm('add')">
              <FontAwesomeIcon icon="plus" aria-hidden="true" /> 新建客户
            </button>
          </div>
        </div>
      </div>

      <!-- 数据表格 -->
      <div class="cu-table-wrap">
        <div v-if="isLoading && customers.length === 0" class="cu-empty">
          <UiSpinner />
        </div>
        <template v-else-if="customers.length === 0">
          <div class="cu-empty">
            <FontAwesomeIcon icon="building" aria-hidden="true" />
            <span>暂无客户数据</span>
            <button class="cu-action-btn cu-action-primary" @click="openForm('add')">立即添加</button>
          </div>
        </template>
        <template v-else>
        <div v-if="isFetching" class="cu-fetching-bar"><div class="cu-fetching-progress" /></div>
        <table class="cu-table">
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
            <tr v-for="row in customers" :key="row.id">
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
              <td><span class="cu-text-muted">{{ formatDate(row.create_time) }}</span></td>
              <td>
                <div class="cu-actions">
                  <button class="cu-icon-btn cu-icon-edit" title="编辑" @click="openForm('edit', row)" aria-label="编辑"><FontAwesomeIcon icon="pen-to-square" aria-hidden="true" /></button>
                  <button class="cu-icon-btn cu-icon-toggle" title="切换状态" @click="handleToggle(row)" aria-label="切换状态"><FontAwesomeIcon :icon="row.status ? 'lock' : 'lock-open'" aria-hidden="true" /></button>
                  <button class="cu-icon-btn cu-icon-delete" title="删除" @click="handleDelete(row)" aria-label="删除"><FontAwesomeIcon icon="trash" aria-hidden="true" /></button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- 分页 -->
        <UiPagination v-if="totalItems > perPage" :current-page="currentPage" :total-pages="totalPages" :total-items="totalItems" @update:current-page="currentPage = $event" />
        </template>
      </div>
    </div>

    <!-- 新建/编辑弹窗 -->
    <UiDialog :open="formVisible" :title="formMode === 'add' ? '新建客户' : '编辑客户'" @update:open="formVisible = $event">
      <form @submit.prevent="handleSubmit">
        <div class="cu-form-group">
          <label>客户名称 <span class="cu-required">*</span></label>
          <input v-model="form.name" class="cu-form-input" required placeholder="请输入客户名称" name="customer-name" autocomplete="off" />
        </div>
        <div class="cu-form-grid">
          <div class="cu-form-group"><label>联系人</label><input v-model="form.contact" class="cu-form-input" placeholder="联系人姓名" name="contact" autocomplete="off" /></div>
          <div class="cu-form-group"><label>联系电话</label><input v-model="form.phone" class="cu-form-input" placeholder="联系电话" name="phone" autocomplete="tel" /></div>
        </div>
        <div class="cu-form-group"><label>地址</label><input v-model="form.address" class="cu-form-input" placeholder="详细地址" name="address" autocomplete="off" /></div>
        <div class="cu-form-group">
          <label>备注</label>
          <textarea v-model="form.note" rows="3" placeholder="选填" class="cu-form-textarea" style="resize: none" />
        </div>
      </form>
      <template #footer>
        <button class="cu-action-btn" @click="formVisible = false">取消</button>
        <button class="cu-action-btn cu-action-primary" :disabled="submitting" @click="handleSubmit">
          {{ submitting ? '提交中…' : formMode === 'add' ? '创建' : '保存修改' }}
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
/**
 * CustomerView.vue — 客户管理页面
 *
 * 职责：
 * - 展示客户列表（服务端分页 + 搜索防抖 + 状态筛选）
 * - 新增 / 编辑 / 删除客户，切换启用/停用状态
 * - 使用 useApiMutation 统一管理增删改操作
 */
import { ref, reactive, computed, onUnmounted } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { showToast } from '@/composables/useToast'
import { customerApi } from '@/api'
import { useApiMutation } from '@/composables/useApiMutation'
import type { Customer } from '@/types'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { formatDate } from '@/utils/format'

// ===== 列表查询（服务端分页+搜索） =====
/** 搜索关键词（即时绑定输入框） */
const searchTerm = ref('')
/** 状态筛选：all / active / inactive */
const statusFilter = ref<'all' | 'active' | 'inactive'>('all')
/** 当前页码 */
const currentPage = ref(1)
/** 每页条数 */
const perPage = 15

let searchTimer: ReturnType<typeof setTimeout> | null = null
/** 防抖后的搜索关键词，用于触发查询 */
const debouncedSearch = ref('')

/** 搜索输入防抖处理（300ms），避免频繁请求 */
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    debouncedSearch.value = searchTerm.value
    currentPage.value = 1
  }, 300)
}

onUnmounted(() => {
  if (searchTimer) clearTimeout(searchTimer)
})

/** 客户列表查询（服务端分页 + 搜索 + 状态筛选） */
const { data: result, isLoading, isFetching } = useQuery({
  queryKey: ['customers-list', () => debouncedSearch.value, () => statusFilter.value, () => currentPage.value],
  queryFn: () => customerApi.list({ per_page: perPage, page: currentPage.value, search: debouncedSearch.value || undefined, status: statusFilter.value !== 'all' ? statusFilter.value : undefined }),
  staleTime: 30_000,
  gcTime: 60_000,
  placeholderData: keepPreviousData,
})

/** 当前页客户列表（统一 status 为布尔值） */
const customers = computed<Customer[]>(() => {
  const raw = result.value?.customers ?? []
  return raw.map((c: Customer) => ({ ...c, status: c.status === true || String(c.status) === 'active' }))
})

/** 总记录数（用于分页） */
const totalItems = computed(() => result.value?.total ?? customers.value.length)
/** 总页数（至少为 1） */
const totalPages = computed(() => Math.ceil(totalItems.value / perPage) || 1)

// ===== 表单 =====
const formVisible = ref(false)
/** 表单模式：新增 / 编辑 */
const formMode = ref<'add' | 'edit'>('add')
const submitting = ref(false)
const form = reactive({ id: 0, name: '', contact: '', phone: '', address: '', note: '' })

/** 重置表单到初始状态 */
function resetForm() {
  Object.assign(form, { id: 0, name: '', contact: '', phone: '', address: '', note: '' })
}

/** 打开表单弹窗：新增模式清空表单，编辑模式填充行数据 */
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
/** 新增客户 */
const addMutation = useApiMutation((data: typeof form) => customerApi.create(data), {
  invalidateKeys: ['customers-list'],
  successMsg: '客户创建成功',
})

/** 编辑客户 */
const editMutation = useApiMutation((data: typeof form) => customerApi.update(data.id, data), {
  invalidateKeys: ['customers-list'],
  successMsg: '修改已保存',
})

/** 切换客户启用/停用状态 */
const toggleMutation = useApiMutation((id: number) => customerApi.toggleStatus(id), {
  invalidateKeys: ['customers-list'],
})

/** 删除客户 */
const deleteMutation = useApiMutation((id: number) => customerApi.delete(id), {
  invalidateKeys: ['customers-list'],
  successMsg: '客户已删除',
})
const confirmDialog = useConfirmDialog()

/** 提交表单：校验后执行新增或编辑 */
async function handleSubmit() {
  if (!form.name?.trim()) {
    showToast('客户名称不能为空', 'warning')
    return
  }
  if (form.phone && !/^[\d\-+\s()]{6,20}$/.test(form.phone)) {
    showToast('联系电话格式不正确', 'warning')
    return
  }
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

/** 当前操作中的客户 ID（用于禁用按钮） */
const actionId = ref<number | null>(null)

/** 切换客户状态（带确认对话框） */
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

/** 删除客户（带确认对话框） */
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
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */

/* Card Header */
/* 卡片头部样式已迁移到全局 .page-card-header（src/styles/app.css） */
.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.cu-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}
.cu-header-right {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
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

/* Tabs */
.cu-tabs {
  display: flex;
  gap: 4px;
  background: var(--color-surface, #f1f5f9);
  padding: 4px;
  border-radius: 11px;
}

.cu-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: color 0.3s ease, background 0.3s ease;
}

.cu-tab-btn:hover {
  color: var(--color-primary-600);
  background: rgba(255, 255, 255, 0.6);
}

.cu-tab-btn.active {
  background: white;
  color: var(--color-primary-600);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
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
  transition: border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
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
  background: white;
  font-size: 13px;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
}
.cu-search-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
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
  transition: background 0.2s ease, color 0.2s ease;
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
  transition: background 0.2s ease, color 0.2s ease;
  font-size: 13px;
}
.cu-icon-btn:hover { background: var(--color-border-light); }
.cu-icon-edit:hover { color: var(--color-primary-500); background: var(--color-primary-50); }
.cu-icon-toggle:hover { color: var(--color-warning-500); background: var(--color-warning-50); }
.cu-icon-delete:hover { color: var(--color-danger-500); background: var(--color-danger-50); }

/* Table Footer */
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

/* Fetching progress bar */
.cu-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.cu-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: cu-progress-slide 1s ease-in-out infinite;
}
@keyframes cu-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

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
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  font-family: inherit;
  color: var(--color-text);
  background: white;
}
.cu-form-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
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
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
}
.cu-form-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cu-form-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

/* Action Buttons (Section 10) */
.cu-action-btn {
  border-radius: 9px;
  padding: 7px 14px;
  border: 2px solid var(--color-border-light);
  background: white;
  font-size: 12px;
  font-weight: 600;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  cursor: pointer;
  color: var(--color-text);
  font-family: inherit;
}
.cu-action-btn:hover {
  transform: translateY(-1px);
}
.cu-action-primary {
  color: var(--color-primary-600);
}
.cu-action-primary:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
}
.cu-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
}

/* Responsive */
@media (max-width: 900px) {
  .cu-metrics { grid-template-columns: 1fr; gap: 8px; }
  .cu-form-grid { grid-template-columns: 1fr; }
}
</style>

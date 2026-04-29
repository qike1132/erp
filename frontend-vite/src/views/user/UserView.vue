<template>
  <div class="us-container">
    <div class="us-card us-card-main">
      <!-- 卡片头部 -->
      <div class="us-card-header">
        <HeaderTabs />
      </div>

      <!-- 双栏主体 -->
      <div class="us-body">
        <!-- 左栏：添加用户 -->
        <div class="us-col">
          <div class="us-col-title"><i class="fas fa-user-plus" /> 添加新用户</div>
          <div class="us-col-scroll">
            <form @submit.prevent="handleAdd" class="us-form">
              <div class="us-form-group">
                <label>用户名 <span class="us-required">*</span></label>
                <input v-model="form.username" class="us-input" placeholder="请输入用户名" />
              </div>
              <div class="us-form-group">
                <label>密码 <span class="us-required">*</span></label>
                <div class="us-input-wrapper">
                  <input v-model="form.password" :type="showPwd1 ? 'text' : 'password'" class="us-input" placeholder="至少6位" />
                  <button type="button" class="us-pwd-toggle" @click="showPwd1 = !showPwd1">
                    <i :class="showPwd1 ? 'fas fa-eye-slash' : 'fas fa-eye'" />
                  </button>
                </div>
              </div>
              <div class="us-form-group">
                <label>确认密码 <span class="us-required">*</span></label>
                <div class="us-input-wrapper">
                  <input v-model="form.confirmPassword" :type="showPwd2 ? 'text' : 'password'" class="us-input" placeholder="再次输入密码" />
                  <button type="button" class="us-pwd-toggle" @click="showPwd2 = !showPwd2">
                    <i :class="showPwd2 ? 'fas fa-eye-slash' : 'fas fa-eye'" />
                  </button>
                </div>
              </div>
              <p v-if="formError" class="us-form-error">{{ formError }}</p>
              <button type="submit" class="us-submit-btn" :disabled="submitting">
                {{ submitting ? '添加中...' : '添加用户' }}
              </button>
            </form>
          </div>
        </div>

        <!-- 右栏：用户列表 -->
        <div class="us-col">
          <div class="us-col-title">
            <i class="fas fa-list" /> 用户列表
            <span class="us-count-badge">{{ users.length }}</span>
          </div>
          <div class="us-col-scroll">
            <div v-if="isLoading" class="us-empty">
              <i class="fas fa-spinner fa-spin" />
              <span>加载中...</span>
            </div>
            <div v-else-if="users.length === 0" class="us-empty">
              <i class="fas fa-users" />
              <span>暂无用户</span>
            </div>
            <table v-else class="us-table">
              <thead>
                <tr>
                  <th>用户名</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in users" :key="row.id">
                  <td>{{ row.username }}</td>
                  <td>
                    <span :class="['us-badge', row.is_superuser ? 'us-badge-danger' : 'us-badge-info']">
                      {{ row.is_superuser ? '管理员' : '普通用户' }}
                    </span>
                  </td>
                  <td>
                    <span :class="['us-badge', row.is_active !== false ? 'us-badge-success' : 'us-badge-muted']">
                      {{ row.is_active !== false ? '启用' : '禁用' }}
                    </span>
                  </td>
                  <td>{{ row.created_at ? row.created_at.split('T')[0] : '-' }}</td>
                  <td style="white-space: nowrap">
                    <button class="us-action-btn us-action-primary" @click="openPermissionDialog(row)">权限</button>
                    <button class="us-action-btn us-action-primary" :disabled="actionId === row.id" @click="handleToggle(row)">
                      {{ row.is_active !== false ? '禁用' : '启用' }}
                    </button>
                    <button class="us-action-btn us-action-danger" :disabled="actionId === row.id || row.is_superuser" @click="handleDelete(row)">
                      删除
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- 权限分配弹窗 -->
    <UiDialog :open="permDialogVisible" title="分配权限" @update:open="permDialogVisible = $event">
      <div class="perm-tree">
        <template v-for="node in permissionTree" :key="node.id">
          <PermNode :node="node" :checked-keys="permCheckedKeys" @toggle="togglePermNode" />
        </template>
      </div>
      <template #footer>
        <button class="us-action-btn" @click="permDialogVisible = false">取消</button>
        <button class="us-action-btn us-action-primary" :disabled="permSubmitting" @click="handleSavePermission">
          {{ permSubmitting ? '保存中...' : '保存' }}
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
import { ref, reactive, computed, h, defineComponent } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { userApi, permissionApi } from '@/api'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import { showToast } from '@/composables/useToast'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'

// Recursive permission tree node
const PermNode = defineComponent({
  name: 'PermNode',
  props: { node: { type: Object, required: true }, checkedKeys: { type: Array as () => number[], required: true } },
  emits: ['toggle'],
  setup(props, { emit }) {
    return () => {
      const node = props.node
      const isChecked = props.checkedKeys.includes(node.id)
      const children = node.children?.length
        ? h(
            'div',
            { style: 'padding-left: 20px' },
            node.children.map((c: any) =>
              h(PermNode, { node: c, checkedKeys: props.checkedKeys, onToggle: (id: number) => emit('toggle', id) }),
            ),
          )
        : null
      return h('div', { style: 'margin-bottom: 4px' }, [
        h(
          'div',
          {
            style: 'display:flex;align-items:center;gap:8px;padding:4px 0;cursor:pointer',
            onClick: () => emit('toggle', node.id),
          },
          [
            h(UiCheckbox, { checked: isChecked, 'onUpdate:checked': () => emit('toggle', node.id) }),
            h('span', { style: 'font-size:13px' }, node.name),
          ],
        ),
        children,
      ])
    }
  },
})

const actionId = ref<number | ''>(0)
const formError = ref('')
const showPwd1 = ref(false)
const showPwd2 = ref(false)
const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()

const { data: result, isLoading } = useQuery({
  queryKey: ['users-list'],
  queryFn: () => userApi.list() as Promise<any>,
  staleTime: 30_000,
})
const users = computed(() => result.value?.items ?? result.value?.users ?? result.value?.data ?? [])

// 添加用户
const submitting = ref(false)
const form = reactive({ username: '', password: '', confirmPassword: '' })

async function handleAdd() {
  formError.value = ''
  if (!form.username) {
    formError.value = '请输入用户名'
    return
  }
  if (!form.password) {
    formError.value = '请输入密码'
    return
  }
  if (form.password.length < 6) {
    formError.value = '密码至少6位'
    return
  }
  if (form.password !== form.confirmPassword) {
    formError.value = '两次输入密码不一致'
    return
  }
  submitting.value = true
  try {
    await userApi.create({ username: form.username, password: form.password })
    showToast('添加成功', 'success')
    Object.assign(form, { username: '', password: '', confirmPassword: '' })
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '添加失败', 'error')
  } finally {
    submitting.value = false
  }
}

// 切换状态
async function handleToggle(row: any) {
  actionId.value = row.id
  try {
    await userApi.toggle(row.id)
    showToast('操作成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '操作失败', 'error')
  } finally {
    actionId.value = 0
  }
}

async function handleDelete(row: any) {
  if (!(await confirmDialog.confirm(`确定要删除用户"${row.username}"吗？`))) return
  actionId.value = row.id
  try {
    await userApi.delete(row.id)
    showToast('删除成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
  } catch (err: any) {
    showToast(err.response?.data?.detail || '删除失败', 'error')
  } finally {
    actionId.value = 0
  }
}

// 权限分配
const permDialogVisible = ref(false)
const permSubmitting = ref(false)
const permissionTree = ref<any[]>([])
const permCheckedKeys = ref<number[]>([])
const permTargetUserId = ref(0)

function togglePermNode(id: number) {
  const idx = permCheckedKeys.value.indexOf(id)
  if (idx >= 0) permCheckedKeys.value.splice(idx, 1)
  else permCheckedKeys.value.push(id)
}

async function openPermissionDialog(row: any) {
  permTargetUserId.value = row.id
  try {
    const [permRes, userPermRes] = await Promise.all([
      permissionApi.tree() as Promise<any>,
      userApi.getPermission(row.id) as Promise<any>,
    ])
    permissionTree.value = permRes.tree ?? permRes ?? []
    permCheckedKeys.value = (userPermRes.permission_ids ?? userPermRes.data ?? []) as number[]
    permDialogVisible.value = true
  } catch {
    showToast('加载权限数据失败', 'error')
  }
}

async function handleSavePermission() {
  permSubmitting.value = true
  try {
    await userApi.savePermission(permTargetUserId.value, permCheckedKeys.value)
    showToast('权限保存成功', 'success')
    permDialogVisible.value = false
  } catch (err: any) {
    showToast(err.response?.data?.detail || '保存失败', 'error')
  } finally {
    permSubmitting.value = false
  }
}
</script>

<style scoped>
/* Container */
.us-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card */
.us-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}
.us-card:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
}
.us-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* Card Header */
.us-card-header {
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: center;
  padding: 10px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  gap: 12px;
}
.us-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.us-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.us-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.us-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

/* Icon Box */
.us-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.us-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

/* Body */
.us-body {
  display: grid;
  grid-template-columns: 320px 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* Column */
.us-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.us-col + .us-col {
  border-left: 1px solid var(--color-border-light, #f1f5f9);
}
.us-col-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
}
.us-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}
.us-col-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding: 16px 20px;
}

/* Form */
.us-form {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.us-form-group {
  margin-bottom: 14px;
}
.us-form-group label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.us-required {
  color: var(--color-danger-500);
}
.us-input {
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
.us-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.us-input-wrapper {
  position: relative;
}
.us-pwd-toggle {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  cursor: pointer;
  color: var(--color-text-muted);
  padding: 4px;
  transition: color 0.2s ease;
}
.us-pwd-toggle:hover {
  color: var(--color-text-secondary);
}
.us-form-error {
  color: var(--color-danger-500);
  font-size: 12px;
  margin-bottom: 8px;
}
.us-submit-btn {
  width: 100%;
  padding: 10px 16px;
  border: none;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
}
.us-submit-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 148, 191, 0.3);
}
.us-submit-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Count Badge */
.us-count-badge {
  margin-left: auto;
  padding: 4px 12px;
  border-radius: 20px;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  font-size: 12px;
  font-weight: 600;
}

/* Badge */
.us-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}
.us-badge-info {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.us-badge-danger {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
}
.us-badge-success {
  background: var(--color-success-50);
  color: var(--color-success-600);
}
.us-badge-muted {
  background: var(--color-border-light, #f1f5f9);
  color: var(--color-text-muted);
}

/* Table */
.us-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.us-table thead th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  color: var(--color-text-secondary);
  text-align: left;
}
.us-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  transition: background 0.2s ease;
  color: var(--color-text);
}
.us-table tbody tr:hover {
  background: var(--color-primary-50);
}

/* Action Buttons */
.us-action-btn {
  padding: 5px 10px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  color: var(--color-text-secondary);
  margin-right: 4px;
}
.us-action-primary {
  color: var(--color-primary-600);
}
.us-action-primary:hover:not(:disabled) {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.us-action-danger {
  color: var(--color-danger-500);
}
.us-action-danger:hover:not(:disabled) {
  background: var(--color-danger-50);
  border-color: var(--color-danger-200);
  transform: translateY(-1px);
}
.us-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Empty State */
.us-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.us-empty i {
  font-size: 28px;
  opacity: 0.5;
}
.us-empty span {
  font-size: 14px;
}

/* Perm Tree */
.perm-tree {
  max-height: 400px;
  overflow-y: auto;
}
</style>

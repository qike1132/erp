<template>
  <!-- 编辑用户弹窗 -->
  <UiDialog :open="editDialogVisible" title="编辑用户" max-width-class="max-w-[480px]" @update:open="editDialogVisible = $event">
    <div class="us-edit-form">
      <div class="us-edit-username">用户名：{{ editTargetName }}</div>
      <div class="us-form-group">
        <label>新密码</label>
        <div class="us-input-wrapper">
          <input v-model="editForm.password" :type="showPwd ? 'text' : 'password'" class="us-input" :placeholder="`留空则不修改，至少${PASSWORD_MIN_LENGTH}位`" aria-label="新密码，留空则不修改" />
          <button type="button" class="us-pwd-toggle" aria-label="查看" @click="showPwd = !showPwd">
            <FontAwesomeIcon :icon="showPwd ? 'eye-slash' : 'eye'" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div class="us-form-group">
        <label>工厂</label>
        <select v-model="editForm.factory" class="us-input" aria-label="工厂">
          <option value="">无（跨厂管理员）</option>
          <option v-for="f in FACTORY_OPTIONS" :key="f" :value="f">{{ f }}</option>
        </select>
      </div>
    </div>
    <template #footer>
      <button class="us-action-btn" aria-label="取消" @click="editDialogVisible = false">取消</button>
      <button class="us-action-btn us-action-primary" :disabled="editSubmitting" :aria-label="editSubmitting ? '保存中…' : '保存'" @click="handleSaveEdit">
        {{ editSubmitting ? '保存中…' : '保存' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * UserEditDialog.vue — 编辑用户弹窗
 *
 * 从 UserView.vue 拆出：展示用户名 + 重置密码（留空不改）+ 编辑所属工厂并保存。
 * 弹窗打开时从 initialFactory 同步初值。
 */
import { ref, reactive, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { userApi } from '@/api'
import type { UserUpdate } from '@/types'
import UiDialog from '@/components/ui/UiDialog.vue'
import { showToast } from '@/composables/useToast'
import { FACTORY_OPTIONS, PASSWORD_MIN_LENGTH, extractErrorMessage } from '@/views/user/composables/useUserManagement'

const props = defineProps<{
  /** 编辑目标用户 id */
  editTargetId: number
  /** 编辑目标用户名（弹窗内展示） */
  editTargetName: string
  /** 打开弹窗时的工厂初值 */
  initialFactory: string
}>()

/** 弹窗开关（父组件 v-model:open） */
const editDialogVisible = defineModel<boolean>('open', { default: false })

const queryClient = useQueryClient()

const editSubmitting = ref(false)
const showPwd = ref(false)
const editForm = reactive<{ factory: string; password: string }>({ factory: '', password: '' })

// 弹窗打开时预填当前工厂值并清空密码
watch(editDialogVisible, (v) => {
  if (v) {
    editForm.factory = props.initialFactory
    editForm.password = ''
    showPwd.value = false
  }
})

/** 保存用户工厂/密码编辑 */
async function handleSaveEdit() {
  const payload: UserUpdate = { factory: editForm.factory || null }
  // 密码留空表示不修改；填了则校验长度（与新增用户保持一致）
  if (editForm.password) {
    if (editForm.password.length < PASSWORD_MIN_LENGTH) {
      showToast(`密码至少 ${PASSWORD_MIN_LENGTH} 位`, 'error')
      return
    }
    payload.password = editForm.password
  }
  editSubmitting.value = true
  try {
    await userApi.update(props.editTargetId, payload)
    showToast('保存成功', 'success')
    editDialogVisible.value = false
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, '保存失败'), 'error')
  } finally {
    editSubmitting.value = false
  }
}
</script>

<style scoped>
/* Edit Dialog */
.us-edit-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.us-edit-username {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  padding: 8px 0;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
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
.us-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  font-family: inherit;
  color: var(--color-text);
  background: white;
}
.us-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
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

/* Action Buttons */
.us-action-btn {
  padding: 5px 10px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
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
.us-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>

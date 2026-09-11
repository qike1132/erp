<template>
  <div class="us-col-title"><FontAwesomeIcon icon="user-plus" aria-hidden="true" /> 添加新用户</div>
  <div class="us-col-scroll">
    <form class="us-form" @submit.prevent="handleAdd">
      <div class="us-form-group">
        <label>用户名 <span class="us-required">*</span></label>
        <input v-model="form.username" class="us-input" placeholder="请输入用户名" aria-label="请输入用户名" />
      </div>
      <div class="us-form-group">
        <label>密码 <span class="us-required">*</span></label>
        <div class="us-input-wrapper">
          <input v-model="form.password" :type="showPwd1 ? 'text' : 'password'" class="us-input" placeholder="至少8位，含大小写字母和数字" aria-label="至少8位，含大小写字母和数字" />
          <button type="button" class="us-pwd-toggle" aria-label="查看" @click="showPwd1 = !showPwd1">
            <FontAwesomeIcon :icon="showPwd1 ? 'eye-slash' : 'eye'" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div class="us-form-group us-form-group-row">
        <UiCheckbox :checked="form.isSuper" @update:checked="form.isSuper = $event" />
        <label class="us-checkbox-label" @click="form.isSuper = !form.isSuper">超级管理员</label>
      </div>
      <div class="us-form-group">
        <label>工厂</label>
        <select v-model="form.factory" class="us-input" aria-label="工厂">
          <option value="">无（跨厂管理员）</option>
          <option v-for="f in FACTORY_OPTIONS" :key="f" :value="f">{{ f }}</option>
        </select>
      </div>
      <p v-if="formError" class="us-form-error">{{ formError }}</p>
      <button type="submit" class="us-submit-btn" :disabled="submitting" :aria-label="submitting ? '添加中…' : '添加用户'">
        {{ submitting ? '添加中…' : '添加用户' }}
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
/**
 * UserCreateForm.vue — 添加新用户表单（左栏）
 *
 * 从 UserView.vue 拆出：用户名/密码/超级管理员/工厂输入与提交校验。
 */
import { ref, reactive } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { userApi } from '@/api'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import { showToast } from '@/composables/useToast'
import { FACTORY_OPTIONS, extractErrorMessage } from '@/views/user/composables/useUserManagement'

const queryClient = useQueryClient()

const formError = ref('')
const showPwd1 = ref(false)
const submitting = ref(false)
const form = reactive({ username: '', password: '', isSuper: false, factory: '' })

/**
 * 密码复杂度校验：至少 8 位，且需同时包含大写字母、小写字母、数字。
 * @returns 错误提示字符串；通过校验返回 null
 */
function validatePasswordComplexity(password: string): string | null {
  if (password.length < 8) return '密码至少 8 位'
  if (!/[A-Z]/.test(password)) return '密码需包含大写字母'
  if (!/[a-z]/.test(password)) return '密码需包含小写字母'
  if (!/[0-9]/.test(password)) return '密码需包含数字'
  return null
}

/** 提交添加用户表单 */
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
  const pwdErr = validatePasswordComplexity(form.password)
  if (pwdErr) {
    formError.value = pwdErr
    return
  }
  submitting.value = true
  try {
    await userApi.create({
      username: form.username,
      password: form.password,
      is_super: form.isSuper,
      factory: form.factory || null,
    })
    showToast('添加成功', 'success')
    Object.assign(form, { username: '', password: '', isSuper: false, factory: '' })
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, '添加失败'), 'error')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
/* 左栏标题 */
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
.us-form-group-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.us-checkbox-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  cursor: pointer;
  user-select: none;
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
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.us-submit-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 148, 191, 0.3);
}
.us-submit-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>

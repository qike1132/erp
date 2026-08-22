<template>
  <div class="login-section">
    <div class="login-card">
      <div class="login-card-header">
        <h2 class="login-heading">欢迎登录</h2>
        <p class="login-subheading">请输入您的账号信息以访问系统</p>
      </div>

      <form class="login-form" @submit.prevent="handleLogin">
        <div class="form-group">
          <label class="form-label">用户名</label>
          <div class="input-wrapper">
            <FontAwesomeIcon icon="user" class="input-prefix-icon" aria-hidden="true" />
            <input
              v-model="form.username"
              type="text"
              name="username"
              placeholder="请输入用户名"
              autocomplete="username"
              required
              class="form-input with-prefix"
            />
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">密码</label>
          <div class="input-wrapper">
            <FontAwesomeIcon icon="lock" class="input-prefix-icon" aria-hidden="true" />
            <input
              v-model="form.password"
              :type="showPassword ? 'text' : 'password'"
              name="password"
              placeholder="请输入密码"
              autocomplete="current-password"
              required
              class="form-input with-prefix with-suffix"
              aria-describedby="login-error-msg"
            />
            <button type="button" class="input-suffix-btn" aria-label="切换密码可见性" @click="showPassword = !showPassword">
              <FontAwesomeIcon :icon="showPassword ? 'eye-slash' : 'eye'" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div class="remember-row">
          <label class="remember-label">
            <UiCheckbox v-model:checked="form.remember" />
            <span>记住我</span>
          </label>
        </div>

        <div v-if="errorMsg" id="login-error-msg" class="login-error-msg">{{ errorMsg }}</div>

        <button type="submit" class="btn-login" :disabled="loading" :aria-label="loading ? '登录中…' : '安全登录'">
          <FontAwesomeIcon v-if="!loading" icon="right-to-bracket" style="margin-right: 6px" aria-hidden="true" />
          {{ loading ? '登录中…' : '安全登录' }}
        </button>
      </form>

      <div class="login-footer">
        <p class="footer-text">滨发玩具供应链管理系统</p>
        <p class="footer-version">v2.0</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiCheckbox from '@/components/ui/UiCheckbox.vue'

defineProps<{
  loading: boolean
  errorMsg: string
  handleLogin: () => Promise<void> | void
}>()

// 显式双向绑定：父组件 v-model:form 传入，子组件就地编辑表单字段（合法替代直接改 props）
const form = defineModel<{ username: string; password: string; remember: boolean }>('form', { required: true })

const showPassword = defineModel<boolean>('showPassword', { default: false })
</script>

<style scoped>
.login-section {
  flex: 0.9;
  background: var(--color-surface);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  padding: 78px;
}

.login-card {
  width: 100%;
  max-width: 460px;
  background: var(--color-surface-card);
  border-radius: var(--radius-xl);
  padding: 52px 48px;
  box-shadow: var(--shadow-lg, 0 8px 32px rgba(0, 0, 0, 0.1));
  animation: fadeInUp 0.3s ease both;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.login-card-header { margin-bottom: 40px; }

.login-heading {
  font-size: 30px;
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: 10px;
}

.login-subheading {
  font-size: 16px;
  color: var(--color-text-secondary);
}

.form-label {
  display: block;
  font-size: 15px;
  font-weight: 500;
  color: var(--color-text);
  margin-bottom: 8px;
}

.remember-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.btn-login {
  width: 100%;
  height: 48px;
  font-size: 17px;
  font-weight: 600;
  border-radius: var(--radius-md);
  background: var(--color-ocean-deep);
  border-color: var(--color-ocean-deep);
  color: var(--color-surface-card);
  border: none;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.btn-login:hover,
.btn-login:focus {
  background: color-mix(in srgb, var(--color-ocean-deep) 85%, black);
  border-color: color-mix(in srgb, var(--color-ocean-deep) 85%, black);
}

.btn-login:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.login-footer {
  text-align: center;
  margin-top: 40px;
  padding-top: 32px;
  border-top: 1px solid var(--color-border);
}

.footer-text {
  font-size: 16px;
  color: var(--color-text-muted);
}

.footer-version {
  font-size: 14px;
  color: var(--color-text-muted);
  margin-top: 5px;
}

.login-form .form-group { margin-bottom: 22px; }

.input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.input-prefix-icon {
  position: absolute;
  left: 12px;
  color: var(--color-text-muted);
  font-size: 14px;
  pointer-events: none;
}

.input-suffix-btn {
  position: absolute;
  right: 8px;
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 4px 8px;
  font-size: 14px;
}

.input-suffix-btn:hover {
  color: var(--color-text-secondary);
}

.form-input {
  width: 100%;
  padding: 12px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 15px;
  color: var(--color-text);
  background: var(--color-surface-card);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.form-input:focus {
  outline: none;
  border-color: var(--color-ocean-deep);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-ocean-deep) 20%, transparent);
}
.form-input:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
}

.form-input::placeholder {
  color: var(--color-text-muted);
}

.form-input.with-prefix { padding-left: 40px; }
.form-input.with-suffix { padding-right: 40px; }

.remember-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 14px;
  color: var(--color-text-secondary);
}

.login-error-msg {
  color: var(--color-danger-600);
  font-size: 13px;
  margin-bottom: 8px;
  padding: 8px 12px;
  background: var(--color-danger-50);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-danger-200);
}

@media (max-width: 1024px) {
  .login-section { padding: 48px; }
  .login-card { padding: 40px 36px; }
}

@media (max-width: 768px) {
  .login-section { padding: 40px 24px; flex: 1; }
  .login-card { padding: 36px 28px; }
}

@media (max-width: 480px) {
  .login-card { padding: 32px 24px; border-radius: var(--radius-xl); }
  .login-heading { font-size: 22px; }
}
</style>
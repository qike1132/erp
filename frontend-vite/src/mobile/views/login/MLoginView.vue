<template>
  <div class="m-login">
    <div class="m-login-header">
      <div class="m-login-logo">
        <svg viewBox="0 0 48 48" fill="none" width="56" height="56">
          <rect width="48" height="48" rx="14" fill="var(--m-accent)" />
          <path d="M14 16h20M14 24h20M14 32h12" stroke="white" stroke-width="2.5" stroke-linecap="round" />
        </svg>
      </div>
      <h1 class="m-login-title">滨发协同</h1>
      <p class="m-login-desc">ERP协同管理系统</p>
    </div>

    <form class="m-login-form" @submit.prevent="handleLogin">
      <div class="m-login-field">
        <input
          v-model="username"
          type="text"
          class="m-login-input"
          placeholder="用户名"
          autocomplete="username"
          inputmode="text"
          :disabled="submitting"
        />
      </div>
      <div class="m-login-field">
        <input
          v-model="password"
          type="password"
          class="m-login-input"
          placeholder="密码"
          autocomplete="current-password"
          :disabled="submitting"
        />
      </div>

      <p v-if="errorMsg" class="m-login-error">{{ errorMsg }}</p>

      <button type="submit" class="m-login-btn" :disabled="submitting || !username || !password">
        <template v-if="submitting">
          <span class="m-login-spinner" />
          登录中…
        </template>
        <template v-else>登 录</template>
      </button>
    </form>

    <p class="m-login-footer">v{{ appVersion }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const submitting = ref(false)
const errorMsg = ref('')
const appVersion = '1.0.0'

async function handleLogin() {
  errorMsg.value = ''
  submitting.value = true

  try {
    await authApi.login({ username: username.value, password: password.value })
    await authStore.init()
    await authStore.fetchNavSections()

    const redirect = (route.query.redirect as string) || '/m'
    router.replace(redirect)
  } catch (e: unknown) {
    const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    errorMsg.value = msg || '登录失败，请检查用户名和密码'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.m-login {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  min-height: 100dvh;
  padding: 40px 28px;
  padding-top: calc(var(--m-safe-top) + 40px);
  padding-bottom: calc(var(--m-safe-bottom) + 40px);
  background: var(--m-bg-deep);
}

.m-login-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 40px;
}

.m-login-logo {
  margin-bottom: 20px;
}

.m-login-title {
  font-size: var(--m-font-display-md);
  font-weight: 800;
  color: var(--m-text-primary);
  margin: 0;
  letter-spacing: -0.5px;
}

.m-login-desc {
  font-size: var(--m-font-body);
  color: var(--m-text-secondary);
  margin: 6px 0 0;
  font-weight: 500;
}

.m-login-form {
  width: 100%;
  max-width: 360px;
}

.m-login-field {
  margin-bottom: 14px;
}

.m-login-input {
  width: 100%;
  padding: 14px 16px;
  font-size: var(--m-font-body-lg);
  font-family: inherit;
  color: var(--m-text-primary);
  background: var(--m-bg-surface);
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: var(--m-radius-input-lg);
  outline: none;
  transition: border-color 0.2s var(--m-ease-smooth), box-shadow 0.2s var(--m-ease-smooth);
  box-sizing: border-box;
  -webkit-appearance: none;
}

.m-login-input::placeholder {
  color: var(--m-text-tertiary);
}
.m-login-input:focus {
  border-color: var(--m-accent);
  box-shadow: 0 0 0 3px var(--m-accent-glow);
}

.m-login-error {
  font-size: var(--m-font-body-sm);
  color: var(--m-accent-red);
  margin: 0 0 14px;
  text-align: center;
  padding: 10px 14px;
  background: var(--m-error-light);
  border-radius: var(--m-radius-md);
}

.m-login-btn {
  width: 100%;
  padding: 14px;
  margin-top: 8px;
  font-size: var(--m-font-title);
  font-weight: var(--m-font-weight-semibold);
  font-family: inherit;
  color: white;
  background: var(--m-accent);
  border: none;
  border-radius: var(--m-radius-button-md);
  cursor: pointer;
  transition: opacity 0.2s var(--m-ease-smooth), transform 0.2s var(--m-ease-spring);
  -webkit-tap-highlight-color: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.m-login-btn:active {
  transform: scale(0.97);
}
.m-login-btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.m-login-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: m-spin 0.7s linear infinite;
}

@keyframes m-spin {
  to { transform: rotate(360deg); }
}

.m-login-footer {
  margin-top: 40px;
  font-size: var(--m-font-label-sm);
  color: var(--m-text-tertiary);
}
</style>

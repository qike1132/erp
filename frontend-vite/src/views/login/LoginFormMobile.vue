<template>
  <div class="m-login-page">
    <div class="m-login-logo-area">
      <img loading="lazy" class="m-login-logo" src="/logo_plush.png" alt="滨发协同系统" />
      <div class="m-login-title">滨发协同系统</div>
      <div class="m-login-sub">Binfa Collaboration System</div>
    </div>

    <div class="m-login-form-area">
      <form @submit.prevent="handleLogin">
        <div class="m-login-field">
          <label>用户名</label>
          <input
            v-model="form.username"
            type="text"
            placeholder="请输入用户名"
            autocomplete="username"
            required
          />
        </div>
        <div class="m-login-field">
          <label>密码</label>
          <div class="m-login-pwd-wrapper">
            <input
              v-model="form.password"
              :type="showPassword ? 'text' : 'password'"
              placeholder="请输入密码"
              autocomplete="current-password"
              required
              aria-describedby="m-login-error-msg"
            />
            <button
              class="m-login-pwd-toggle"
              type="button"
              aria-label="切换密码可见性"
              @click="showPassword = !showPassword"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path v-if="!showPassword" d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                <circle v-if="!showPassword" cx="12" cy="12" r="3" />
                <path v-if="showPassword" d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                <path v-if="showPassword" d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                <line v-if="showPassword" x1="1" y1="1" x2="23" y2="23" />
              </svg>
            </button>
          </div>
        </div>
        <div v-if="errorMsg" id="m-login-error-msg" class="m-login-error-msg show">{{ errorMsg }}</div>
        <div class="m-login-btn-area">
          <button type="submit" class="m-login-btn" :disabled="loading" aria-label="登录">
            <span v-if="!loading">登录</span>
            <span v-else class="m-login-spinner"></span>
          </button>
        </div>
      </form>
    </div>

    <div class="m-login-footer">东莞玩具供应链管理系统</div>
  </div>
</template>

<script setup lang="ts">
import { useLogin } from './useLogin'

const { loading, showPassword, errorMsg, form, handleLogin } = useLogin()
</script>

<style scoped>
.m-login-page {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #FFFFFF;
  z-index: 100;
  padding: 0;
}

.m-login-logo-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 60px;
  padding-bottom: 24px;
  flex-shrink: 0;
}

.m-login-logo {
  width: 80px;
  height: 80px;
  border-radius: 22px;
  margin-bottom: 16px;
}

.m-login-title {
  font-size: 24px;
  font-weight: 700;
  color: #1C1C1E;
  letter-spacing: -0.3px;
}

.m-login-sub {
  font-size: 13px;
  color: #8E8E93;
  margin-top: 4px;
  font-weight: 500;
}

.m-login-form-area {
  width: 100%;
  flex: 1;
  padding: 32px 24px 0;
  overflow-y: auto;
}

.m-login-field {
  margin-bottom: 20px;
}

.m-login-field label {
  display: block;
  font-size: 15px;
  font-weight: 600;
  color: #1C1C1E;
  margin-bottom: 8px;
}

.m-login-field input {
  width: 100%;
  height: 50px;
  padding: 0 16px;
  border: 1px solid #E5E5EA;
  border-radius: 12px;
  font-size: 16px;
  color: #1C1C1E;
  background: #F9F9FB;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
  font-family: -apple-system, 'SF Pro Text', 'Inter', 'Noto Sans SC', sans-serif;
}

.m-login-field input:focus {
  border-color: #0071E3;
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.15);
}

.m-login-field input::placeholder {
  color: #C7C7CC;
}

.m-login-pwd-wrapper {
  position: relative;
}

.m-login-pwd-toggle {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  padding: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
}

.m-login-pwd-toggle svg {
  width: 22px;
  height: 22px;
  color: var(--m-text-tertiary, #AEAEB2);
}

.m-login-error-msg {
  color: #FF3B30;
  font-size: 13px;
  margin-top: 0;
  margin-bottom: 4px;
  display: none;
}

.m-login-error-msg.show {
  display: block;
}

.m-login-btn-area {
  width: 100%;
  padding: 32px 24px 0;
  flex-shrink: 0;
}

.m-login-btn {
  width: 100%;
  height: 52px;
  border: none;
  border-radius: 14px;
  background: var(--m-accent, #0071E3);
  color: white;
  font-size: 17px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.3s var(--m-ease-spring, cubic-bezier(0.175, 0.885, 0.32, 1.275)),
              box-shadow 0.3s var(--m-ease-smooth, cubic-bezier(0.25, 0.1, 0.25, 1));
  font-family: -apple-system, 'SF Pro Text', 'Inter', 'Noto Sans SC', sans-serif;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 14px rgba(0, 113, 227, 0.25);
}

.m-login-btn:active {
  transform: scale(0.97);
}

.m-login-btn:disabled {
  opacity: 1;
  cursor: not-allowed;
}

.m-login-spinner {
  width: 24px;
  height: 24px;
  border: 2.5px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: m-spin 0.7s linear infinite;
}

@keyframes m-spin {
  to { transform: rotate(360deg); }
}

.m-login-footer {
  flex: 1;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding-bottom: 24px;
  font-size: 14px;
  color: #999999;
  flex-shrink: 0;
}
</style>

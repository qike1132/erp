<template>
  <!-- 移动端：Apple 极简登录 -->
  <LoginFormMobile v-if="isMobile" />
  <!-- PC 端：左右分栏登录 -->
  <LoginFormPc v-else />
</template>

<script setup lang="ts">
import LoginFormPc from './LoginFormPc.vue'
import LoginFormMobile from './LoginFormMobile.vue'
import { isMobileDevice } from '@/composables/useDevice'

const isMobile = isMobileDevice()
</script>

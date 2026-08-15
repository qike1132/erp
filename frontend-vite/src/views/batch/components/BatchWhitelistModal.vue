<template>
  <!-- 白名单设置弹窗 -->
  <div v-if="showWhitelistModal" class="bt-whitelist-overlay" @click.self="showWhitelistModal = false">
    <div class="bt-whitelist-modal">
      <div class="bt-whitelist-header">
        <span>白名单客户</span>
        <button class="bt-whitelist-close" @click="showWhitelistModal = false">&times;</button>
      </div>
      <div class="bt-whitelist-body">
        <label v-for="c in allCustomers" :key="c" class="bt-whitelist-item">
          <input type="checkbox" :value="c" v-model="whitelistEdit" />
          <span>{{ c }}</span>
        </label>
      </div>
      <div class="bt-whitelist-footer">
        <UiButton variant="outline" @click="showWhitelistModal = false">取消</UiButton>
        <UiButton variant="primary" @click="saveWhitelist" :disabled="whitelistSaving">保存</UiButton>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BatchWhitelistModal.vue — 白名单客户设置弹窗
 *
 * 从 BatchView.vue 拆出：勾选启用客户并保存为批次页白名单。
 * 保存成功后 emit('saved')，由父组件刷新白名单与主列表。
 */
import { ref, watch } from 'vue'
import { orderBatchApi } from '@/api'
import UiButton from '@/components/ui/UiButton.vue'
import { showToast } from '@/composables/useToast'

const props = defineProps<{
  /** 当前白名单客户（打开弹窗时的初始勾选） */
  customers: string[]
  /** 全部启用客户（候选清单） */
  allCustomers: string[]
}>()

const emit = defineEmits<{
  /** 保存成功后刷新数据 */
  saved: []
}>()

/** 弹窗开关（父组件 v-model:open） */
const showWhitelistModal = defineModel<boolean>('open', { default: false })

// ---- Whitelist modal ----
const whitelistEdit = ref<string[]>([])
const whitelistSaving = ref(false)

// When modal opens, populate edit list from current whitelist
watch(showWhitelistModal, (val) => {
  if (val) {
    whitelistEdit.value = [...props.customers]
  }
})

/** 保存白名单客户列表 */
async function saveWhitelist() {
  whitelistSaving.value = true
  try {
    await orderBatchApi.setWhitelist(whitelistEdit.value)
    showToast('白名单已更新', 'success')
    showWhitelistModal.value = false
    emit('saved')
  } catch {
    showToast('白名单更新失败', 'error')
  } finally {
    whitelistSaving.value = false
  }
}
</script>

<style scoped>
/* ===== 白名单弹窗 ===== */
.bt-whitelist-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.bt-whitelist-modal {
  background: white;
  border-radius: 16px;
  width: 360px;
  max-height: 480px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}
.bt-whitelist-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  font-size: 15px;
  font-weight: 700;
  border-bottom: 1px solid var(--color-border-light);
}
.bt-whitelist-close {
  background: none;
  border: none;
  font-size: 20px;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
}
.bt-whitelist-body {
  padding: 12px 20px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.bt-whitelist-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 14px;
  color: var(--color-text);
  cursor: pointer;
}
.bt-whitelist-item input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary-500);
  cursor: pointer;
}
.bt-whitelist-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--color-border-light);
}
</style>

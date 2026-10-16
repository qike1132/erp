<template>
  <!-- 白名单设置弹窗（共享 UiDialog：Esc / 焦点陷阱 / 滚动锁内建；点遮罩空白不关闭） -->
  <UiDialog
    :open="showWhitelistModal"
    title="白名单客户"
    max-width-class="max-w-[360px]"
    overlay-z-class="z-[var(--z-page-modal)]"
    content-z-class="z-[var(--z-page-modal)] bt-whitelist-card"
    body-class="bt-whitelist-pane"
    :body-padded="false"
    @update:open="showWhitelistModal = $event"
  >
    <div class="bt-whitelist-body">
      <label v-for="c in allCustomers" :key="c" class="bt-whitelist-item">
        <input v-model="whitelistEdit" type="checkbox" :value="c" :aria-label="`启用客户 ${c}`" />
        <span>{{ c }}</span>
      </label>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="showWhitelistModal = false">取消</UiButton>
      <UiButton variant="primary" :disabled="whitelistSaving" @click="saveWhitelist">保存</UiButton>
    </template>
  </UiDialog>
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
import UiDialog from '@/components/ui/UiDialog.vue'
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
/* 外壳（遮罩 / 卡片 / 头部 / 关闭 / 底栏）由共享 UiDialog 提供 */
.bt-whitelist-body {
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
</style>

<!-- 卡片与 body 由 UiDialog 渲染并 portal 到 body → 全局维持迁移前的最大高度与内边距 -->
<style>
.bt-whitelist-card {
  max-height: 480px !important;
}
.bt-whitelist-pane {
  padding: 12px 20px;
}
</style>

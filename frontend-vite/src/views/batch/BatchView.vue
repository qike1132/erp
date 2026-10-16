<template>
  <div class="bt-container">
    <div class="page-card page-card-main">

      <!-- 卡片头部 -->
      <div class="page-card-header">
        <span v-if="whitelistCustomers.length" class="bt-tab-group" role="tablist">
          <button
            v-for="c in whitelistCustomers"
            :key="c"
            role="tab"
            :aria-selected="filters.customer === c"
            class="bt-tab-btn"
            :class="{ 'bt-tab-btn--active': filters.customer === c }"
            @click="switchCustomer(c)"
          >{{ c }}</button>
        </span>
        <div class="bt-header-search">
          <UiInput v-model="filters.keyword" placeholder="搜索" style="width: 160px" />
          <UiButton variant="primary" @click="refetch()"> 查询 </UiButton>
          <button class="bt-whitelist-btn" aria-label="设置" @click="showWhitelistModal = true">
            <FontAwesomeIcon icon="cog" aria-hidden="true" />
          </button>
        </div>
        <!-- 白名单设置弹窗（拆分为子组件） -->
        <BatchWhitelistModal
          v-model:open="showWhitelistModal"
          :customers="whitelistCustomers"
          :all-customers="allCustomers"
          @saved="refreshAfterWhitelistSaved"
        />
        <!-- 完成批次确认弹窗（共享 UiDialog：Esc / 焦点陷阱 / 滚动锁内建；点遮罩空白不关闭） -->
        <UiDialog
          :open="showCompleteModal"
          title="确认完成批次"
          max-width-class="max-w-[360px]"
          overlay-z-class="z-[var(--z-page-modal)]"
          content-z-class="z-[var(--z-page-modal)] bt-complete-card"
          @update:open="showCompleteModal = $event"
        >
          <div class="bt-complete-body">
            确定要完成批次 <strong>{{ completingBatchNo }}</strong> 吗？完成后该批次将不再显示。
          </div>
          <template #footer>
            <UiButton variant="outline" @click="showCompleteModal = false">取消</UiButton>
            <UiButton variant="primary" :disabled="completing" @click="confirmComplete">确定</UiButton>
          </template>
        </UiDialog>
      </div>

      <!-- 主内容 -->
      <div class="page-card-main">
        <div v-if="isLoading && !result" class="bt-loading">
          <UiSpinner />
        </div>
        <template v-else>
          <div v-if="isFetching" class="bt-fetching-bar"><div class="bt-fetching-progress" /></div>

          <!-- 客户分组卡片（拆分为子组件） -->
          <BatchGroupList
            v-if="grouped.length"
            :grouped="grouped"
            @refresh="refetch()"
            @request-complete="openCompleteConfirm"
          />
          <div v-else class="bt-empty">
            <FontAwesomeIcon icon="inbox" aria-hidden="true" />
            <span>暂无批次数据</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BatchView.vue — 批次管理页面
 *
 * 职责：
 * - 按客户白名单分组展示订单/备货记录
 * - 支持内联编辑批次号、完成批次操作
 * - 支持白名单客户的增删管理
 *
 * 数据/分组/完成批次逻辑下沉到 composables/useBatchQuery.ts，
 * 分组列表拆分为 components/BatchGroupList.vue，
 * 白名单弹窗拆分为 components/BatchWhitelistModal.vue。
 */
import { ref } from 'vue'
import UiInput from '@/components/ui/UiInput.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import BatchGroupList from '@/views/batch/components/BatchGroupList.vue'
import BatchWhitelistModal from '@/views/batch/components/BatchWhitelistModal.vue'
import { useBatchQuery } from '@/views/batch/composables/useBatchQuery'

// ---- Whitelist modal 开关（弹窗子组件 v-model:open） ----
const showWhitelistModal = ref(false)

const {
  filters,
  result,
  whitelistCustomers,
  allCustomers,
  isLoading,
  isFetching,
  refetch,
  grouped,
  switchCustomer,
  refreshAfterWhitelistSaved,
  showCompleteModal,
  completingBatchNo,
  completing,
  openCompleteConfirm,
  confirmComplete,
} = useBatchQuery()
</script>

<style scoped>
/* ===== 容器 (Section 1) ===== */
.bt-container {
  padding: 0;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  /* 页面整体禁止文本选中，避免鼠标拖动时整页高亮 */
  user-select: none;
  -webkit-user-select: none;
}
/* 容器内的输入框/文本域仍需可选中、可编辑 */
.bt-container :deep(input),
.bt-container :deep(textarea) {
  user-select: text;
  -webkit-user-select: text;
}

/* ===== 卡片 (Section 3) ===== */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */

/* ===== 卡片头部 (Section 4) ===== */
/* 卡片头部样式已迁移到全局 .page-card-header（src/styles/app.css） */

.bt-card-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}
.bt-card-title-group h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.bt-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin: 0;
}

/* ===== 图标色块 (Section 8) ===== */
.bt-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.bt-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-600);
}

/* ===== 头部操作区 ===== */
/* 搜索 + 查询 + 设置 作为一组贴右上角（左侧留给客户 tab） */
.bt-header-search {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  flex-shrink: 0;
}

/* ===== TAB 切换栏 (Section 23) ===== */
.bt-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}

.bt-tab-btn {
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  font-family: inherit;
}
.bt-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.bt-tab-btn--active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* ===== 卡片主体 (Section 3 overflow) ===== */
/* 卡片主体样式已迁移到全局 .page-card-main（src/styles/app.css） */

/* ===== 加载状态 (Section 18) ===== */
.bt-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
}

/* ===== 空状态 (Section 18) ===== */
.bt-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  font-size: 14px;
  color: var(--color-text-muted);
}
.bt-empty i {
  font-size: 28px;
  opacity: 0.5;
}

/* ===== 白名单设置按钮 ===== */
.bt-whitelist-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: background 0.2s ease, transform 0.2s ease;
}
.bt-whitelist-btn:hover {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}

/* ===== 完成批次确认弹窗（外壳由共享 UiDialog 提供） ===== */
.bt-complete-body {
  font-size: 14px;
  color: var(--color-text);
}

/* ===== Fetching bar ===== */
.bt-fetching-bar {
  height: 2px;
  background: var(--color-primary-100);
  overflow: hidden;
  margin: 0 24px;
  border-radius: 1px;
}
.bt-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500);
  border-radius: 1px;
  animation: bt-progress-slide 1s ease-in-out infinite;
}
@keyframes bt-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .page-card-header {
    padding: 12px 16px 8px;
  }
  .bt-filterbar {
    padding: 0 16px 12px;
  }
}
</style>

<!-- 卡片与 body 由 UiDialog 渲染并 portal 到 body → 全局维持迁移前的最大高度与内边距 -->
<style>
.bt-complete-card {
  max-height: 480px !important;
}
.bt-complete-card > .p-6 {
  padding: 20px !important;
}
</style>

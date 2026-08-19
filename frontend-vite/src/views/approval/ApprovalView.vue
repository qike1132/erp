<template>
  <div class="ap-container">
    <div class="page-card page-card-main">
      <ApprovalStatsBar :stats="stats" />
      <ApprovalFilterBar
        v-model:search-term="searchTerm"
        v-model:status-filter="statusFilter"
        :status-options="statusOptions"
        @search="onSearchInput"
        @clear="clearSearch"
      />
      <ApprovalTable
        :items="items"
        :is-loading="isLoading"
        :action-id="actionId"
        :total-items="totalItems"
        :per-page="perPage"
        :current-page="currentPage"
        :total-pages="totalPages"
        :status-badge-class="statusBadgeClass"
        :status-label="statusLabel"
        @approve="handleApprove"
        @reject="openRejectDialog"
        @page="goPage"
      />
    </div>

    <RejectDialog
      v-model:open="rejectDialogVisible"
      v-model:reason="rejectReason"
      :saving="rejectSaving"
      @confirm="handleReject"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * ApprovalView.vue — 审批管理页面
 *
 * 职责：
 * - 展示待审批/已通过/已驳回的审批记录统计
 * - 支持按状态筛选和关键词搜索
 * - 审批通过操作与驳回弹窗（需填写驳回原因）
 */
import ApprovalStatsBar from './components/ApprovalStatsBar.vue'
import ApprovalFilterBar from './components/ApprovalFilterBar.vue'
import ApprovalTable from './components/ApprovalTable.vue'
import RejectDialog from './components/RejectDialog.vue'
import { useApproval } from './composables/useApproval'

const {
  actionId,
  searchTerm,
  statusFilter,
  currentPage,
  perPage,
  statusOptions,
  onSearchInput,
  clearSearch,
  isLoading,
  items,
  totalItems,
  totalPages,
  stats,
  goPage,
  statusBadgeClass,
  statusLabel,
  handleApprove,
  rejectDialogVisible,
  rejectReason,
  rejectSaving,
  openRejectDialog,
  handleReject,
} = useApproval()
</script>

<style scoped>
.ap-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
</style>

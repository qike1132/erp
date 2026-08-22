<template>
  <div class="nc-page">
    <!-- 页面头部（拆分为子组件） -->
    <NotificationHeaderBar
      :unread-count="unreadCount"
      :marking="marking"
      @back="goBack"
      @mark-all="handleMarkAll"
    />

    <!-- 批量操作栏 -->
    <Transition name="nc-slide">
      <div v-if="hasSelection" class="nc-batch-bar">
        <div class="nc-batch-info">
          <FontAwesomeIcon icon="check-circle" aria-hidden="true" />
          已选 <strong>{{ selectedCount }}</strong> 条
        </div>
        <div class="nc-batch-actions">
          <button class="nc-btn nc-btn--primary-sm" aria-label="标记已读" @click="handleBatchMarkRead">
            <FontAwesomeIcon icon="envelope-open-text" aria-hidden="true" />
            标记已读
          </button>
          <button class="nc-btn nc-btn--ghost-sm" aria-label="取消选择" @click="clearSelection">
            取消选择
          </button>
        </div>
      </div>
    </Transition>

    <!-- 通知列表 -->
    <div class="nc-body">
      <!-- 加载中 -->
      <div v-if="loading" class="nc-state">
        <div class="nc-state-icon">
          <UiSpinner />
        </div>
        <p class="nc-state-text">加载通知中...</p>
      </div>

      <!-- 空状态 -->
      <div v-else-if="list.length === 0" class="nc-state">
        <div class="nc-state-icon nc-state-icon--empty">
          <FontAwesomeIcon icon="bell-slash" aria-hidden="true" />
        </div>
        <p class="nc-state-text">暂无通知</p>
        <p class="nc-state-hint">当有新的订单或系统通知时，会在这里显示</p>
      </div>

      <!-- 列表 -->
      <div v-else class="nc-list-container">
        <!-- 全选栏 -->
        <div class="nc-select-bar">
          <label class="nc-checkbox-label">
            <input
              type="checkbox"
              :checked="selectAll"
              :indeterminate="isIndeterminate"
              @change="selectAll = ($event.target as HTMLInputElement).checked"
            />
            <span class="nc-checkbox-text">全选</span>
          </label>
          <span v-if="list.length > 0" class="nc-select-count">
            共 {{ total }} 条通知
          </span>
        </div>

        <ul class="nc-list">
          <NotificationListItem
            v-for="item in processedList"
            :key="item.id"
            :item="item"
            :selected-ids="selectedIds"
            @toggle-select="toggleSelect"
            @click-item="handleItemClick"
          />
        </ul>

        <UiPagination
          v-if="totalPages > 1"
          :current-page="page"
          :total-pages="totalPages"
          :total-items="total"
          @update:current-page="goToPage"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * NotificationCenterView.vue — 通知中心页面
 *
 * 页面逻辑（列表/多选/已读/轮询/跳转）下沉到 composables/useNotificationCenterPage.ts，
 * 页头拆分为 components/NotificationHeaderBar.vue，
 * 通知项拆分为 components/NotificationListItem.vue。
 */
import UiPagination from '@/components/ui/UiPagination.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import NotificationHeaderBar from '@/views/notifications/components/NotificationHeaderBar.vue'
import NotificationListItem from '@/views/notifications/components/NotificationListItem.vue'
import { useNotificationCenterPage } from '@/views/notifications/composables/useNotificationCenterPage'

const {
  list,
  total,
  page,
  totalPages,
  loading,
  marking,
  selectedIds,
  selectAll,
  isIndeterminate,
  selectedCount,
  hasSelection,
  unreadCount,
  processedList,
  goToPage,
  toggleSelect,
  goBack,
  handleItemClick,
  handleBatchMarkRead,
  handleMarkAll,
  clearSelection,
} = useNotificationCenterPage()
</script>

<style scoped>
/* ============ 页面布局 ============ */
.nc-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--color-surface-card);
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 18px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

/* ============ 批量操作栏 ============ */
.nc-batch-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 24px;
  background: var(--color-primary-50);
  border-bottom: 1px solid var(--color-primary-100);
  flex-shrink: 0;
}

.nc-batch-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary-700);
}

.nc-batch-info i {
  font-size: 14px;
  color: var(--color-primary-500);
}

.nc-batch-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ============ 主体列表区 ============ */
.nc-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: thin;
}

.nc-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 24px;
  gap: 12px;
}

.nc-state-icon {
  width: 64px;
  height: 64px;
  border-radius: 20px;
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-ocean-light));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  color: var(--color-primary-500);
}

.nc-state-icon--empty {
  background: linear-gradient(135deg, var(--color-slate-100), var(--color-border-light));
  color: var(--color-text-muted);
}

.nc-state-text {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-heading);
  margin: 0;
}

.nc-state-hint {
  font-size: 13px;
  color: var(--color-text-muted);
  margin: 0;
}

/* ============ 列表容器 ============ */
.nc-list-container {
  padding: 12px 16px 24px;
}

.nc-select-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  margin-bottom: 14px;
  background: var(--color-slate-50);
  border-radius: 12px;
  border: 1px solid var(--color-border-light);
}

.nc-select-count {
  font-size: 12px;
  color: var(--color-text-muted);
  font-weight: 500;
}

/* ============ 复选框（全选栏） ============ */
.nc-checkbox-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.nc-checkbox-label input[type="checkbox"] {
  width: 18px;
  height: 18px;
  accent-color: var(--color-primary-500);
  cursor: pointer;
  flex-shrink: 0;
}

.nc-checkbox-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  user-select: none;
}

/* ============ 通知列表 ============ */
.nc-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ============ 按钮（批量操作栏） ============ */
.nc-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: var(--radius-button);
  font-size: 13px;
  font-weight: 700;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all 0.2s ease;
  border: none;
  white-space: nowrap;
}

.nc-btn--primary-sm {
  background: var(--gradient-primary);
  color: #fff;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 700;
  border-radius: 10px;
  border: none;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all 0.2s ease;
}

.nc-btn--primary-sm:hover {
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.35);
  transform: translateY(-1px);
}

.nc-btn--ghost-sm {
  background: transparent;
  color: var(--color-text-secondary);
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 10px;
  border: 1px solid var(--color-border);
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all 0.2s ease;
}

.nc-btn--ghost-sm:hover {
  background: var(--color-slate-50);
  border-color: var(--color-text-muted);
}

/* ============ 动画 ============ */
.nc-slide-enter-active,
.nc-slide-leave-active {
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.nc-slide-enter-from,
.nc-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.nc-slide-enter-to,
.nc-slide-leave-from {
  max-height: 60px;
}

/* ============ 响应式：移动端 ============ */
@media (max-width: 767px) {
  .nc-list-container {
    padding: 8px 10px 16px;
  }

  .nc-batch-bar {
    padding: 8px 12px;
    flex-wrap: wrap;
  }
}

@media (max-width: 480px) {
  .nc-list-container {
    padding: 6px 8px 12px;
  }

  .nc-select-bar {
    padding: 6px 10px;
  }
}
</style>

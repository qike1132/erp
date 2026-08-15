<template>
  <div class="nc-page">
    <!-- 页面头部 -->
    <div class="nc-header">
      <div class="nc-header-left">
        <button class="nc-back-btn" @click="goBack" :aria-label="'返回上一页'">
          <FontAwesomeIcon icon="arrow-left" aria-hidden="true" />
        </button>
        <div class="nc-title-group">
          <h1 class="nc-title">通知中心</h1>
          <span v-if="unreadCount > 0" class="nc-title-badge">{{ unreadCount }} 条未读</span>
        </div>
      </div>
      <div class="nc-header-right">
        <button
          class="nc-btn nc-btn--ghost"
          :disabled="marking || unreadCount === 0"
          @click="handleMarkAll"
        >
          <FontAwesomeIcon icon="check-double" aria-hidden="true" />
          <span>全部已读</span>
        </button>
      </div>
    </div>

    <!-- 批量操作栏 -->
    <Transition name="nc-slide">
      <div v-if="hasSelection" class="nc-batch-bar">
        <div class="nc-batch-info">
          <FontAwesomeIcon icon="check-circle" aria-hidden="true" />
          已选 <strong>{{ selectedCount }}</strong> 条
        </div>
        <div class="nc-batch-actions">
          <button class="nc-btn nc-btn--primary-sm" @click="handleBatchMarkRead">
            <FontAwesomeIcon icon="envelope-open-text" aria-hidden="true" />
            标记已读
          </button>
          <button class="nc-btn nc-btn--ghost-sm" @click="clearSelection">
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
          <span class="nc-select-count" v-if="list.length > 0">
            共 {{ total }} 条通知
          </span>
        </div>

        <ul class="nc-list">
          <li
            v-for="item in processedList"
            :key="item.id"
            :class="['nc-item', { 'nc-item--unread': !item.is_read }]"
          >
            <!-- 复选框 -->
            <label class="nc-checkbox-label nc-item-check" @click.stop>
              <input
                type="checkbox"
                :checked="selectedIds.has(item.id)"
                @change="toggleSelect(item.id)"
              />
            </label>

            <!-- 内容主区（点击跳转订单） -->
            <div class="nc-item-body" @click="handleItemClick(item)">
              <!-- 顶部：未读点 + 类型图标 + 标题 + 时间戳 -->
              <header class="nc-item-head">
                <div class="nc-item-head-left">
                  <span v-if="!item.is_read" class="nc-item-dot" aria-hidden="true" />
                  <span class="nc-item-type-icon" aria-hidden="true">
                    <FontAwesomeIcon icon="bell" />
                  </span>
                  <h3 class="nc-item-title">{{ item.title }}</h3>
                </div>
                <time class="nc-item-time" :datetime="item.created_at ?? undefined">
                  <FontAwesomeIcon icon="clock" aria-hidden="true" />
                  {{ formatRelativeTime(item.created_at) }}
                </time>
              </header>

              <!-- 结构化内容 v2：单行展示订单摘要 + 产品（参照 beile-order 表格行） -->
              <template v-if="item._parsed && item._parsed.format_version === 2">
                <div class="nc-order-line">
                  <span class="nc-order-time">
                    <FontAwesomeIcon icon="calendar-alt" aria-hidden="true" />
                    {{ formatDateTime(item.created_at) }}
                  </span>
                  <span v-if="item._parsed.customer" class="nc-order-customer">
                    客户：{{ item._parsed.customer }}
                  </span>

                  <span v-if="item._parsed.factory" class="nc-order-factory">
                    工厂：{{ item._parsed.factory }}
                  </span>

                  <span class="nc-sku-summary">
                    <template v-for="(p, idx) in item._parsed.products" :key="idx">
                      <span v-if="idx > 0" class="nc-sku-sep">、</span>
                      <span class="nc-sku-text">{{ p.name }} ×{{ p.quantity }}</span>
                    </template>

                  <span v-if="item._parsed.products.length > 1" class="nc-sku-badge">
                    {{ item._parsed.products.length }} SKU
                  </span>
                  </span>

                </div>
              </template>

              <!-- 纯文本内容 -->
              <div v-else-if="item.content" class="nc-item-text">
                {{ item.content }}
              </div>
            </div>
          </li>
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
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useNotificationCenter } from '@/composables/useNotificationCenter'
import { useNotifications } from '@/composables/useNotifications'
import { type Notification } from '@/api/notification'
import { formatRelativeTime, formatDateTime } from '@/utils/format'
import { useToast } from '@/composables/useToast'

// ==== 结构化内容类型 ====
interface NotificationContentV2 {
  format_version: 2
  order_type: string
  order_no?: string
  customer?: string
  factory?: string
  products: Array<{ name: string; quantity: number | string }>
}

type ParsedNotification = Notification & {
  _parsed?: NotificationContentV2 | null
}

function parseContentV2(content: string | null | undefined): NotificationContentV2 | null {
  if (!content || typeof content !== 'string' || !content.startsWith('{')) return null
  try {
    const obj = JSON.parse(content)
    if (obj && obj.format_version === 2 && Array.isArray(obj.products)) {
      return obj as NotificationContentV2
    }
    return null
  } catch {
    return null
  }
}

// ==== 初始化 ====
const router = useRouter()
const { toast } = useToast()

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
  fetchList,
  goToPage,
  toggleSelect,
  dismissFromList,
  markBatchAsRead,
  markAllAsRead,
} = useNotificationCenter()

// 获取未读数（复用轮询 composable）
const { unreadCount, fetchUnreadCount, startPolling, stopPolling } = useNotifications()

// 处理后的列表
const processedList = computed<ParsedNotification[]>(() =>
  list.value.map((it) => ({ ...(it as ParsedNotification), _parsed: parseContentV2(it.content) })),
)

// 导航
function goBack() {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/dashboard')
  }
}

function navigateToOrder(orderId: number) {
  router.push({ path: '/beile-order', query: { order_id: String(orderId) } })
}

// 通知项点击：跳转订单页 + 标记已读并从列表移除
async function handleItemClick(item: Notification) {
  if (item.related_order_id) {
    navigateToOrder(item.related_order_id)
  }
  try {
    await dismissFromList(item.id)
    fetchUnreadCount()
  } catch {
    // 标记已读失败不阻塞跳转
  }
}

// 批量标记已读
async function handleBatchMarkRead() {
  const ids = Array.from(selectedIds.value).filter(
    (id) => !list.value.find((n) => n.id === id)?.is_read,
  )
  if (ids.length === 0) {
    toast.info('所选通知均已读')
    return
  }
  try {
    await markBatchAsRead(ids)
    // 即时刷新未读数，保持头部徽章同步
    fetchUnreadCount()
    toast.success(`已标记 ${ids.length} 条为已读`)
  } catch {
    toast.error('批量操作失败，请重试')
  }
}

// 全部已读
async function handleMarkAll() {
  try {
    await markAllAsRead()
    fetchUnreadCount()
    toast.success('已全部标记为已读')
    await fetchList(true)
  } catch {
    toast.error('操作失败，请重试')
  }
}

function clearSelection() {
  selectAll.value = false
}

// 生命周期
import { onMounted, onUnmounted } from 'vue'

onMounted(async () => {
  startPolling()
  await fetchList(true)
})

onUnmounted(() => {
  stopPolling()
})
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

/* ============ 头部 ============ */
.nc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 24px;
  background: linear-gradient(135deg, rgba(91, 141, 239, 0.04) 0%, rgba(176, 224, 230, 0.06) 100%);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.nc-header-left {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}

.nc-back-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-button);
  border: 1px solid var(--color-border-light);
  background: var(--color-surface-card);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 15px;
  transition: all var(--transition-fast, 0.2s ease);
  flex-shrink: 0;
}

.nc-back-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  border-color: var(--color-primary-200);
  transform: translateX(-2px);
}

.nc-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.nc-title {
  font-size: 1.25rem;
  font-weight: 800;
  color: var(--color-heading);
  letter-spacing: -0.01em;
  white-space: nowrap;
  margin: 0;
}

.nc-title-badge {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-danger-600);
  background: var(--color-danger-50);
  border: 1px solid var(--color-danger-200);
  padding: 3px 10px;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
}

.nc-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
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

/* ============ 复选框 ============ */
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

.nc-item {
  display: grid;
  /* 列：复选框 | 内容（弹性） */
  grid-template-columns: auto 1fr;
  align-items: start;
  gap: 16px;
  padding: 18px 20px;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: var(--color-surface-card);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
  transition: box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1),
              transform 0.4s cubic-bezier(0.4, 0, 0.2, 1),
              border-color 0.2s ease;
  position: relative;
}

.nc-item:hover {
  border-color: var(--color-primary-200);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06), 0 6px 20px rgba(91, 141, 239, 0.08);
  transform: translateY(-2px);
}

.nc-item--unread {
  background: linear-gradient(135deg, rgba(91, 141, 239, 0.04), rgba(176, 224, 230, 0.05));
  border-color: rgba(91, 141, 239, 0.2);
}

.nc-item--unread::before {
  /* 左侧强调条，标识未读 */
  content: '';
  position: absolute;
  left: -1px;
  top: 18px;
  bottom: 18px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: linear-gradient(180deg, var(--color-primary-400), var(--color-primary-600));
}

.nc-item-check {
  padding-top: 2px;
}

/* ============ 内容主区 ============ */
.nc-item-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  cursor: pointer;
}

/* 顶部：类型徽章 + 标题 + 时间戳 */
.nc-item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.nc-item-head-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.nc-item-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-danger-500);
  flex-shrink: 0;
  box-shadow: 0 0 0 3px rgba(234, 84, 85, 0.12);
}

.nc-item-type-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-ocean-light));
  border: 1px solid var(--color-primary-100);
  color: var(--color-primary-600);
  font-size: 14px;
  flex-shrink: 0;
}

.nc-item--unread .nc-item-type-icon {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-ocean-light));
  color: var(--color-primary-700);
  border-color: var(--color-primary-200);
}

.nc-item-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-heading);
  line-height: 1.4;
  word-break: break-word;
  margin: 0;
  flex: 1;
  min-width: 0;
}

.nc-item--unread .nc-item-title {
  font-weight: 800;
  color: var(--color-text-primary, #0f172a);
}

.nc-item-time {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-muted);
  white-space: nowrap;
  flex-shrink: 0;
  padding-top: 2px;
}

.nc-item-time i {
  font-size: 11px;
  opacity: 0.8;
}

/* 纯文本内容 */
.nc-item-text {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  padding: 12px 14px;
  background: var(--color-slate-50);
  border-radius: 10px;
  border: 1px dashed var(--color-border-light);
  word-break: break-word;
}

/* ============ 订单详情（单行展示，参照 beile-order 表格行） ============ */
.nc-order-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 18px;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.5;
  background: var(--color-surface, #f8fafc);
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  color: var(--color-text-secondary);
}

.nc-order-time {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 600;
  color: var(--color-text);
  white-space: nowrap;
}

.nc-order-time i {
  font-size: 12px;
  color: var(--color-primary-500);
}

.nc-order-customer,
.nc-order-factory {
  color: var(--color-text-secondary);
  white-space: nowrap;
}

/* SKU 摘要：产品名 ×数量，单行内联 */
.nc-sku-summary {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0 2px;
  color: var(--color-text);
  font-weight: 600;
}

.nc-sku-text {
  white-space: nowrap;
}

.nc-sku-sep {
  color: var(--color-text-muted);
  margin: 0 1px;
}

/* 多 SKU 徽章（类似 beile-order 的 bo-sku-badge） */
.nc-sku-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 700;
  border-radius: 999px;
  background: var(--color-primary-50, #eff3fb);
  border: 1px solid var(--color-primary-100, #dbe7fe);
  color: var(--color-primary-600, #5b8def);
  white-space: nowrap;
}

/* ============ 按钮 ============ */
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

.nc-btn--ghost {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  border: 1px solid var(--color-primary-100);
}

.nc-btn--ghost:hover:not(:disabled) {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}

.nc-btn--ghost:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  background: transparent;
  border-color: transparent;
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
  .nc-header {
    padding: 14px 16px;
  }

  .nc-title {
    font-size: 1.1rem;
  }

  .nc-list-container {
    padding: 8px 10px 16px;
  }

  .nc-item {
    padding: 14px 14px;
    gap: 12px;
    border-radius: 14px;
  }

  .nc-item-dot {
    width: 7px;
    height: 7px;
  }

  .nc-item-type-icon {
    width: 30px;
    height: 30px;
    font-size: 13px;
    border-radius: 9px;
  }

  .nc-item-head {
    gap: 8px;
  }

  .nc-order-line {
    padding: 8px 12px;
    gap: 4px 14px;
    font-size: 12px;
  }

  .nc-batch-bar {
    padding: 8px 12px;
    flex-wrap: wrap;
  }

  .nc-btn--ghost span {
    display: none;
  }

  .nc-btn--ghost {
    padding: 8px 12px;
  }
}

@media (max-width: 480px) {
  .nc-header {
    padding: 10px 12px;
  }

  .nc-title {
    font-size: 1rem;
  }

  .nc-back-btn {
    width: 36px;
    height: 36px;
  }

  .nc-list-container {
    padding: 6px 8px 12px;
  }

  .nc-item {
    padding: 12px;
    border-radius: 12px;
  }

  .nc-select-bar {
    padding: 6px 10px;
  }
}
</style>

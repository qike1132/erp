<template>
  <li
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
</template>

<script setup lang="ts">
/**
 * NotificationListItem.vue — 通知列表项
 *
 * 从 NotificationCenterView.vue 拆出：复选框 + 未读标识 + 标题 +
 * 结构化订单摘要（v2）/纯文本内容。选中与点击通过 emit 交回父组件。
 */
import { formatRelativeTime, formatDateTime } from '@/utils/format'
import type { ParsedNotification } from '@/views/notifications/composables/useNotificationCenterPage'

defineProps<{
  /** 通知项（含解析后的结构化内容 _parsed） */
  item: ParsedNotification
  /** 已选通知 id 集合（复选框勾选态） */
  selectedIds: ReadonlySet<number>
}>()

const emit = defineEmits<{
  /** 切换选中 */
  toggleSelect: [id: number]
  /** 点击内容区（跳转订单 + 标记已读） */
  clickItem: [item: ParsedNotification]
}>()

/** 切换选中：交给父组件处理多选集合 */
function toggleSelect(id: number) {
  emit('toggleSelect', id)
}

/** 点击内容区：交给父组件跳转订单并标记已读 */
function handleItemClick(item: ParsedNotification) {
  emit('clickItem', item)
}
</script>

<style scoped>
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

/* ============ 通知项卡片 ============ */
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

/* ============ 响应式：移动端 ============ */
@media (max-width: 767px) {
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
}

@media (max-width: 480px) {
  .nc-item {
    padding: 12px;
    border-radius: 12px;
  }
}
</style>

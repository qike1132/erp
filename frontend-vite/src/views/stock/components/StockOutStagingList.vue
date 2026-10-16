<template>
  <div class="so-col-title">
    <span><FontAwesomeIcon icon="clipboard-list" aria-hidden="true" /> 暂存出货列表</span>
    <span class="staged-count">共 {{ staged.length }} 个，合计 {{ stagedTotalQty }}</span>
  </div>
  <div class="so-col-scroll">
    <div v-if="staged.length === 0" class="so-empty-state">
      <FontAwesomeIcon icon="box-open" class="so-empty-icon" aria-hidden="true" />
      <p>暂无暂存出货</p>
    </div>
    <TransitionGroup v-else name="staged-list" tag="div">
      <div
        v-for="(item, idx) in staged"
        :key="item.id"
        class="so-staged-card"
      >
        <div class="so-staged-main">
          <div class="so-staged-info">
            <div class="so-staged-product">
              <FontAwesomeIcon icon="shipping-fast" class="so-staged-icon" aria-hidden="true" />{{ item.product_name }}
            </div>
            <div class="so-staged-meta">
              <span class="so-staged-tag"><FontAwesomeIcon icon="user" aria-hidden="true" />{{ item.customer || '无客户' }}</span>
              <span class="so-staged-tag"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" />{{ item.date }}</span>
            </div>
            <div class="so-staged-badges">
              <span class="badge-tag badge-danger">数量: {{ item.quantity }}</span>
              <span v-if="item.batch_no" class="badge-tag badge-secondary">批次: {{ item.batch_no }}</span>
              <span v-if="item.note" class="badge-tag badge-secondary">备注: {{ item.note }}</span>
            </div>
          </div>
          <div class="so-staged-actions">
            <button class="action-btn action-edit" aria-label="编辑" @click="emit('edit-item', idx)">
              <FontAwesomeIcon icon="edit" aria-hidden="true" />
            </button>
            <button class="action-btn action-delete" aria-label="删除" @click="emit('remove-item', idx)">
              <FontAwesomeIcon icon="trash" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup lang="ts">
import type { StagedStockout } from '@/types'

defineProps<{
  staged: StagedStockout[]
  stagedTotalQty: number
}>()

const emit = defineEmits<{
  'remove-item': [idx: number]
  'edit-item': [idx: number]
}>()
</script>

<style scoped>
.so-col-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.so-col-title i {
  color: var(--color-danger-500);
  margin-right: 6px;
  font-size: 13px;
}
.so-col-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 12px 20px;
}

/* ===== Staged Cards ===== */
.so-staged-card {
  border: 2px solid var(--color-border, #cbd5e1);
  border-left: 4px solid var(--color-danger-500);
  border-radius: 10px;
  padding: 8px 12px;
  margin-bottom: 6px;
  transition: border-color 0.3s ease, transform 0.3s ease;
}
.so-staged-card:hover {
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.so-staged-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.so-staged-info { flex: 1; }
.so-staged-product {
  font-weight: 600;
  margin-bottom: 4px;
  color: var(--color-text);
  font-size: 13px;
}
.so-staged-icon {
  color: var(--color-danger-500);
  margin-right: 4px;
}
.so-staged-meta {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
  display: flex;
  gap: 8px;
}
.so-staged-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.so-staged-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.so-staged-actions { display: flex; gap: 4px; margin-left: 8px; }
.so-empty-state {
  text-align: center;
  padding: 40px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--color-text-secondary);
}
.so-empty-icon {
  font-size: 28px;
  opacity: 0.5;
}
.staged-count {
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 400;
}

/* Staged list transition */
.staged-list-enter-active { transition: opacity 0.3s ease, transform 0.3s ease; }
.staged-list-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.staged-list-enter-from { opacity: 0; transform: translateX(-12px); }
.staged-list-leave-to { opacity: 0; transform: translateX(12px); }
.staged-list-move { transition: transform 0.3s ease; }

/* ===== Badge Tags ===== */
.badge-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}
.badge-info { background: var(--color-primary-50); color: var(--color-primary-600); }
.badge-danger { background: var(--color-danger-50); color: var(--color-danger-600); }
.badge-success { background: var(--color-success-50); color: var(--color-success-600); }
.badge-secondary { background: var(--color-surface, #f8fafc); color: var(--color-text-secondary); }
.badge-warning { background: #fef3c7; color: #92400e; }

/* ===== Action Buttons ===== */
.action-btn {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: background 0.2s ease, transform 0.2s ease;
  cursor: pointer;
  padding: 0;
}
.action-edit {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.action-edit:hover {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}
.action-delete {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}
.action-delete:hover {
  background: var(--color-danger-100);
  transform: translateY(-1px);
}
.action-delete:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>

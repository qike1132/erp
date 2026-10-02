<template>
  <div class="sc-card">
    <div class="sc-header">
      <div class="sc-title">
        <FontAwesomeIcon icon="layer-group" style="color: var(--color-primary-500)" aria-hidden="true" />
        暂存单
      </div>
      <span class="sc-count">
        {{ staged.length ? `${staged.length} 条 / 共 ${stagedTotal} 件` : '空' }}
      </span>
    </div>

    <div class="sc-list">
      <div v-if="!staged.length" class="sc-empty">
        <FontAwesomeIcon icon="box-open" aria-hidden="true" />
        <p>左侧填写信息后点击「加入暂存单」</p>
      </div>
      <div
        v-for="item in staged"
        :key="item.key"
        :class="['sc-item', item.direction === 'in' ? 'sc-item-in' : 'sc-item-out']"
      >
        <div class="sc-item-main">
          <div class="sc-item-name">
            <span :class="['sc-dir', item.direction === 'in' ? 'sc-dir-in' : 'sc-dir-out']">
              {{ item.direction === 'in' ? '入库' : '出库' }}
            </span>
            {{ item.caseName }}
          </div>
          <div class="sc-item-meta">
            <span><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" /> {{ item.date }}</span>
            <span v-if="item.note" class="sc-item-note"><FontAwesomeIcon icon="note-sticky" aria-hidden="true" /> {{ item.note }}</span>
          </div>
        </div>
        <div class="sc-item-side">
          <div class="sc-qty-editor">
            <button type="button" class="sc-qty-btn" aria-label="减少" @click="emit('quantity-change', item.key, item.quantity - 1)">
              <FontAwesomeIcon icon="minus" />
            </button>
            <input
              :value="item.quantity"
              type="number"
              class="sc-qty-input"
              min="1"
              step="1"
              :aria-label="`${item.caseName} 数量`"
              @change="emit('quantity-change', item.key, Number(($event.target as HTMLInputElement).value))"
            />
            <button type="button" class="sc-qty-btn" aria-label="增加" @click="emit('quantity-change', item.key, item.quantity + 1)">
              <FontAwesomeIcon icon="plus" />
            </button>
          </div>
          <button class="sc-remove-btn" aria-label="移除" @click="emit('remove', item.key)">
            <FontAwesomeIcon icon="trash" />
          </button>
        </div>
      </div>
    </div>

    <div v-if="lastFailures.length" class="sc-failures" role="alert">
      <div class="sc-failures-title">
        <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />
        以下记录提交失败，已保留在清单中：
      </div>
      <ul>
        <li v-for="f in lastFailures" :key="f.index">
          <strong>{{ f.productName }}</strong>：{{ f.error }}
        </li>
      </ul>
    </div>

    <div class="sc-footer">
      <button class="sc-btn sc-btn-clear" :disabled="!staged.length || submitting" aria-label="清空清单" @click="emit('clear')">
        <FontAwesomeIcon icon="times" style="margin-right: 4px" aria-hidden="true" />清空
      </button>
      <button
        class="sc-btn sc-btn-submit"
        :disabled="!staged.length || submitting"
        aria-label="提交"
        @click="emit('submit')"
      >
        <UiLoadingIcon :loading="submitting" icon="paper-plane" style="margin-right: 6px" />
        {{ submitting ? '提交中…' : `提交（${staged.length} 条）` }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * StagedCart — 暂存单：入库/出库混存（每条带方向徽标）、行内改数量、移除、清空、批量提交。
 */
import UiLoadingIcon from '@/components/ui/UiLoadingIcon.vue'
import type { StagedStockItem, SubmitFailure } from '../composables/useCaseStockWorkbench'

defineProps<{
  staged: StagedStockItem[]
  stagedTotal: number
  submitting: boolean
  lastFailures: SubmitFailure[]
}>()

const emit = defineEmits<{
  remove: [key: number]
  'quantity-change': [key: number, quantity: number]
  clear: []
  submit: []
}>()
</script>

<style scoped>
.sc-card {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
  display: flex;
  flex-direction: column;
}
.sc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.sc-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.sc-count { color: var(--color-text-secondary); font-size: 13px; }

.sc-list {
  max-height: 320px;
  overflow-y: auto;
  padding: 12px 16px;
}
.sc-empty {
  text-align: center;
  color: var(--color-text-muted);
  padding: 32px 0;
}
.sc-empty i { font-size: 28px; opacity: 0.3; display: block; margin-bottom: 8px; }

.sc-item {
  border: 2px solid;
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  transition: transform 0.2s ease;
}
.sc-item:hover { transform: translateY(-1px); }
.sc-item-in { border-color: var(--color-primary-200); }
.sc-item-out { border-color: var(--color-danger-100); }
.sc-item-main { flex: 1; min-width: 0; }
.sc-item-name { font-weight: 600; margin-bottom: 4px; font-size: 13px; color: var(--color-text); }
.sc-item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.sc-item-note {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sc-item-side {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.sc-dir { display: inline-block; padding: 1px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-right: 6px; }
.sc-dir-in { background: var(--color-success-50); color: var(--color-success-600); }
.sc-dir-out { background: var(--color-danger-50); color: var(--color-danger-600); }

.sc-qty-editor { display: flex; align-items: stretch; }
.sc-qty-btn {
  width: 24px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: var(--color-surface, #f8fafc);
  color: var(--color-text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
}
.sc-qty-btn:first-child { border-radius: 7px 0 0 7px; }
.sc-qty-btn:last-child { border-radius: 0 7px 7px 0; }
.sc-qty-btn:hover { background: var(--color-primary-50); color: var(--color-primary-600); }
.sc-qty-input {
  width: 52px;
  text-align: center;
  padding: 5px 2px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-left: none;
  border-right: none;
  font-size: 13px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  outline: none;
}
.sc-qty-input::-webkit-outer-spin-button,
.sc-qty-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.sc-qty-input { appearance: textfield; -moz-appearance: textfield; }

.sc-remove-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  background: var(--color-danger-50);
  color: var(--color-danger-500);
  transition: background 0.2s ease;
}
.sc-remove-btn:hover { background: var(--color-danger-100); }

.sc-failures {
  margin: 0 16px 8px;
  padding: 10px 12px;
  border-radius: 9px;
  background: var(--color-danger-50);
  color: var(--color-danger-700);
  font-size: 12px;
}
.sc-failures-title { font-weight: 600; margin-bottom: 4px; display: flex; gap: 6px; align-items: center; }
.sc-failures ul { margin: 0; padding-left: 18px; }
.sc-failures li { margin-bottom: 2px; }

.sc-footer {
  display: flex;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--color-border-light, #f1f5f9);
}
.sc-btn {
  padding: 9px 16px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: box-shadow 0.2s ease, transform 0.2s ease, opacity 0.2s ease;
}
.sc-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.sc-btn-clear {
  flex: 0 0 auto;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  color: var(--color-text-secondary);
}
.sc-btn-clear:hover:not(:disabled) { background: var(--color-surface, #f8fafc); }
.sc-btn-submit {
  flex: 1;
  color: white;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
}
.sc-btn-submit:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15); }
</style>

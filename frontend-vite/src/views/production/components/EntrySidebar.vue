<template>
  <aside class="pr-entry-sidebar" aria-label="链接">
    <div class="pr-entry-side-card">
      <div class="pr-entry-side-head">
        <span><FontAwesomeIcon icon="clock-rotate-left" aria-hidden="true" /> 最近使用</span>
        <button v-if="recentProducts.length" type="button" class="pr-entry-side-clear" aria-label="清空 {{ p.name }} {{ p.barcode }}" @click="emit('clear')">清空</button>
      </div>
      <div v-if="recentProducts.length" class="pr-entry-recent-list">
        <button
          v-for="p in recentProducts"
          :key="p.id"
          type="button"
          class="pr-entry-recent-item"
          :title="p.barcode || ''"
          @click="emit('select', p)"
        >
          <span class="pr-entry-recent-bullet" />
          <span class="pr-entry-recent-content">
            <span class="pr-entry-recent-name">{{ p.name }}</span>
            <span v-if="p.barcode" class="pr-entry-recent-barcode">{{ p.barcode }}</span>
          </span>
          <FontAwesomeIcon icon="chevron-right" class="pr-entry-recent-arrow" aria-hidden="true" />
        </button>
      </div>
      <div v-else class="pr-entry-empty-small">
        <FontAwesomeIcon icon="inbox" aria-hidden="true" />
        <span>暂无最近使用</span>
        <small>录入后会自动记录</small>
      </div>
    </div>

    <div class="pr-entry-side-card">
      <div class="pr-entry-side-head">
        <span><FontAwesomeIcon icon="keyboard" aria-hidden="true" /> 快捷键</span>
      </div>
      <div class="pr-entry-shortcuts">
        <div class="pr-entry-shortcut"><kbd>↑</kbd><kbd>↓</kbd><span>选择产品</span></div>
        <div class="pr-entry-shortcut"><kbd>Enter</kbd><span>确认选择 / 提交</span></div>
        <div class="pr-entry-shortcut"><kbd>Ctrl</kbd>+<kbd>Enter</kbd><span>直接提交</span></div>
        <div class="pr-entry-shortcut"><kbd>Esc</kbd><span>关闭</span></div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import type { Product } from '@/types'

defineProps<{
  recentProducts: Product[]
}>()

const emit = defineEmits<{
  select: [product: Product]
  clear: []
}>()
</script>

<style scoped>
.pr-entry-sidebar {
  padding: 22px 20px;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
}
.pr-entry-side-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.pr-entry-side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  background: #f8fafc;
  border-bottom: 1px solid #f1f5f9;
  font-size: 12px;
  font-weight: 700;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.pr-entry-side-head span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.pr-entry-side-head i {
  color: #1e40af;
  font-size: 11px;
}
.pr-entry-side-clear {
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  padding: 2px 4px;
  font-family: inherit;
  text-transform: none;
  letter-spacing: 0;
  transition: color 0.15s ease;
}
.pr-entry-side-clear:hover {
  color: #dc2626;
}
.pr-entry-recent-list {
  display: flex;
  flex-direction: column;
  padding: 6px;
}
.pr-entry-recent-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  border-radius: 8px;
  font-family: inherit;
  color: inherit;
  transition: all 0.15s ease;
}
.pr-entry-recent-item:hover {
  background: #eff6ff;
  transform: translateX(2px);
}
.pr-entry-recent-bullet {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
  flex-shrink: 0;
  transition: background 0.15s ease, transform 0.15s ease;
}
.pr-entry-recent-item:hover .pr-entry-recent-bullet {
  background: #3b82f6;
  transform: scale(1.4);
}
.pr-entry-recent-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.pr-entry-recent-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pr-entry-recent-barcode {
  font-size: 11px;
  color: #64748b;
  font-family: 'SF Mono', 'Consolas', monospace;
}
.pr-entry-recent-arrow {
  font-size: 10px;
  color: #cbd5e1;
  transition: all 0.15s ease;
}
.pr-entry-recent-item:hover .pr-entry-recent-arrow {
  color: #1e40af;
  transform: translateX(2px);
}
.pr-entry-empty-small {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 24px 12px;
  color: #94a3b8;
  text-align: center;
}
.pr-entry-empty-small i {
  font-size: 22px;
  opacity: 0.5;
}
.pr-entry-empty-small span {
  font-size: 12px;
  font-weight: 600;
}
.pr-entry-empty-small small {
  font-size: 11px;
  color: #cbd5e1;
}
.pr-entry-shortcuts {
  padding: 10px 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pr-entry-shortcut {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #475569;
}
.pr-entry-shortcut span {
  margin-left: auto;
  font-weight: 500;
}
.pr-entry-shortcut kbd {
  display: inline-block;
  min-width: 22px;
  padding: 2px 6px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-bottom-width: 2px;
  border-radius: 5px;
  font-size: 10px;
  font-weight: 700;
  color: #475569;
  font-family: 'SF Mono', 'Consolas', monospace;
  text-align: center;
}
@media (max-width: 900px) {
  .pr-entry-sidebar {
    padding: 16px;
    max-height: 40vh;
  }
}
@media (max-width: 600px) {
  .pr-entry-sidebar {
    padding: 14px;
  }
}
</style>
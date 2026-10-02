<template>
  <div class="set-wrap">
    <div class="set-card">
      <div class="set-head">
        <FontAwesomeIcon icon="gear" style="color: var(--color-primary-500)" aria-hidden="true" />
        皮套设置
        <small class="set-sub">按产品维护：一个主件 + 若干配件</small>
      </div>
      <div class="set-body">
        <label class="set-label">产品</label>
        <UiAutocomplete
          v-model="productQuery"
          :search-fn="searchProducts"
          placeholder="搜索产品名称或69码"
          suppress-after-select
          @select="(p: Product) => selectProduct(p)"
        >
          <template #option="{ item }">
            <span class="set-option-name">{{ item.name }}</span>
            <span v-if="item.barcode" class="set-option-barcode">{{ item.barcode }}</span>
          </template>
        </UiAutocomplete>
      </div>
    </div>

    <div v-if="loading" class="set-loading"><UiLoadingIcon :loading="true" icon="spinner" /> 载入…</div>

    <div v-else-if="main" class="set-card">
      <div class="set-head">
        <span>主件：<b>{{ main.name }}</b></span>
        <span class="set-tag">主件</span>
        <span class="set-sub">库存 {{ main.current_stock }}</span>
      </div>
      <div class="set-body">
        <div class="set-sub-head">配件（{{ rows.length }}）</div>

        <div v-for="row in rows" :key="row.id" class="set-row">
          <input v-model="row.name" class="set-input" aria-label="配件名称" />
          <label class="set-qty-label">配比 ×<input v-model.number="row.qtyPerSet" type="number" min="1" class="set-qty" aria-label="配比" /></label>
          <button class="set-btn set-btn-ghost" :disabled="saving" @click="savePart(row)">保存</button>
          <button class="set-btn set-btn-del" :disabled="saving" @click="removePart(row)">删除</button>
        </div>
        <div v-if="!rows.length" class="set-empty">暂无配件，可在下方添加</div>

        <div class="set-add-row">
          <input v-model="newName" class="set-input" placeholder="新配件名称（如：鲨鱼帽子）" aria-label="新配件名称" />
          <label class="set-qty-label">配比 ×<input v-model.number="newQty" type="number" min="1" class="set-qty" aria-label="新配件配比" /></label>
          <button class="set-btn set-btn-primary" :disabled="saving || !newName.trim()" @click="onAdd">添加配件</button>
        </div>
        <div class="set-hint">配比先存着备用（暂不参与计算）。配件与主件各自独立出入库。</div>
      </div>
    </div>

    <div v-else class="set-card">
      <div class="set-body set-empty-outer">选择一个产品，查看 / 维护它的皮套主件与配件。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * CaseSettingsPanel — 皮套设置：按产品维护主件 + 配件（名称、配比）。
 */
import { ref } from 'vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import UiLoadingIcon from '@/components/ui/UiLoadingIcon.vue'
import { useCaseSettings } from '../composables/useCaseSettings'
import type { Product } from '@/types'

const {
  productQuery,
  searchProducts,
  main,
  rows,
  loading,
  saving,
  selectProduct,
  addPart,
  savePart,
  removePart,
} = useCaseSettings()

const newName = ref('')
const newQty = ref(1)

function onAdd() {
  void addPart(newName.value, newQty.value)
  newName.value = ''
  newQty.value = 1
}
</script>

<style scoped>
.set-wrap { display: flex; flex-direction: column; gap: 16px; }
.set-card {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}
.set-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.set-sub { color: var(--color-text-muted); font-weight: 400; font-size: 12px; }
.set-tag { font-size: 11px; padding: 1px 8px; border-radius: 10px; background: var(--color-primary-50); color: var(--color-primary-700); font-weight: 600; }
.set-body { padding: 16px; }
.set-label { display: block; font-size: 12px; font-weight: 600; color: var(--color-text-secondary); margin-bottom: 6px; }
.set-option-name { margin-right: 6px; }
.set-option-barcode { color: var(--color-text-muted); font-size: 11px; }

.set-sub-head { font-size: 13px; font-weight: 600; color: var(--color-text-secondary); margin-bottom: 8px; }
.set-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.set-input {
  flex: 1;
  min-width: 0;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  color: var(--color-text);
  font-family: inherit;
  outline: none;
}
.set-input:focus { border-color: var(--color-primary-400); }
.set-qty-label { flex-shrink: 0; display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--color-text-secondary); }
.set-qty {
  width: 56px;
  height: 34px;
  text-align: center;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  outline: none;
}
.set-btn {
  flex-shrink: 0;
  height: 34px;
  padding: 0 12px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.set-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.set-btn-ghost { border: 1px solid var(--color-border-light, #e2e8f0); background: white; color: var(--color-text-secondary); }
.set-btn-del { border: none; background: var(--color-danger-50); color: var(--color-danger-600); }
.set-btn-primary { border: none; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: white; }

.set-add-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--color-border-light);
}
.set-empty { color: var(--color-text-muted); font-size: 13px; padding: 8px 0; }
.set-empty-outer { color: var(--color-text-muted); font-size: 13px; }
.set-hint { margin-top: 10px; font-size: 12px; color: var(--color-text-muted); }
.set-loading { display: flex; align-items: center; gap: 6px; padding: 12px; color: var(--color-text-muted); font-size: 13px; }
</style>

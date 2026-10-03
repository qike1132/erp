<template>
  <div class="set-wrap">
    <!-- 产品选择 -->
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
      <div class="set-sect-head">主件</div>
      <div class="set-body">
        <!-- 主件带 -->
        <div class="set-main-band">
          <span class="set-tag-main">主件</span>
          <span class="set-main-name">{{ main.name }}</span>
          <span class="set-main-stock">库存 {{ main.current_stock }}</span>
        </div>

        <!-- 配件卡片 -->
        <div class="set-sect-head" style="background:none;border:none;padding:14px 0 8px">配件 <span class="set-sub">{{ rows.length }} 项</span></div>
        <div class="set-chips">
          <span v-for="row in rows" :key="row.id" class="set-chip">
            <span class="set-tag-part">配件</span>
            <span class="set-chip-name">{{ row.name }}</span>
            <button class="set-chip-edit" :disabled="saving" aria-label="编辑" @click="openEdit(row)">改</button>
            <button class="set-chip-del" :disabled="saving" aria-label="删除" @click="removePart(row)">✕</button>
          </span>
          <button v-if="!edit" class="set-chip-add" aria-label="添加配件" @click="openAdd">＋ 添加配件</button>
        </div>

        <!-- 添加 / 编辑 表单 -->
        <div v-if="edit" class="set-edit">
          <span class="set-tag-part" style="flex-shrink:0">{{ edit.id == null ? '新增' : '编辑' }}</span>
          <input v-model="edit.name" class="set-cell-input" placeholder="配件名称（如：鲨鱼帽子）" aria-label="配件名称" />
          <button class="set-btn set-btn-primary" :disabled="saving || !edit.name.trim()" @click="submitEdit">保存</button>
          <button class="set-btn set-btn-ghost" :disabled="saving" @click="edit = null">取消</button>
        </div>

        <div class="set-hint">配件与主件各自独立出入库。</div>
      </div>
    </div>

    <div v-else class="set-card">
      <div class="set-body set-empty-outer">选择一个产品，查看 / 维护它的皮套主件与配件。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * CaseSettingsPanel — 皮套设置（主件带 + 配件卡片；点「改」或「＋」在下方编辑）。
 */
import { ref } from 'vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import UiLoadingIcon from '@/components/ui/UiLoadingIcon.vue'
import { useCaseSettings, type EditablePart } from '../composables/useCaseSettings'
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

/** 当前编辑/新增的表单（id=null 表示新增） */
const edit = ref<{ id: number | null; name: string } | null>(null)

function openAdd() {
  edit.value = { id: null, name: '' }
}
function openEdit(row: EditablePart) {
  edit.value = { id: row.id, name: row.name }
}
function submitEdit() {
  const e = edit.value
  if (!e || !e.name.trim()) return
  if (e.id == null) {
    addPart(e.name)
  } else {
    savePart({ id: e.id, name: e.name })
  }
  edit.value = null
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
.set-body { padding: 16px; }
.set-label { display: block; font-size: 12px; font-weight: 600; color: var(--color-text-secondary); margin-bottom: 6px; }
.set-option-name { margin-right: 6px; }
.set-option-barcode { color: var(--color-text-muted); font-size: 11px; }

.set-sect-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--color-surface, #f8fafc);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-secondary);
}

/* 主件带 */
.set-main-band {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  background: var(--color-primary-50);
  border-left: 4px solid var(--color-primary-500);
  border-radius: 10px;
}
.set-main-name { font-size: 15px; font-weight: 700; color: var(--color-primary-700); }
.set-main-stock { margin-left: auto; font-size: 12px; color: var(--color-text-muted); }

.set-tag-main { flex-shrink: 0; display: inline-flex; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: var(--color-primary-500); color: #fff; }
.set-tag-part { flex-shrink: 0; display: inline-flex; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: var(--color-warning-500); color: #fff; }

/* 配件卡片 */
.set-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.set-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px 6px 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 20px;
  background: #fff;
  font-size: 13px;
}
.set-chip-name { font-weight: 600; color: var(--color-text); }
.set-chip-ratio { color: var(--color-text-muted); font-size: 12px; }
.set-chip-edit {
  border: none;
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  cursor: pointer;
}
.set-chip-del {
  border: none;
  background: var(--color-danger-50);
  color: var(--color-danger-600);
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  width: 22px;
  height: 22px;
  cursor: pointer;
}
.set-chip-add {
  border: 1px dashed var(--color-primary-300, #8babf5);
  background: #fff;
  color: var(--color-primary-600);
  border-radius: 20px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}
.set-chip-add:hover { background: var(--color-primary-50); }

/* 编辑表单 */
.set-edit {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 12px;
  background: #fbfcff;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
}
.set-edit .set-cell-input { flex: 1; }
.set-cell-input {
  width: 100%;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text);
  font-family: inherit;
  outline: none;
}
.set-cell-input:focus { border-color: var(--color-primary-400); }
.set-qty-label { flex-shrink: 0; display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--color-text-secondary); }
.set-cell-qty {
  width: 56px;
  height: 32px;
  text-align: center;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px;
  font-size: 13px;
  outline: none;
}
.set-btn {
  flex-shrink: 0;
  height: 32px;
  padding: 0 12px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.set-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.set-btn-ghost { border: 1px solid var(--color-border-light, #e2e8f0); background: #fff; color: var(--color-text-secondary); }
.set-btn-primary { border: none; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: #fff; }

.set-empty-outer { color: var(--color-text-muted); font-size: 13px; }
.set-hint { margin-top: 12px; font-size: 12px; color: var(--color-text-muted); }
.set-loading { display: flex; align-items: center; gap: 6px; padding: 12px; color: var(--color-text-muted); font-size: 13px; }
</style>

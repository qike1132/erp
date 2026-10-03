<template>
  <div class="cs-set">
    <div class="cs-cols">
      <!-- 左：产品选择（全部产品，按 有配件/无配件 区分） -->
      <div class="cs-col">
        <div class="mc-col-title">
          <FontAwesomeIcon icon="boxes-stacked" aria-hidden="true" />
          产品选择
          <span class="mc-col-tail">{{ filtered.length }} 条</span>
        </div>
        <div class="mc-col-tools">
          <UiSearchInput v-model="keyword" placeholder="搜索产品名称或69码…" />
          <div class="mc-seg" role="group" aria-label="按有无配件过滤">
            <button
              v-for="f in FILTERS"
              :key="f.value"
              type="button"
              :class="{ active: partsFilter === f.value }"
              :aria-pressed="partsFilter === f.value"
              @click="partsFilter = f.value"
            >
              {{ f.label }}
            </button>
          </div>
        </div>

        <div v-if="capped" class="cs-cap-hint">已加载前 {{ PRODUCT_CAP }} 个产品，如未找到请用上方搜索</div>
        <div v-if="isLoading && !products.length" class="cs-state">载入…</div>
        <div v-else-if="!filtered.length" class="cs-state">没有匹配的产品</div>
        <ul v-else class="cs-products">
          <li
            v-for="p in filtered"
            :key="p.id"
            :class="['cs-product', { active: p.id === selectedProductId }]"
            @click="selectProduct(p.id)"
          >
            <div class="cs-product-details">
              <span class="cs-product-name">{{ p.name }}</span>
              <span v-if="p.barcode" class="cs-product-code">{{ p.barcode }}</span>
            </div>
            <span :class="['cs-badge', p.has_parts ? 'has' : 'no']">
              {{ p.has_parts ? '有配件' : '无配件' }}
            </span>
          </li>
        </ul>
      </div>

      <!-- 右：选中产品的配件维护 -->
      <div class="cs-col">
        <div class="mc-col-title">
          <FontAwesomeIcon icon="gear" aria-hidden="true" />
          配件维护
          <span v-if="selectedMain" class="mc-col-tail">库存 {{ selectedMain.current_stock }}</span>
        </div>
        <div class="cs-parts-body">
          <div v-if="!selectedMain" class="cs-state cs-state-center">
            从左侧选一个产品，在右侧维护它的配件。
          </div>
          <template v-else>
            <div class="cs-main-head">
              <span class="cs-tag-main">皮套</span>
              <span class="cs-main-name">{{ selectedMain.name }}</span>
            </div>
            <div v-if="loadingTree" class="cs-state">载入…</div>
            <template v-else>
              <div class="cs-parts-head">配件（{{ selectedParts.length }}）</div>
              <div v-for="p in selectedParts" :key="p.id" class="cs-part">
                <span class="cs-tag-part">配件</span>
                <input
                  v-model="drafts[p.id]"
                  class="cs-input"
                  aria-label="配件名称"
                  @keydown.enter="savePart(p.id, drafts[p.id] ?? p.name)"
                />
                <button class="cs-btn cs-btn-ghost" :disabled="saving" @click="savePart(p.id, drafts[p.id] ?? p.name)">保存</button>
                <button class="cs-btn cs-btn-del" :disabled="saving" @click="askRemove(p)">删除</button>
              </div>
              <div v-if="!selectedParts.length" class="cs-state">暂无配件，在下方添加</div>

              <div class="cs-add-row">
                <input
                  v-model="newName"
                  class="cs-input"
                  placeholder="新配件名称（如：鲨鱼帽子）"
                  aria-label="新配件名称"
                  @keydown.enter="onAdd"
                />
                <button class="cs-btn cs-btn-primary" :disabled="saving || !newName.trim()" @click="onAdd">添加配件</button>
              </div>
            </template>
          </template>
        </div>
      </div>
    </div>

    <UiConfirmDialog
      :open="confirm.open"
      :text="confirm.text"
      :sub="confirm.sub"
      :type="confirm.type"
      @confirm="confirm.onConfirm"
      @cancel="confirm.onCancel"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * CaseSettingsPanel — 皮套设置（产品选择面板）。
 *
 * 左：全部产品（`GET /cases/products`，附配件数），本地按关键词 + 有/无配件过滤；
 * 右：选中产品的皮套主件 + 配件维护（点产品经 `POST /cases/for-product` 自动建主件）。
 * 观感对齐 material-calculator 的 ProductSelectColumn（复用全局 .mc-col-title/.mc-seg）。
 */
import { ref, watch } from 'vue'
import UiSearchInput from '@/components/ui/UiSearchInput.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useCaseSettings, type PartsFilter } from '../composables/useCaseSettings'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import type { CaseItem } from '@/api/case'

const {
  keyword,
  partsFilter,
  products,
  filtered,
  capped,
  isLoading,
  selectedProductId,
  selectedMain,
  selectedParts,
  loadingTree,
  selectProduct,
  saving,
  addPart,
  savePart,
  removePart,
} = useCaseSettings()

const PRODUCT_CAP = 200
const FILTERS: { label: string; value: PartsFilter }[] = [
  { label: '全部', value: 'all' },
  { label: '有配件', value: 'yes' },
  { label: '无配件', value: 'no' },
]

const confirm = useConfirmDialog()
const newName = ref('')

/** 配件名称的编辑副本（按 id 索引），选中/刷新时同步 */
const drafts = ref<Record<number, string>>({})
watch(
  selectedParts,
  (ps) => {
    const d: Record<number, string> = {}
    for (const p of ps) d[p.id] = p.name
    drafts.value = d
  },
  { immediate: true },
)

function onAdd() {
  void addPart(newName.value)
  newName.value = ''
}

async function askRemove(p: CaseItem) {
  const ok = await confirm.confirm(`删除配件「${p.name}」？`, '仅删除该配件，不影响皮套', 'danger')
  if (ok) void removePart(p.id)
}
</script>

<style scoped>
.cs-set { display: flex; flex-direction: column; }

.cs-cols { display: grid; grid-template-columns: 480px 1fr; gap: 16px; align-items: stretch; }
@media (max-width: 1100px) { .cs-cols { grid-template-columns: 1fr; } }

.cs-col {
  display: flex;
  flex-direction: column;
  height: 440px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  background: var(--color-surface-card, #fff);
  overflow: hidden;
}

/* 产品行（观感对齐 material-calculator 的 .mc-product-item） */
.cs-products { list-style: none; margin: 0; padding: 8px 12px; flex: 1; min-height: 0; overflow-y: auto; }
.cs-product {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: 6px;
  margin-bottom: 4px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.cs-product:hover { border-color: var(--color-primary-300); background: var(--color-primary-50); }
.cs-product.active { border-color: var(--color-primary-400); background: var(--color-primary-50); }

.cs-product-details { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 8px; }
.cs-product-name {
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cs-product-code { flex-shrink: 0; font-size: 11px; font-family: var(--font-mono); color: var(--color-text-muted); }

.cs-badge { flex-shrink: 0; padding: 1px 6px; border-radius: 4px; font-size: 11px; font-weight: 500; border: 1px solid; }
.cs-badge.has { background: var(--color-success-50); color: var(--color-success-700); border-color: var(--color-success-200); }
.cs-badge.no { background: var(--color-slate-100); color: var(--color-text-muted); border-color: var(--color-border); }

.cs-cap-hint { padding: 6px 12px 0; font-size: 11px; color: var(--color-text-muted); }

/* 右侧配件维护 */
.cs-parts-body { padding: 14px; flex: 1; min-height: 0; overflow-y: auto; }
.cs-main-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 12px;
  border-radius: 8px;
  background: var(--color-primary-50);
  border-left: 4px solid var(--color-primary-500);
}
.cs-main-name { font-size: 14px; font-weight: 700; color: var(--color-primary-700); }

.cs-parts-head { font-size: 12px; font-weight: 700; color: var(--color-text-secondary); margin-bottom: 8px; }
.cs-part { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.cs-add-row { display: flex; align-items: center; gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--color-border-light); }

.cs-tag-main { flex-shrink: 0; display: inline-flex; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: var(--color-primary-500); color: #fff; }
.cs-tag-part { flex-shrink: 0; display: inline-flex; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; background: var(--color-warning-500); color: #fff; }

.cs-input {
  flex: 1;
  min-width: 0;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px;
  font-size: 13px;
  color: var(--color-text);
  font-family: inherit;
  outline: none;
}
.cs-input:focus { border-color: var(--color-primary-400); }

.cs-btn { flex-shrink: 0; height: 32px; padding: 0 12px; border-radius: 8px; font-size: 12px; font-weight: 600; cursor: pointer; }
.cs-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.cs-btn-ghost { border: 1px solid var(--color-border-light, #e2e8f0); background: #fff; color: var(--color-text-secondary); }
.cs-btn-del { border: none; background: var(--color-danger-50); color: var(--color-danger-600); }
.cs-btn-primary { border: none; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: #fff; }

.cs-state { padding: 16px; color: var(--color-text-muted); font-size: 13px; display: flex; align-items: center; gap: 6px; }
.cs-state-center { justify-content: center; padding: 40px 16px; }
</style>

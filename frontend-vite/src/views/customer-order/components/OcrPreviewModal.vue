<template>
  <UiDialog
    v-model:open="openModel"
    :title="showGuide ? '没有识别到可导入的条目' : '确认识别结果'"
    max-width-class="max-w-[900px]"
  >
    <!-- 弹窗打开时录入面板的粘贴热区被遮挡，这里用更高优先级接管，
         让「换一张更清晰的」可以直接 Ctrl+V 重试 -->
    <div ref="dialogBodyRef">
      <!-- ============ 有候选条目：人工确认表 ============ -->
      <template v-if="!showGuide">
        <p class="ocr-sub">
          来自「{{ sourceName || '粘贴的图片' }}」· 识别到 {{ drafts.length }} 项，请核对后再导入
        </p>

        <div class="ocr-sum">
          <span class="ok">已匹配 <b>{{ matchedCount }}</b></span>
          <span class="bad">未匹配 <b>{{ unmatchedCount }}</b></span>
          <span>合计数量 <b>{{ totalQuantity }}</b></span>
        </div>

        <!-- 后端识别过程中的提示（客户兜底 / 未匹配）不能只存在状态里没人看 -->
        <ul v-if="warnings.length" class="ocr-warn">
          <li v-for="(w, i) in warnings" :key="i">{{ w }}</li>
        </ul>

        <p v-if="!drafts.length" class="ocr-empty">
          已把识别到的条目全部移除。若还有要录的，可以直接粘贴下一张图；否则关闭本窗口手工录入。
        </p>

        <table v-else class="ocr-table">
          <thead>
            <tr>
              <th class="c-cust">客户</th>
              <th>产品</th>
              <th class="c-qty">数量</th>
              <th class="c-note">备注</th>
              <th class="c-del"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in drafts" :key="row.uid">
              <td>
                <span class="cust">
                  <template v-if="row.customer">{{ row.customer }}</template>
                  <span v-else class="cust-missing">未填</span>
                  <span v-if="row.customer && row.customer === defaultCustomer" class="src-tag">取自表单</span>
                </span>
              </td>
              <td>
                <!-- 已匹配：精确直接过；模糊匹配把「原图识别」也露出来，便于人工扫一眼 -->
                <template v-if="row.product_id">
                  <span class="picked">
                    <span class="picked-name">{{ row.product_name }}</span>
                    <span v-if="isExact(row)" class="pill pill-ok">精确</span>
                    <span v-else class="pill pill-mid">{{ confidenceText(row) }}</span>
                  </span>
                  <span v-if="!isExact(row) && row.raw_product_name !== row.product_name" class="orig">
                    原图识别：{{ row.raw_product_name }}
                  </span>
                </template>
                <!-- 未匹配：必须手选，否则不允许导入 -->
                <template v-else>
                  <UiAutocomplete
                    :id="`ocr-product-${row.uid}`"
                    :model-value="''"
                    :search-fn="searchProducts"
                    :empty-text="'无匹配结果'"
                    :required="true"
                    placeholder="点击搜索产品…"
                    class="ocr-pick"
                    @select="(item) => pickProduct(row, item)"
                  >
                    <template #option="{ item }">
                      {{ item.name }}
                    </template>
                  </UiAutocomplete>
                  <span class="pick-hint">
                    原图识别「{{ row.raw_product_name || '空' }}」在库内无匹配，请手动选择
                  </span>
                </template>
              </td>
              <td>
                <span class="qty-wrap">
                  <input
                    v-model.number="row.quantity"
                    type="number"
                    min="1"
                    step="1"
                    class="qty-input"
                    :class="{ 'qty-invalid': row.quantity <= 0 }"
                    :aria-label="`${row.product_name} 数量`"
                  />
                  <span v-if="row.unit" class="unit">{{ row.unit }}</span>
                </span>
              </td>
              <td>
                <input v-model="row.note" class="note-input" placeholder="可选" :aria-label="`${row.product_name} 备注`" />
              </td>
              <td>
                <button class="del" :aria-label="`删除 ${row.product_name}`" @click="removeRow(row.uid)">
                  <FontAwesomeIcon icon="times" aria-hidden="true" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <details class="raw">
          <summary>查看识别原文（用于判断是识别错了还是解析错了）</summary>
          <pre class="raw-text">{{ rawText || '(无)' }}</pre>
        </details>
      </template>

      <!-- ============ 一条都没识别到：给三条出路 ============ -->
      <template v-else>
        <div class="guide">
          <div class="guide-icon"><FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" /></div>
          <p class="guide-why">
            这张图没读出货品和数量。常见原因：图片太糊或有遮挡、文字被截断，或者内容本身不是订货信息。
            下面三种方式都能继续。
          </p>
          <div class="exits">
            <div class="exit">
              <span class="exit-t">换一张更清晰的</span>
              <span class="exit-d">正对拍摄、光线均匀、别裁掉文字，聊天截图尽量完整。</span>
              <UiButton variant="primary" size="sm" @click="emit('retry')">重新粘贴</UiButton>
            </div>
            <div class="exit">
              <span class="exit-t">改用 Excel 导入</span>
              <span class="exit-d">大批量或格式规整时更稳。下载模板填好再拖进来。</span>
              <UiButton variant="outline" size="sm" @click="emit('download-template')">下载模板</UiButton>
            </div>
            <div class="exit">
              <span class="exit-t">手工录入这一条</span>
              <span class="exit-d">只有一两条的话，直接填比折腾图片快。</span>
              <UiButton variant="outline" size="sm" @click="emit('go-manual')">去录入</UiButton>
            </div>
          </div>
          <details v-if="rawText" class="raw raw-in-guide" open>
            <summary>识别原文</summary>
            <pre class="raw-text">{{ rawText }}</pre>
          </details>
        </div>
      </template>
    </div>

    <template #footer>
      <template v-if="!showGuide">
        <span class="foot-note">{{ blockReason }}</span>
        <UiButton variant="outline" @click="openModel = false">取消</UiButton>
        <UiButton variant="primary" :disabled="!canConfirm" @click="emit('confirm')">
          导入暂存区（{{ drafts.length }} 项）
        </UiButton>
      </template>
      <template v-else>
        <UiButton variant="outline" @click="openModel = false">关闭</UiButton>
      </template>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * OcrPreviewModal — 粘贴图片识别的结果弹窗
 *
 * 两种形态合一，省掉两套弹窗各自注册粘贴热区的重复：
 * - 有候选条目 → 可编辑确认表（三种匹配态：精确 / 模糊 / 未匹配）
 * - 一条都没识别到 → 指引态，给三条明确出路（需求「提供替代解决方案和操作指引」）
 */
import { computed, ref } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import { useImagePaste } from '@/composables/useImagePaste'
import type { OcrDraftItem, ProductSuggestion } from '../composables/types'

const props = defineProps<{
  /** true = 本次识别一条都没解析出来 → 指引态（**不看** drafts 长度，见 useOrderOcr.emptyResult） */
  showGuide: boolean
  unmatchedCount: number
  invalidQuantityCount: number
  missingCustomerCount: number
  /** 后端提示：客户兜底 / 产品未匹配等，必须让用户看到 */
  warnings: string[]
  rawText: string
  sourceName: string
  /** 表单当前选中的客户，用于标注「取自表单」 */
  defaultCustomer: string
  searchProducts: (query: string) => Promise<ProductSuggestion[]>
}>()

const emit = defineEmits<{
  confirm: []
  retry: []
  'download-template': []
  'go-manual': []
  /** 弹窗内直接粘贴了一张图片，交给父级重新识别 */
  'paste-image': [file: File]
}>()

const openModel = defineModel<boolean>('open', { required: true })
const drafts = defineModel<OcrDraftItem[]>('draftItems', { required: true })

/** 弹窗内的粘贴：优先级高于录入面板的热区，只在弹窗打开时生效 */
const dialogBodyRef = ref<HTMLElement | null>(null)
useImagePaste({
  target: dialogBodyRef,
  onFile: (file) => emit('paste-image', file),
  enabled: () => openModel.value,
  priority: 1,
})

const matchedCount = computed(() => drafts.value.filter((i) => i.product_id).length)
const totalQuantity = computed(() => drafts.value.reduce((sum, i) => sum + (i.quantity || 0), 0))

/**
 * 可以导入：有行，且三道闸门都过。
 * 闸门与 `useOrderOcr.confirmImport` 的校验一一对应——按钮禁用和提交校验
 * 必须用同一组条件，否则会出现「按钮能点但提交被拦」或反过来的错位。
 */
const canConfirm = computed(
  () =>
    drafts.value.length > 0 &&
    props.unmatchedCount === 0 &&
    props.invalidQuantityCount === 0 &&
    props.missingCustomerCount === 0,
)

/** 底栏提示：按最先卡住的那一道说清原因 */
const blockReason = computed(() => {
  if (!drafts.value.length) return '没有可导入的条目'
  if (props.unmatchedCount) return '未匹配的产品需先选择或删除该行，之后才能导入'
  if (props.invalidQuantityCount) return '数量需在 1 以上，请补齐后再导入'
  if (props.missingCustomerCount) return '这些条目还没有客户，请先在表单选择客户'
  return '导入后仍可在暂存区里修改或删除'
})

/** 置信度 1.0 视为精确命中（后端对精确匹配返回 1.0） */
function isExact(row: OcrDraftItem): boolean {
  return row.match_confidence >= 0.999
}

function confidenceText(row: OcrDraftItem): string {
  return `匹配度 ${Math.round((row.match_confidence || 0) * 100)}%`
}

function pickProduct(row: OcrDraftItem, item: ProductSuggestion) {
  row.product_id = item.id
  row.product_name = item.name
  row.match_confidence = 1
}

function removeRow(uid: string) {
  drafts.value = drafts.value.filter((i) => i.uid !== uid)
}
</script>

<style scoped>
.ocr-sub { margin: 0 0 10px; font-size: 12.5px; color: var(--color-text-muted); }
.ocr-sum {
  display: flex; gap: 18px; padding: 9px 12px; margin-bottom: 4px;
  background: var(--color-slate-50, #f8fafc); border-radius: 10px; font-size: 12px;
  color: var(--color-text-secondary);
}
.ocr-sum b { font-size: 13.5px; }
.ocr-sum .ok b { color: var(--color-success-600); }
.ocr-sum .bad b { color: var(--color-danger-600); }

/* 后端提示（客户兜底 / 未匹配）——必须可见，不能只存在状态里 */
.ocr-warn {
  margin: 8px 0 0;
  padding: 8px 12px 8px 28px;
  background: var(--color-warning-50);
  border-radius: 10px;
  font-size: 12px;
  color: var(--color-warning-700);
  list-style: disc;
}
.ocr-empty {
  margin: 14px 0 6px;
  padding: 18px 12px;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-muted);
  background: var(--color-slate-50, #f8fafc);
  border-radius: 10px;
}

.ocr-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.ocr-table th {
  text-align: left; font-weight: 600; font-size: 12px; padding: 8px;
  color: var(--color-text-secondary); border-bottom: 1px solid var(--color-border);
}
.ocr-table td { padding: 8px; border-bottom: 1px solid var(--color-border-light); vertical-align: top; }
.ocr-table tr:last-child td { border-bottom: 0; }
.c-cust { width: 150px; }
.c-qty { width: 108px; }
.c-note { width: 130px; }
.c-del { width: 34px; }

.cust { display: inline-flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.cust-missing { color: var(--color-danger-600); }
.src-tag {
  font-size: 10.5px; font-weight: 600; color: var(--color-ocean-text, #02669e);
  background: var(--color-ocean-light, #d4f1f4); padding: 1px 6px; border-radius: 999px;
}

.picked { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.picked-name { font-weight: 600; }
.pill { font-size: 10.5px; font-weight: 700; padding: 1px 7px; border-radius: 999px; white-space: nowrap; }
.pill-ok { background: var(--color-success-50); color: var(--color-success-700); }
.pill-mid { background: var(--color-warning-50); color: var(--color-warning-700); }
.orig { display: block; margin-top: 3px; font-size: 11px; color: var(--color-text-muted); }

.ocr-pick { width: 100%; }
.pick-hint { display: block; margin-top: 3px; font-size: 11px; color: var(--color-danger-600); }

.qty-wrap { display: inline-flex; align-items: center; gap: 4px; }
.qty-input {
  width: 70px; padding: 6px 9px; text-align: right; font-size: 13px; font-family: inherit;
  border: 1px solid var(--color-border); border-radius: 9px; outline: none;
}
.qty-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 1px; }
.qty-invalid { border-color: var(--color-danger-400); background: var(--color-danger-50); }
.unit { font-size: 11.5px; color: var(--color-text-muted); }

.note-input {
  width: 100%; padding: 6px 9px; font-size: 12.5px; font-family: inherit;
  border: 1px solid var(--color-border); border-radius: 9px; outline: none;
}
.note-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 1px; }

.del {
  background: none; border: 0; cursor: pointer; padding: 4px 6px;
  color: var(--color-text-muted); border-radius: 6px;
}
.del:hover { color: var(--color-danger-500); background: var(--color-danger-50); }

.raw { margin-top: 12px; }
.raw summary { font-size: 12px; color: var(--color-text-secondary); cursor: pointer; }
.raw-text {
  margin: 8px 0 0; padding: 10px; max-height: 180px; overflow: auto;
  background: var(--color-slate-50, #f8fafc); border: 1px solid var(--color-border-light);
  border-radius: 10px; font-size: 11.5px; line-height: 1.6; white-space: pre-wrap; word-break: break-all;
}

.guide { text-align: center; padding: 4px 0 8px; }
.guide-icon {
  width: 48px; height: 48px; margin: 0 auto 10px; border-radius: 14px;
  display: flex; align-items: center; justify-content: center; font-size: 20px;
  background: var(--color-warning-50); color: var(--color-warning-700);
}
.guide-why {
  max-width: 460px; margin: 0 auto 18px; font-size: 12.5px; color: var(--color-text-muted);
}
.exits { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; text-align: left; }
.exit {
  display: flex; flex-direction: column; gap: 6px; padding: 13px;
  border: 1px solid var(--color-border); border-radius: var(--radius-input, 12px); background: white;
}
.exit-t { font-size: 13px; font-weight: 700; }
.exit-d { flex: 1; font-size: 11.5px; color: var(--color-text-muted); }
.exit :deep(button) { align-self: flex-start; }
.raw-in-guide { text-align: left; }

.foot-note { margin-right: auto; font-size: 11.5px; color: var(--color-text-muted); }

@media (max-width: 720px) {
  .exits { grid-template-columns: 1fr; }
}
</style>

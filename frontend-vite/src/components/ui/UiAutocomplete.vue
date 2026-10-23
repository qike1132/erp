<script setup lang="ts" generic="T extends object">
/**
 * UiAutocomplete — 产品/资源搜索自动补全
 *
 * 基于 PrimeVue AutoComplete，封装为标准接口。
 * 消除 5 个视图 664 行重复的 autocomplete 代码。
 *
 * Props:
 *   modelValue     - v-model: 搜索文本
 *   suggestions    - 外部传入的建议列表（静态模式）
 *   searchFn       - 远程搜索函数: (query: string) => Promise<T[]>
 *   optionLabel    - 显示字段名（默认 'name'）
 *   placeholder
 *   disabled
 *   debounceMs     - 防抖毫秒（默认 300）
 *   minQueryLength - 最小触发搜索长度（默认 1）
 *
 * Emits:
 *   update:modelValue - v-model 双向绑定
 *   select            - 选中项: (item: T) => void
 *   search            - 搜索文本变化: (query: string) => void
 *
 * Slots:
 *   option   - 自定义选项模板: { item, index }
 *   header   - 列表头部
 *   footer   - 列表尾部
 *
 * 示例：
 *   <UiAutocomplete
 *     v-model="searchText"
 *     :searchFn="api.searchProducts"
 *     placeholder="输入产品名称搜索"
 *     optionLabel="name"
 *     @select="onSelect"
 *   >
 *     <template #option="{ item }">
 *       {{ item.name }} <span class="text-xs text-text-muted">{{ item.barcode }}</span>
 *     </template>
 *   </UiAutocomplete>
 */
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import AutoComplete from 'primevue/autocomplete'
import type { AutoCompleteCompleteEvent } from 'primevue'
import { showToast } from '@/composables/useToast'

const props = withDefaults(
  defineProps<{
    modelValue?: string
    suggestions?: T[]
    searchFn?: (query: string) => Promise<T[]>
    /** 「打开下拉即列全量」：调用方提供后，聚焦/清空输入（空关键字）时改调它，
     * 下拉显示全量列表而不是一片空白。**不传则本组件行为一字不变**（其余 6 个页面
     * 不提供，所以不会凭空弹出空下拉）。典型用法见下单页产品名称。 */
    listFn?: () => Promise<T[]>
    optionLabel?: string
    placeholder?: string
    disabled?: boolean
    debounceMs?: number
    minQueryLength?: number
    /** 触发搜索前的停顿毫秒数（透传给 PrimeVue AutoComplete 的 delay）。
     * 调大后快速连续键入不会逐键触发搜索，避免下拉面板/加载态逐键闪烁。 */
    searchDelayMs?: number
    /** 搜索期间是否在输入框内显示加载 spinner。
     * 在表格上方打开面板的页面可关闭，避免逐键出现转圈闪烁。 */
    showLoading?: boolean
    /** PrimeVue AutoComplete appendTo。默认 'body' 保证父容器 overflow:hidden 时不裁剪。
     * 传 undefined 则渲染在组件树内（适用于无裁剪风险的场景，避免 body 级重排跳动）。 */
    appendTo?: string
    /** 选中建议后抑制下拉面板再次自动展开（编辑已提交的搜索词时不再弹面板，
     * 避免面板遮挡下方内容造成闪烁）；清空输入后自动恢复。 */
    suppressAfterSelect?: boolean
    /** 内层 input 的 id，用于与外层 <label for> 配对 */
    id?: string
    /** 无结果时面板内的文案。调用方可用它区分「无匹配」与「请求失败」 */
    emptyText?: string
    /** 必填项：向辅助技术暴露 aria-required */
    required?: boolean
  }>(),
  {
    modelValue: '',
    suggestions: () => [],
    placeholder: '请输入搜索关键词',
    disabled: false,
    minQueryLength: 1,
    optionLabel: 'name',
    searchDelayMs: 300,
    showLoading: true,
    appendTo: 'body',
    suppressAfterSelect: false,
    searchFn: undefined,
    listFn: undefined,
    debounceMs: undefined,
    id: undefined,
    emptyText: undefined,
  },
)

defineSlots<{
  option: (props: { item: T; index: number }) => unknown
  header: () => unknown
  footer: () => unknown
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  select: [item: T]
  search: [query: string]
}>()

// ============================================================
// 内部状态
// ============================================================
const internalSuggestions = ref<T[]>([])
const loading = ref(false)
let requestSeq = 0

// 只有大列表才启用虚拟滚动：小列表走普通渲染，避免无谓的
// ResizeObserver/测量开销（也让 jsdom 下的交互测试保持真实语义）
const virtualScrollerOptions = computed(() =>
  internalSuggestions.value.length > 50 ? { itemSize: 40 } : undefined,
)

// 选中/提交后抑制下拉：编辑已选中的搜索词时不再触发搜索与面板展开，清空输入后自动恢复
const suppressSearch = ref(false)

/** 供父组件控制抑制状态（如点击查询按钮提交后主动抑制） */
function setSuppressed(v: boolean) {
  suppressSearch.value = v
}

const acRef = ref<{ $el?: HTMLElement; show?: () => void; hide?: () => void } | null>(null)

/** 把焦点交回输入框（连续录入场景：提交一条后无需重新 Tab 寻找入口） */
function focusInput() {
  acRef.value?.$el?.querySelector('input')?.focus()
}

// ============================================================
// 搜索逻辑 — @complete 驱动搜索 + requestSeq 防过期
// ============================================================
function onInputChange(value: string | Record<string, unknown>) {
  let displayValue: string
  // PrimeVue 选中项时 emit 的是完整 option 对象而非 label 字符串，需提取
  if (value != null && typeof value === 'object' && !Array.isArray(value)) {
    const labelKey = typeof props.optionLabel === 'string' ? props.optionLabel : 'name'
    displayValue = (value[labelKey] as string) ?? ''
  } else {
    displayValue = String(value ?? '')
  }
  emit('update:modelValue', displayValue)
}

function onComplete(event: AutoCompleteCompleteEvent) {
  triggerSearch(event.query)
}

/**
 * 点击输入框 → 列全量并展开面板。只在调用方提供 listFn 时启用 —— 其余页面点输入框
 * 不打任何请求、也不会弹出一个空下拉。
 *
 * ⚠️ 刻意挂在输入框的**原生 click** 上，而不是 PrimeVue 的 `focus` 事件：
 * 选中一项后 PrimeVue 会把焦点交回输入框，`focus` 会**再触发一次** —— 于是刚选完面板
 * 又被重新打开，用户看到的是「列表没关闭」（2026-10-10 线上实测，`listFn` 被调了两次）。
 * click 是真实用户手势，选中引起的那次聚焦不会产生 click，天然把两者分开。
 *
 * ⚠️ 也不能拿 modelValue 当关键字传给 triggerSearch：那会变成「拿已选产品的名字去搜」，
 * 而那个名字当然能搜到它自己 —— 面板里冒出一条与输入框**一模一样**的条目（同一个 bug 的
 * 另一种表现，2026-10-10 首报）。点击的语义是「列该客户全部 SKU」。
 */
function onInputClick() {
  if (!props.listFn || suppressSearch.value) return
  triggerSearch('')
  acRef.value?.show?.()
}

/** PrimeVue 不对外暴露内层 input，原生监听只能自己在挂载后挂上、卸载时摘掉 */
onMounted(() => {
  acRef.value?.$el?.querySelector('input')?.addEventListener('click', onInputClick)
})

onBeforeUnmount(() => {
  acRef.value?.$el?.querySelector('input')?.removeEventListener('click', onInputClick)
})

function triggerSearch(query: string) {
  const q = query.trim()

  // 已提交搜索后编辑输入框：不弹下拉（避免面板遮挡下方表格闪烁）
  if (suppressSearch.value) {
    internalSuggestions.value = []
    loading.value = false
    return
  }

  // 静态建议列表
  if (props.suggestions && props.suggestions.length > 0) {
    const ql = q.toLowerCase()
    internalSuggestions.value = props.suggestions.filter((item) => {
      const label = (item as Record<string, unknown>)[props.optionLabel!]
      return typeof label === 'string' && label.toLowerCase().includes(ql)
    })
    emit('search', q)
    return
  }

  // 「打开即列全量」：空关键字时改调 listFn，下拉显示全量列表而不是空列表。
  // 放在 searchFn 之前，避免被 minQueryLength 的早退挡掉。
  if (!q && props.listFn) {
    const listSeq = ++requestSeq
    loading.value = true
    props.listFn()
      .then((results) => {
        if (listSeq === requestSeq) {
          internalSuggestions.value = results || []
          loading.value = false
        }
      })
      .catch(() => {
        if (listSeq === requestSeq) {
          internalSuggestions.value = []
          loading.value = false
          // P2（2026-10-24）：搜索失败不能显示成「无匹配结果」——用户会以为产品不存在
          // 而转去手工建重复产品。与 useOcrPaste 的口径对齐，明确提示失败。
          showToast('搜索失败，请重试', 'error')
        }
      })
    emit('search', q)
    return
  }

  // 远程搜索
  if (!props.searchFn || q.length < props.minQueryLength!) {
    internalSuggestions.value = []
    return
  }

  const seq = ++requestSeq
  loading.value = true

  props.searchFn(q)
    .then((results) => {
      if (seq === requestSeq) {
        internalSuggestions.value = results || []
        loading.value = false
      }
    })
    .catch(() => {
      if (seq === requestSeq) {
        internalSuggestions.value = []
        loading.value = false
        // P2：同上，远程搜索失败要明确提示（否则空态文案会被当成「没搜到」）
        showToast('搜索失败，请重试', 'error')
      }
    })

  emit('search', q)
}

function onItemSelect(event: { value: T }) {
  if (props.suppressAfterSelect) {
    suppressSearch.value = true
  }
  emit('select', event.value)
}

// 当外部 suggestions 变化时同步
watch(
  () => props.suggestions,
  (val) => {
    if (val?.length) {
      internalSuggestions.value = [...val]
    }
  },
  { immediate: true },
)

// 输入清空 = 开始新搜索，恢复下拉功能
watch(
  () => props.modelValue,
  (val) => {
    if (!val) {
      suppressSearch.value = false
    }
  },
)

defineExpose({ setSuppressed, focusInput })
</script>

<template>
  <AutoComplete
    ref="acRef"
    :model-value="modelValue"
    :suggestions="internalSuggestions"
    :option-label="(optionLabel as string)"
    :placeholder="placeholder"
    :disabled="disabled"
    :input-id="id"
    :loading="showLoading ? loading : false"
    :delay="searchDelayMs"
    :min-length="minQueryLength"
    :append-to="(appendTo as string | undefined)"
    :show-empty-message="!suppressSearch"
    :empty-search-message="emptyText"
    :virtual-scroller-options="virtualScrollerOptions"
    :pt="required ? { pcInputText: { root: { 'aria-required': 'true' } } } : undefined"
    @update:model-value="onInputChange"
    @complete="onComplete"
    @item-select="onItemSelect"
  >
    <template v-if="$slots.option" #option="slotProps">
      <slot name="option" :item="slotProps.option" :index="slotProps.index" />
    </template>
  </AutoComplete>
</template>

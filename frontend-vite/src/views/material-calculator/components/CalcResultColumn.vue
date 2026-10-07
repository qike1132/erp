<template>
  <div class="mc-col mc-col-results">
    <div class="mc-col-title">
      <FontAwesomeIcon icon="chart-pie" aria-hidden="true" />
      物料用量计算结果
      <span class="mc-col-tail">合计 <b>{{ totalRows }}</b> 项</span>
    </div>

    <!-- 空态：既无分块也无扁平结果 -->
    <div v-if="isEmpty" class="mc-empty-state">
      <FontAwesomeIcon icon="calculator" aria-hidden="true" />
      <span>选择产品并输入数量后自动计算</span>
    </div>

    <template v-else>
      <!-- 作用域条：汇总 TAB + 各产品 TAB → 左侧分段控件切换；
           仅 1 个作用域 → 纯文本名（无 TAB，行为与旧版一致）。
           右侧常驻当前视图的产品/数量信息，切换时同步更新。 -->
      <div class="mc-scope-bar">
        <div v-if="scopeTabs.length > 1" class="mc-seg" role="tablist" aria-label="切换作用域">
          <button
            v-for="(g, gi) in scopeTabs"
            :key="groupKey(g)"
            type="button"
            role="tab"
            :title="scopeTabLabels[gi]"
            :class="{ active: groupKey(g) === activeScopeKey }"
            :aria-selected="groupKey(g) === activeScopeKey"
            @click="activeScopeKey = groupKey(g)"
          >
            {{ scopeTabLabels[gi] }}
          </button>
        </div>
        <span v-else-if="activeGroup" class="mc-scope-name">{{ groupName(activeGroup) }}</span>

        <span class="mc-scope-meta">
          <!-- 汇总视图：产品数 + 订单合计；产品视图：该产品名 + 数量 -->
          <template v-if="isSummary">
            <span v-if="summary.productCount > 0" class="mc-scope-product">
              {{ summary.productCount }} 个产品
            </span>
            <span class="mc-scope-qty">合计 <b>{{ summary.totalQuantity }}</b> 件</span>
          </template>
          <template v-else-if="activeGroup">
            <span v-if="activeGroup.product_name" class="mc-scope-product">{{ activeGroup.product_name }}</span>
            <span class="mc-scope-qty">数量 <b>{{ activeGroup.quantity }}</b></span>
          </template>
        </span>
      </div>

      <div class="mc-result-content">
        <!-- 分块卡 / 汇总 / 扁平回退共用同一份 section 视图模型（0 项分类不进入数组） -->
        <CalcCategoryBlock
          v-for="section in sections"
          :key="section.key"
          :category-key="section.key"
          :label="section.label"
          :icon="section.icon"
          :rows="section.rows"
          :show-sku-count="isSummary"
          :collapsed="sectionCollapsed(section.key)"
          @toggle="toggleSection(section.key)"
        />

        <p v-if="!sections.length" class="mc-result-hint">当前作用域暂无用量数据</p>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * 物料用量计算结果列。
 *
 * 渲染契约：
 * - 分块模式（`calcGroups` 非空）：**「汇总」TAB 恒居首位且默认选中**——相同
 *   「供应商 + 物料名称 + 规格/色号」的行合并求和（见 utils/calcSummary.ts）；
 *   后续 TAB 为「按产品查看」的原始分块（多角色 BOM 能力保留），同一时刻只渲染
 *   1 个视图。默认 BOM 恒首块 → 单产品场景无 TAB、行为与旧版一致。
 * - 扁平回退（A-5，旧后端 / `calcGroups` 缺失）：行为与旧版一致，走同一份 section 视图模型。
 * - 复合 row-key（A-9）：`__rk` 由「分类 + 名称 + 规格 + 供应商 + 单位」拼成，
 *   保证「同分类同名但规格/供应商/单位不同」的行全部渲染、不丢行。
 * - 0 项分类不渲染表头（原先会渲染 `(0 项)` 空块，是纯噪声）。
 *
 * 单个分类区块（折叠头 + 紧凑表 + 单位换算）在 `CalcCategoryBlock.vue`。
 */
import { reactive, ref, computed, watch } from 'vue'
import type { MaterialCalcRow, MaterialCalcScopeGroup } from '@/api'
import { CALC_CATEGORY_LIST } from '@/composables/useMaterialCalculator'
import { scopeKeyOf, scopeNameOf } from '@/utils/roleMatrix'
import { deriveCalcSummary, type SummaryRow } from '@/utils/calcSummary'
import CalcCategoryBlock from './CalcCategoryBlock.vue'

const props = defineProps<{
  calcResults: Record<string, MaterialCalcRow[]>
  hasResults: boolean
  /** 按「产品 × 作用域」分块；缺失/空 → 回退扁平渲染（A-5）。 */
  calcGroups?: MaterialCalcScopeGroup[]
}>()

/** 带复合 row-key 的行视图模型。 */
type CalcRowVM = MaterialCalcRow & { __rk: string }

/** 分类区块的统一视图模型（分块 / 扁平两种来源归一化后的产物）。 */
interface ResultSection {
  key: string
  label: string
  icon: string
  rows: CalcRowVM[]
}

// 折叠状态：键 = `<scopeKey>::<category>`，不同作用域互不影响
const collapsed = reactive<Record<string, boolean>>({})
const categoryList = CALC_CATEGORY_LIST

const hasGroups = computed(() => (props.calcGroups?.length ?? 0) > 0)
/** 既无分块也无扁平结果 → 首次进入或尚未计算 */
const isEmpty = computed(() => !hasGroups.value && !props.hasResults)

// ============================================================
// 作用域切换（「汇总」恒首 + 各产品分块）
// ============================================================
/** 汇总视图的唯一作用域键（不与 scopeKeyOf 的 `p|…|r|…` 形态冲突）。 */
const SUMMARY_SCOPE_KEY = '__summary__'

/** 是否多产品（多作用域）→ 需要「汇总」TAB。 */
const hasMultipleScopes = computed(() => (props.calcGroups?.length ?? 0) > 1)

/** 汇总结果（groups 非空时派生；单产品场景不会用到但派生无副作用）。 */
const summary = computed(() => deriveCalcSummary(props.calcGroups))

/** TAB 列表：多作用域时「汇总」恒居首，其后为各产品分块；单作用域为空数组（无 TAB）。 */
const scopeTabs = computed<(MaterialCalcScopeGroup | null)[]>(() => {
  if (!hasMultipleScopes.value) return []
  return [null, ...(props.calcGroups ?? [])]
})
const scopeKeys = computed(() => scopeTabs.value.map((g) => groupKey(g)))
const activeScopeKey = ref('')

/** 当前是否在汇总视图。 */
const isSummary = computed(() => activeScopeKey.value === SUMMARY_SCOPE_KEY)

// 结果重算后旧作用域可能消失（取消选品 / 换角色）→ 回落到首块，避免空渲染
watch(
  scopeKeys,
  (keys) => {
    if (!keys.includes(activeScopeKey.value)) activeScopeKey.value = keys[0] ?? ''
  },
  { immediate: true },
)

const activeGroup = computed<MaterialCalcScopeGroup | null>(() =>
  (scopeTabs.value.find((g) => g != null && scopeKeyOf(g) === activeScopeKey.value) as MaterialCalcScopeGroup | undefined)
    ?? (hasMultipleScopes.value ? null : (props.calcGroups?.[0] ?? null)),
)

/**
 * 分段控件标签：首个 TAB 固定「汇总」，其余沿用「能唯一区分各作用域」的
 * 最短维度（见 scopeTabLabels 原 docstring——多产品 × 默认 BOM 时角色名同名，
 * 降级到产品名；都不唯一则两者拼接）。
 */
const scopeTabLabels = computed<string[]>(() => {
  const list = scopeTabs.value
  if (!list.length) return []
  const rest = list.slice(1) as MaterialCalcScopeGroup[]
  const roleNames = rest.map((g) => groupName(g))
  const productNames = rest.map((g) => (g.product_name ?? '').trim())
  const allUnique = (arr: string[]) => {
    const nonEmpty = arr.filter(Boolean)
    return nonEmpty.length === arr.length && new Set(nonEmpty).size === arr.length
  }
  const useRole = allUnique(roleNames)
  const useProduct = !useRole && allUnique(productNames)
  const restLabels = rest.map((g, i) => {
    if (useRole) return roleNames[i] ?? ''
    if (useProduct) return productNames[i] ?? ''
    return [productNames[i] ?? '', roleNames[i] ?? ''].filter(Boolean).join(' · ')
  })
  return ['汇总', ...restLabels]
})

/** 当前折叠/展开状态所属的作用域前缀（扁平回退固定为 `flat`）。 */
const scopePrefix = computed(() => activeScopeKey.value || 'flat')

// ============================================================
// 视图模型
// ============================================================
/** 作用域唯一键：汇总视图 → `__summary__`；产品分块 → `p|<pid>|r|<rid|default>`。 */
function groupKey(group: MaterialCalcScopeGroup | null): string {
  if (!group) return SUMMARY_SCOPE_KEY
  return scopeKeyOf(group)
}

/** 作用域展示名（默认 BOM → 默认BOM；角色名缺失 → 角色#<id>）。 */
function groupName(group: MaterialCalcScopeGroup | null): string {
  return group ? scopeNameOf(group) : ''
}

/** 读取某分类的行数组（安全索引，避免 undefined）。 */
function groupCat(group: MaterialCalcScopeGroup, category: string): MaterialCalcRow[] {
  const record = group as unknown as Record<string, MaterialCalcRow[] | undefined>
  const value = record[category]
  return Array.isArray(value) ? value : []
}

/**
 * 复合 row-key（A-9）：`<prefix>|<category>|<名称>|<规格>|<供应商>|<单位>`。
 * 同分类同名但规格/供应商/单位任一不同的行 → key 唯一 → 全部渲染。
 */
function rowKeyOf(prefix: string, category: string, row: MaterialCalcRow): string {
  return [
    prefix,
    category,
    row.material_name || row.name || '',
    row.specification || '',
    row.supplier_name || '',
    row.unit || '',
  ].join('|')
}

/** 给行附加 `__rk`（作为 v-for 的唯一键）。 */
function toVM(rows: MaterialCalcRow[] | undefined, prefix: string, category: string): CalcRowVM[] {
  return (rows ?? []).map((row) => ({ ...row, __rk: rowKeyOf(prefix, category, row) }))
}

/** 汇总行的 row-key：合并键天然唯一（分类+名称+规格+供应商+单位），`__summary__` 前缀防撞。 */
function summaryToVM(rows: SummaryRow[], category: string): CalcRowVM[] {
  return rows.map((row) => ({ ...row, __rk: rowKeyOf(SUMMARY_SCOPE_KEY, category, row) }))
}

/** 分类区块列表：汇总视图取合并行，分块取当前作用域，扁平取 `calcResults`；0 项分类剔除。 */
const sections = computed<ResultSection[]>(() => {
  const group = activeGroup.value
  return categoryList
    .map((cat) => ({
      key: cat.key as string,
      label: cat.label,
      icon: cat.icon,
      rows: isSummary.value
        ? summaryToVM(summary.value.rows[cat.key as keyof typeof summary.value.rows] ?? [], cat.key)
        : group
          ? toVM(groupCat(group, cat.key), scopeKeyOf(group), cat.key)
          : toVM(props.calcResults?.[cat.key], 'flat', cat.key),
    }))
    .filter((section) => section.rows.length > 0)
})

/** 列头右侧合计（当前作用域全部行的总数）。 */
const totalRows = computed(() => sections.value.reduce((sum, s) => sum + s.rows.length, 0))

function toggleSection(category: string) {
  const key = `${scopePrefix.value}::${category}`
  collapsed[key] = !collapsed[key]
}

function sectionCollapsed(category: string): boolean {
  return !!collapsed[`${scopePrefix.value}::${category}`]
}
</script>

<style scoped>
/* 列头（.mc-col-title / .mc-col-tail）来自全局 app.css —— scoped 命中不了，
   且历史上正因写在 scoped 里导致 padding/字重/下边框三项静默失效。
   分类区块样式在 CalcCategoryBlock.vue。 */

/* === 作用域条（固定，不随结果滚动） === */
.mc-scope-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-2);
  min-height: 40px;
  min-width: 0;
  padding: var(--sp-2) var(--sp-3);
  border-bottom: var(--bw) solid var(--color-border-light);
  flex-shrink: 0;
}

/* 作用域数多 / 产品名长时：标签条**换行**而不是横向滚动。
   原先是单行 overflow-x:auto + 隐藏滚动条 → SKU 一多，后面的标签被挤出可视区
   又没有滚动提示，名称还被 220px 截断，单个 SKU 根本看不清。
   flex-basis:100% 让标签条独占整行（占满列宽后长名也基本放得下），
   meta 随之换到下一行右对齐；超长名单个仍省略号，靠 title 属性出全称。
   （本组件模板内的元素，scoped 能命中全局类 .mc-seg） */
.mc-scope-bar .mc-seg {
  flex: 1 1 100%;
  min-width: 0;
  flex-wrap: wrap;
  height: auto;
  min-height: 30px;
  overflow: visible;
  row-gap: 2px;
}
/* 换行后容器高度自适应，全局的 `height: 100%` 会塌成 0 → 显式给按钮高度 */
.mc-scope-bar .mc-seg > button {
  height: 26px;
  min-width: 0;
  max-width: 100%;
  flex-shrink: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mc-scope-name {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--color-text);
  white-space: nowrap;
}

.mc-scope-meta {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
  /* 标签条独占整行后 meta 落到下一行右对齐；不收缩，超长产品名由内部
     .mc-scope-product 的省略号兜底 */
  flex: 0 0 auto;
}

.mc-scope-product {
  font-size: var(--fs-cap);
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mc-scope-qty {
  font-size: var(--fs-cap);
  color: var(--color-text-muted);
  white-space: nowrap;
}
.mc-scope-qty b {
  color: var(--color-primary-700);
  font-weight: 600;
}

/* === 结果滚动区 === */
.mc-result-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--sp-1) var(--sp-3) var(--sp-3);
}

/* === 空态 === */
.mc-empty-state {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  padding: var(--sp-6) var(--sp-4);
  color: var(--color-text-muted);
  font-size: var(--fs-sm);
}
.mc-empty-state :deep(svg) {
  width: 24px;
  height: 24px;
  opacity: 0.5;
}

.mc-result-hint {
  margin: var(--sp-6) 0 0;
  text-align: center;
  font-size: var(--fs-xs);
  color: var(--color-text-muted);
}
</style>

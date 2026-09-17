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
      <!-- 作用域条：≥2 个作用域 → 左侧分段控件切换；单作用域 → 纯文本名。
           右侧常驻当前作用域的产品名与数量，切换时同步更新。 -->
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
          <span v-if="activeGroup?.product_name" class="mc-scope-product">{{ activeGroup.product_name }}</span>
          <span v-if="activeGroup" class="mc-scope-qty">数量 <b>{{ activeGroup.quantity }}</b></span>
        </span>
      </div>

      <div class="mc-result-content">
        <!-- 分块卡 / 扁平回退共用同一份 section 视图模型（0 项分类不进入数组） -->
        <CalcCategoryBlock
          v-for="section in sections"
          :key="section.key"
          :category-key="section.key"
          :label="section.label"
          :icon="section.icon"
          :rows="section.rows"
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
 * - 分块模式（`calcGroups` 非空）：顶部作用域条切换，**同一时刻只渲染 1 个作用域**的用量表；
 *   默认 BOM 恒首块 → 初始选中它。窄列里纵向堆叠多张卡会把每张表压到只剩表头，故改为切换。
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
// 作用域切换
// ============================================================
const scopeTabs = computed<MaterialCalcScopeGroup[]>(() => props.calcGroups ?? [])
const scopeKeys = computed(() => scopeTabs.value.map((g) => scopeKeyOf(g)))
const activeScopeKey = ref('')

// 结果重算后旧作用域可能消失（取消选品 / 换角色）→ 回落到首块，避免空渲染
watch(
  scopeKeys,
  (keys) => {
    if (!keys.includes(activeScopeKey.value)) activeScopeKey.value = keys[0] ?? ''
  },
  { immediate: true },
)

const activeGroup = computed<MaterialCalcScopeGroup | null>(
  () => scopeTabs.value.find((g) => scopeKeyOf(g) === activeScopeKey.value) ?? null,
)

/**
 * 分段控件标签：用「能唯一区分各作用域」的最短维度。
 * 真实数据常见「多个产品 × 各自默认 BOM」——此时 `role_name` 全是「默认BOM」，
 * 直接展示角色名会得到两个同名标签，用户无法判断在切什么。降级次序：
 *   角色名互不相同 → 用角色名；否则产品名互不相同 → 用产品名；再否则两者拼接。
 */
const scopeTabLabels = computed<string[]>(() => {
  const list = scopeTabs.value
  if (!list.length) return []
  const roleNames = list.map((g) => groupName(g))
  const productNames = list.map((g) => (g.product_name ?? '').trim())
  const allUnique = (arr: string[]) => {
    const nonEmpty = arr.filter(Boolean)
    return nonEmpty.length === arr.length && new Set(nonEmpty).size === arr.length
  }
  const useRole = allUnique(roleNames)
  const useProduct = !useRole && allUnique(productNames)
  return list.map((_g, i) => {
    if (useRole) return roleNames[i] ?? ''
    if (useProduct) return productNames[i] ?? ''
    return [productNames[i] ?? '', roleNames[i] ?? ''].filter(Boolean).join(' · ')
  })
})

/** 当前折叠/展开状态所属的作用域前缀（扁平回退固定为 `flat`）。 */
const scopePrefix = computed(() => activeScopeKey.value || 'flat')

// ============================================================
// 视图模型
// ============================================================
/** 作用域唯一键（`p|<pid>|r|<rid|default>`）。接受 null 以兼容模板中 `v-else-if` 的收窄失效。 */
function groupKey(group: MaterialCalcScopeGroup | null): string {
  return group ? scopeKeyOf(group) : ''
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

/** 分类区块列表：分块来源取当前作用域，扁平来源取 `calcResults`；0 项分类剔除。 */
const sections = computed<ResultSection[]>(() => {
  const group = activeGroup.value
  return categoryList
    .map((cat) => ({
      key: cat.key as string,
      label: cat.label,
      icon: cat.icon,
      rows: group
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
  gap: var(--sp-2);
  min-height: 40px;
  min-width: 0;
  padding: var(--sp-2) var(--sp-3);
  border-bottom: var(--bw) solid var(--color-border-light);
  flex-shrink: 0;
}

/* 作用域数多 / 产品名长时，让分段控件自身横向滚动而不是撑破窄列。
   （本组件模板内的元素，scoped 能命中全局类 .mc-seg） */
.mc-scope-bar .mc-seg {
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
}
.mc-scope-bar .mc-seg::-webkit-scrollbar {
  display: none;
}
.mc-scope-bar .mc-seg > button {
  min-width: 0;
  /* 220px：实测最长真实产品名「招财猫盲盒毛绒挂件(混4款)」需 167px，
     160px 会白截断 7px（作用域条可用 352px、两标签完整只需 223px）。
     上限只用于防止单个超长名吃掉整条 bar，超出部分由 .mc-seg 横向滚动兜底 */
  max-width: 220px;
  flex-shrink: 0;
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

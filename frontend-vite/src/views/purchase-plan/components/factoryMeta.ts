// 工厂的展示元数据（排序 + 配色档）。
//
// 原先「东莞→主色、湖北→紫、其余→中性」这段映射在 PlanMonthGrid / PlanDayDetail /
// SkuSummaryTable / PurchasePlanDailyTab 里各写了一份；新增第三个工厂时要改四处，
// 漏一处就出现同一天两个组件颜色不一致。集中到此处，各组件只负责把色档拼成自己的类名。
// 注：PurchasePlanFactoryFilter 的色点走 `[data-tone=...]` 的 CSS 选择器，故仅复用排序。

/** 具名工厂的固定展示顺序；未列出的（如「未标注」）排在其后、按字典序 */
export const FACTORY_ORDER = ['东莞', '湖北']

/** 按固定顺序排列工厂名：东莞 → 湖北 → 其余按字典序 */
export function orderFactories(names: string[]): string[] {
  const named = FACTORY_ORDER.filter(f => names.includes(f))
  const rest = names.filter(f => !FACTORY_ORDER.includes(f)).sort()
  return [...named, ...rest]
}

/** 工厂 → 配色档：dg（东莞，主色）/ hb（湖北，紫）/ other（其余，中性） */
export function factoryTone(name?: string): 'dg' | 'hb' | 'other' {
  if (name === '东莞') return 'dg'
  if (name === '湖北') return 'hb'
  return 'other'
}

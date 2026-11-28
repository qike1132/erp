/**
 * useSummaryRateFlush — 损耗率输入的防抖与「不丢值」提交（从 SummaryPanel 抽出，
 * 2026-11-28 生产事故修复：防抖窗口内刷新/关闭会静默丢弃「已输入未提交」的最终值）。
 *
 * 职责（SummaryPanel 保持纯转发）：
 * - 统一损耗率 / 逐布料行损耗率的 300ms 防抖（合并连续输入，只发最后一次）；
 * - 挂起值保存在本 composable，失焦（flushLossRate / flushFabricLossRate）、
 *   返回按钮（flushAllPendingRateEdits → emit close 之前）、卸载兜底都能立即提交；
 * - emit 回调由调用方注入（组件的 emits 契约留在组件层）。
 *
 * 防抖定时器**必须留在整页外壳**（组件随页签 v-if 卸载，定时器放子组件会在
 * 切页签时丢输入——见 SummaryPanel.vue 2026-10-31 注）。
 */

const RATE_DEBOUNCE_MS = 300

export interface SummaryRateFlushOptions {
  /** 统一率到期/flush 时提交 */
  onUnified: (rate: number) => void
  /** 布料行率到期/flush 时提交（落库坐标 gi/si/fi） */
  onFabric: (gi: number, si: number, fi: number, rate: number) => void
}

export function useSummaryRateFlush({ onUnified, onFabric }: SummaryRateFlushOptions) {
  // —— 统一损耗率 ——
  let unifiedTimer: ReturnType<typeof setTimeout> | null = null
  /** 防抖窗口内挂起的统一率（最近一次输入）；null = 无挂起值 */
  let unifiedPending: number | null = null

  function applyLossRateDebounced(v: number) {
    unifiedPending = v
    if (unifiedTimer) clearTimeout(unifiedTimer)
    unifiedTimer = setTimeout(() => {
      unifiedTimer = null
      unifiedPending = null
      onUnified(v)
    }, RATE_DEBOUNCE_MS)
  }

  /** 立即提交挂起的统一率（失焦 / Enter / 返回前）；无挂起值时是空操作。 */
  function flushLossRate() {
    if (unifiedTimer) { clearTimeout(unifiedTimer); unifiedTimer = null }
    if (unifiedPending === null) return
    const v = unifiedPending
    unifiedPending = null
    onUnified(v)
  }

  // —— 逐布料行损耗率：按行独立计时，快速连续改多行时不能互相取消 ——
  const fabricTimers = new Map<string, ReturnType<typeof setTimeout>>()
  /** 防抖窗口内各布料行挂起的率值（键 = `${gi}-${si}-${fi}`） */
  const fabricPending = new Map<string, number>()

  function applyFabricLossRateDebounced(gi: number, si: number, fi: number, v: number) {
    const key = `${gi}-${si}-${fi}`
    fabricPending.set(key, v)
    const timer = fabricTimers.get(key)
    if (timer) clearTimeout(timer)
    fabricTimers.set(key, setTimeout(() => {
      fabricTimers.delete(key)
      fabricPending.delete(key)
      onFabric(gi, si, fi, v)
    }, RATE_DEBOUNCE_MS))
  }

  /** 立即提交某行挂起的率值（失焦 / Enter）；无挂起值时是空操作。 */
  function flushFabricLossRate(gi: number, si: number, fi: number) {
    const key = `${gi}-${si}-${fi}`
    const timer = fabricTimers.get(key)
    if (timer) { clearTimeout(timer); fabricTimers.delete(key) }
    if (!fabricPending.has(key)) return
    const v = fabricPending.get(key)!
    fabricPending.delete(key)
    onFabric(gi, si, fi, v)
  }

  /** 提交全部挂起的损耗率（统一率 + 各布料行）。返回按钮在 emit close 前调用。 */
  function flushAllPendingRateEdits() {
    flushLossRate()
    const keys = [...fabricPending.keys()]
    keys.forEach((key) => {
      const parts = key.split('-').map(Number)
      if (parts.length < 3 || parts.some((n) => !Number.isFinite(n))) return
      flushFabricLossRate(parts[0]!, parts[1]!, parts[2]!)
    })
  }

  /** 作废全部挂起值与定时器（flush 之后调用，防迟到回调二次提交）。 */
  function cancelPendingRateEdits() {
    if (unifiedTimer) { clearTimeout(unifiedTimer); unifiedTimer = null }
    unifiedPending = null
    fabricTimers.forEach((timer) => clearTimeout(timer))
    fabricTimers.clear()
    fabricPending.clear()
  }

  return {
    applyLossRateDebounced,
    applyFabricLossRateDebounced,
    flushLossRate,
    flushFabricLossRate,
    flushAllPendingRateEdits,
    cancelPendingRateEdits,
  }
}

import { watch, type Ref, type ComputedRef } from 'vue'
import { todayIso } from '../components/dayStatus'
import type { Row } from '../components/types'

export function useDefaultTodaySelection(opts: {
  y: Ref<number>; m: Ref<number>; factory: Ref<string>
  rows: ComputedRef<Row[]>; sel: Ref<string>
}) {
  const { y, m, factory, rows, sel } = opts
  let armed = true      // 用户手动改选后解除；换月/换工厂重新武装
  let lastAuto = ''     // 记录「自动写入」的值，用于区分用户操作

  function apply() {
    if (!armed) return
    const iso = todayIso()
    const [yy, mm] = iso.split('-').map(Number)
    const inMonth = yy === y.value && mm === m.value
    const next = inMonth && rows.value.some(r => r.date === iso) ? iso : ''
    if (next !== sel.value) { lastAuto = next; sel.value = next }
  }

  watch(rows, apply, { immediate: true })
  watch([y, m, factory], () => { armed = true; apply() })
  watch(sel, (v) => { if (v !== lastAuto) armed = false }, { flush: 'sync' })
}

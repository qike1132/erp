// 来料进度 / 历史查询的数据加载、SWR 缓存与后台刷新逻辑（从 MaterialView.vue 抽出，行为不变）
import { ref, computed, onUnmounted } from 'vue'
import { materialApi } from '@/api'
import type { Registration, RegItem } from '@/api/material'
import { readMaterialCache, writeMaterialCache } from '@/composables/useMaterialCache'

// 同一供应商 + 同一物料型号合并后的明细行
export interface MergedItem extends RegItem {
  ordered_quantity: number
  received_quantity: number
  progress: number
}

// 按供应商分组的物料行
export interface SupplierGroupRow {
  supplierName: string
  items: MergedItem[]
}

// 来料进度表格渲染行
export interface ProgressOrderRow extends Registration {
  order_no: string
  items: RegItem[]
  groupedItems: SupplierGroupRow[]
}

export function useMaterialRegistrations() {
  // --- Toast（页面内轻提示） ---
  const toastMsg = ref('')
  const toastType = ref('info')
  const toastIcon = computed(() => ({ success: 'fa-check-circle', error: 'fa-exclamation-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle' }[toastType.value] || 'fa-info-circle'))
  let toastTimer: ReturnType<typeof setTimeout> | null = null
  function toast(msg: string, type = 'info') {
    toastMsg.value = msg; toastType.value = type
    if (toastTimer) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => { toastMsg.value = '' }, 3000)
  }

  // --- 来料进度状态 ---
  const pPage = ref(1), pPerPage = ref(20), pPages = ref(1), pIsLoading = ref(false), pIsFetching = ref(false)
  const progressRows = ref<Registration[]>([])
  const pTotal = ref(0)
  /** 待处理订单数（用于 tab 徽章，取后端 total 而非当前页行数） */
  const progressCount = computed(() => pTotal.value)

  /**
   * 模板渲染行：对每个登记按当前分类筛选客户端展示的 items。
   * 服务端已通过 material_category 筛选掉不含该分类物料的登记，
   * 但一个登记可能同时含多分类物料，这里只展示所选分类的明细行。
   *
   * groupedItems: 按物料供应商分组，便于前端按供应商分别展示物料进度。
   */
  const progressOrderRows = computed<ProgressOrderRow[]>(() =>
    progressRows.value.map(r => {
      // 只展示面料类(fabric)和辅料类(accessory)，填充类(filling)不显示
      const items = (r.items || []).filter(i => i.material_category !== 'filling')
      // 按 supplier_name 分组，保持供应商出现顺序
      const groupMap = new Map<string, typeof items>()
      for (const i of items) {
        const key = (i as { supplier_name?: string }).supplier_name || '未指定'
        if (!groupMap.has(key)) groupMap.set(key, [])
        groupMap.get(key)!.push(i)
      }
      // 同一供应商 + 同一物料型号(material_name)汇总显示：合并数量、按总进度计算
      const mergedGroupedItems = Array.from(groupMap, ([supplierName, items]) => {
        const mergedMap = new Map<string, MergedItem>()
        for (const i of items) {
          const key = i.material_name
          const ordered = parseFloat(String(i.ordered_quantity || 0))
          const received = parseFloat(String(i.received_quantity || 0))
          const existing = mergedMap.get(key)
          if (existing) {
            existing.ordered_quantity += ordered
            existing.received_quantity += received
            existing.progress = existing.ordered_quantity > 0
              ? Math.round((existing.received_quantity / existing.ordered_quantity) * 100)
              : 0
          } else {
            const progress = ordered > 0 ? Math.round((received / ordered) * 100) : 0
            mergedMap.set(key, { ...i, ordered_quantity: ordered, received_quantity: received, progress })
          }
        }
        return { supplierName, items: Array.from(mergedMap.values()) }
      })
      return {
        ...r,
        order_no: r.purchase_order_no,
        items,
        groupedItems: mergedGroupedItems,
      }
    })
  )

  // --- 历史查询状态 ---
  const hPage = ref(1), hPerPage = ref(20), hPages = ref(1), hIsLoading = ref(false), hIsFetching = ref(false)
  const hRegistrations = ref<Registration[]>([])

  /** 后台静默刷新调度器：延迟 200ms 避免阻塞首屏渲染 */
  let _bgRefreshTimer: ReturnType<typeof setTimeout> | null = null
  function scheduleBackgroundRefresh(fn: () => Promise<void>) {
    if (_bgRefreshTimer) clearTimeout(_bgRefreshTimer)
    _bgRefreshTimer = setTimeout(() => {
      fn().catch(() => { /* 静默刷新失败不影响已渲染内容 */ })
    }, 200)
  }

  /** 加载历史查询数据（服务端分页 + SWR 缓存） */
  async function loadHistory(page = 1) {
    hPage.value = page
    const params: Record<string, string | number> = { page, per_page: hPerPage.value }

    // SWR: 先尝试从缓存渲染
    const { cached, fresh } = readMaterialCache('history', params)
    if (cached) {
      hRegistrations.value = cached.registrations || []
      hPages.value = cached.pages ?? 1
      if (fresh) {
        // 缓存未过期，直接返回，异步静默刷新
        scheduleBackgroundRefresh(() => loadHistoryFromApi(params))
        return
      }
      // 缓存已过期，先渲染旧数据，同时显示轻量进度条
      hIsFetching.value = true
    } else {
      hIsLoading.value = true
    }

    await loadHistoryFromApi(params)
  }

  /** 实际 API 调用（供首次加载和后台刷新复用） */
  async function loadHistoryFromApi(params: Record<string, string | number>) {
    try {
      const data = await materialApi.history(params)
      hRegistrations.value = data.registrations || []
      hPages.value = data.pages ?? data.total_pages ?? 1
      // 成功时写入缓存
      writeMaterialCache('history', params, {
        registrations: data.registrations || [],
        pages: data.pages ?? data.total_pages ?? 1,
        total: data.total ?? 0,
      })
    } catch { toast('加载失败', 'error') } finally { hIsLoading.value = false; hIsFetching.value = false }
  }

  /** 加载来料进度数据（服务端分页 + SWR 缓存） */
  async function loadProgress(page = 1) {
    pPage.value = page
    const params: Record<string, string | number | boolean> = { page, per_page: pPerPage.value, exclude_completed: true }

    // SWR: 先尝试从缓存渲染
    const { cached, fresh } = readMaterialCache('progress', params)
    if (cached) {
      progressRows.value = cached.registrations || []
      pPages.value = cached.pages ?? 1
      pTotal.value = cached.total ?? 0
      if (fresh) {
        // 缓存未过期，直接返回，异步静默刷新
        scheduleBackgroundRefresh(() => loadProgressFromApi(params))
        return
      }
      // 缓存已过期，先渲染旧数据，同时显示轻量进度条
      pIsFetching.value = true
    } else {
      pIsLoading.value = true
    }

    await loadProgressFromApi(params)
  }

  /** 实际 API 调用（供首次加载和后台刷新复用） */
  async function loadProgressFromApi(params: Record<string, string | number | boolean>) {
    try {
      const data = await materialApi.registrations(params)
      progressRows.value = data.registrations || []
      pPages.value = data.pages ?? data.total_pages ?? 1
      pTotal.value = data.total ?? 0
      // 成功时写入缓存
      writeMaterialCache('progress', params, {
        registrations: data.registrations || [],
        pages: data.pages ?? data.total_pages ?? 1,
        total: data.total ?? 0,
      })
    } catch { toast('加载失败', 'error') } finally { pIsLoading.value = false; pIsFetching.value = false }
  }

  /** 切到来料进度：无数据时先尝试缓存即时渲染，否则加载 */
  function ensureProgressLoaded() {
    if (!progressRows.value.length && !pIsLoading.value) {
      // 尝试从缓存恢复，实现即时渲染
      const params: Record<string, string | number | boolean> = { page: 1, per_page: 20, exclude_completed: true }
      const { cached } = readMaterialCache('progress', params)
      if (cached) {
        progressRows.value = cached.registrations || []
        pPages.value = cached.pages ?? 1
        pTotal.value = cached.total ?? 0
        // 后台静默刷新
        scheduleBackgroundRefresh(() => loadProgressFromApi({ ...params }))
      } else {
        loadProgress(1)
      }
    }
  }

  /** 切到历史查询：无数据时先尝试缓存即时渲染，否则加载 */
  function ensureHistoryLoaded() {
    if (!hRegistrations.value.length && !hIsLoading.value) {
      const params: Record<string, string | number> = { page: 1, per_page: 20 }
      const { cached } = readMaterialCache('history', params)
      if (cached) {
        hRegistrations.value = cached.registrations || []
        hPages.value = cached.pages ?? 1
        scheduleBackgroundRefresh(() => loadHistoryFromApi({ ...params }))
      } else {
        loadHistory(1)
      }
    }
  }

  /** UiDataTable 分页变化处理（PrimeVue page 为 0 索引） */
  function onProgressPageChange(event: { page: number; rows: number }) {
    pPerPage.value = event.rows
    loadProgress(event.page + 1)
  }
  function onHistoryPageChange(event: { page: number; rows: number }) {
    hPerPage.value = event.rows
    loadHistory(event.page + 1)
  }

  onUnmounted(() => {
    if (toastTimer) clearTimeout(toastTimer)
    if (_bgRefreshTimer) clearTimeout(_bgRefreshTimer)
  })

  return {
    toastMsg, toastType, toastIcon, toast,
    pPage, pPerPage, pPages, pIsLoading, pIsFetching, progressRows, progressCount, progressOrderRows,
    hPage, hPerPage, hPages, hIsLoading, hIsFetching, hRegistrations,
    loadProgress, loadHistory, ensureProgressLoaded, ensureHistoryLoaded,
    onProgressPageChange, onHistoryPageChange,
  }
}

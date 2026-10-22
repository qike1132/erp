import { computed, watch } from 'vue'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/vue-query'
import { outsourceApi } from '@/api'
import type { OutsourceProcessType } from '@/api/outsource'
import { toast } from '@/composables/useToast'

/** 列表端点单页上限（后端 per_page 上限 500）——与 useOrderImport 同口径 */
const PRESET_PAGE_SIZE = 500
/** 分页护栏：最多 20 页（= 10000 条预设），防异常响应（恒满页）导致死循环 */
const PRESET_MAX_PAGES = 20
/** queryKey 常量：测试预置缓存（setQueryData）与本 hook 共用，防字面量漂移 */
export const OUTSOURCE_PRESET_TYPES_KEY = ['outsource-process-types'] as const
/** 护栏截断上限（OCR-R12-L-b）：composable toast 与组件横幅共享同一来源，防任一常量
 * 改动后文案与真实 cap 静默脱钩（banner 曾硬编码 10000 漂移于 PRESET_MAX_PAGES*PAGE_SIZE） */
export const OUTSOURCE_PRESET_MAX_TOTAL = PRESET_MAX_PAGES * PRESET_PAGE_SIZE

/** 取数完整性（OCR-R7-M5）：部分失败/护栏截断须让组件可感知（queryFn 内 toast 会随 always 挂载重复弹）。
 * kept-guard（R18-#7）：page-N 失败保留的缓存本身是 guard——截断标志保留，但本次失败
 * 信号与重试入口不得被透传 guard 吞掉（旧实现 isError=false + retryable=false 静默） */
export type PresetPartialKind = 'none' | 'page-failed' | 'kept-stale' | 'guard' | 'kept-guard'

/** partial 元数据单一真相源（R16-#2）：rowsUnknown=「行确实可能缺失」（组件 unknownConfig
 * 行级判据）；banner=纯 partial 态横幅文案（isError 组合/在途分支除外）；toast=部分结果
 * 一次性提示（null=不弹）；retryable（R17-#2）=纯 partial 态是否值得渲染重试按钮——guard
 * 截断确定性（重取必再截断且重跑 20 页全扫）为死路 → false，其余 true（组件判据
 * isError || retryable !== false：isError 组合态网络可能恢复，按钮保留）。Record
 * <PresetPartialKind,…> 穷尽性：新增/改名 kind → 编译错误，而非运行时静默降级为无横幅/
 * 无提示（此前三处白名单各自硬编码字符串，曾两度漂移）。R18-#7 新增 kept-guard 即
 * 被穷尽性强制配齐全部字段——设计意图首次实证。errorSuffix（R21-M1）= isError
 * 组合横幅后缀——组件 bannerText isError 分支查表（单一真相源），与 banner/toast
 * 同源，防组件内联派生静默漂移 */
export const PARTIAL_META: Record<PresetPartialKind, { rowsUnknown: boolean; retryable: boolean; banner: string; toast: string | null; errorSuffix: string }> = {
  none: { rowsUnknown: false, retryable: true, banner: '', toast: null, errorSuffix: '' },
  'page-failed': { rowsUnknown: true, retryable: true, banner: '工序预设列表加载不完整，部分产品的配置状态未知', toast: '工序预设列表加载不完整，请刷新重试', errorSuffix: '，部分产品配置状态未知' },
  'kept-stale': { rowsUnknown: false, retryable: true, banner: '工序预设列表可能不是最新（网络异常，已保留上次数据）', toast: '工序预设列表加载不完整，已保留上次已加载的数据', errorSuffix: '' },
  guard: { rowsUnknown: true, retryable: false, banner: `工序预设超过 ${OUTSOURCE_PRESET_MAX_TOTAL} 条，列表已截断，未显示的产品配置状态未知`, toast: `工序预设超过 ${OUTSOURCE_PRESET_MAX_TOTAL} 条，列表仅显示前 ${OUTSOURCE_PRESET_MAX_TOTAL} 条`, errorSuffix: `，且超过 ${OUTSOURCE_PRESET_MAX_TOTAL} 条仅显示前 ${OUTSOURCE_PRESET_MAX_TOTAL} 条` },
  'kept-guard': { rowsUnknown: true, retryable: true, banner: '网络异常，已保留截断的预设列表（上次超过上限部分未显示，状态未知）', toast: '工序预设列表刷新失败，已保留上次数据', errorSuffix: `，且超过 ${OUTSOURCE_PRESET_MAX_TOTAL} 条仅显示前 ${OUTSOURCE_PRESET_MAX_TOTAL} 条` },
}

/** R7 query 数据形态：items + 完整性标志。缓存/快照的历史形态（R5 裸数组、更早分页信封）由 presets computed 兼容 */
export interface PresetTypesData {
  items: OutsourceProcessType[]
  partial: PresetPartialKind
}

/** 同一 queryClient 内同一份部分结果只弹一次 toast（OCR-R7-M5：always 挂载重取不堆叠告警）。WeakMap 按实例隔离，测试各自新建 queryClient 天然互不串扰 */
const partialToastDedup = new WeakMap<QueryClient, string>()

/** stale-retention 跳过意图（token）挂 QueryClient 共享作用域（OCR-R13-L-b，与
 * partialToastDedup 同口径）：queryFn 挂在 query 上、归属由最后 setOptions 的 observer
 * 决定——实例闭包状态对非发起方路径（refetchQueries / 库语义变化）执行的 queryFn 不可
 * 见，A 的变更后刷新意图会丢（部分失败时回滚变更前旧缓存，R8-M1 复活）。R36-Ld 生命周期
 * 修订：意图分两期——【窗口期】grant 至发起方 finally 之间，queryFn 启动时刻只读快照、
 * 不取走（R21-M2 启动时刻快照语义保持：同窗口内并发 queryFn——piggyback 落败方/非发起
 * 方路径——共享同一意图，R13-Lb 锁定）；【handoff 期】发起方因离线被 race 抢先（refetch
 * 仍挂起、promise 挂起至恢复在线）时 token 迁移至 handoff 集合，由恢复后真正执行的
 * queryFn one-shot 消费（读后即取走一颗）——pause 不再释放意图（R24-L3 的提前释放使
 * mutation 权威恰在离线路径丢失：恢复后 queryFn 读不到意图 → stale-retention 回滚
 * pre-mutation 旧缓存，新增行消失）；one-shot 消费次数上限化解 R24-L3 担心的「skip
 * 波及后续/非变更取数」：恢复的 fetch 保留 mutation 权威而后续 fetch 不保留。Set 支持
 * 重叠刷新净持有（OCR-R9-L2 口径保持）：重叠的两次变更各登记一颗，先结束的一方不取走
 * 在途方的意图 */
const staleRetentionSkipGrants = new WeakMap<QueryClient, Set<symbol>>()
const staleRetentionSkipHandoffs = new WeakMap<QueryClient, Set<symbol>>()

/** queryFn 启动时刻读 skip 快照（R21-M2 + R36-Ld）：handoff 有一颗则 one-shot 消费（读后
 * 即取走）返回 true；否则窗口期集合非空即 true（只读不取——窗口内并发 queryFn 共享，
 * 撤销权在发起方 finally）；两者皆空返回 false。JS 单线程同步读删即原子 */
function readStaleRetentionSkipSnapshot(queryClient: QueryClient): boolean {
  const handoffs = staleRetentionSkipHandoffs.get(queryClient)
  if (handoffs) {
    for (const first of handoffs) { // noUncheckedIndexedAccess 下数组解构得 symbol|undefined，for...of 迭代器元素恒具体
      handoffs.delete(first)
      return true
    }
  }
  return (staleRetentionSkipGrants.get(queryClient)?.size ?? 0) > 0
}

/** 登记一颗窗口期 skip token（变更后刷新意图），返回 token 供 finally 定点处置 */
function grantStaleRetentionSkip(queryClient: QueryClient): symbol {
  const token = Symbol('stale-retention-skip')
  const grants = staleRetentionSkipGrants.get(queryClient) ?? new Set<symbol>()
  grants.add(token)
  staleRetentionSkipGrants.set(queryClient, grants)
  return token
}

/** 发起方 finally 处置：正常结算（refetch 已 settle）→ 撤销（token 未被任何路径取走，
 *  窗口语义下 queryFn 只读）；paused 抢先 → 移交 handoff（one-shot 等待恢复后的 queryFn
 *  消费，意图不得因 pause 丢失——R36-Ld） */
function settleStaleRetentionSkip(queryClient: QueryClient, token: symbol, survivedPause: boolean): void {
  staleRetentionSkipGrants.get(queryClient)?.delete(token)
  if (!survivedPause) return
  const handoffs = staleRetentionSkipHandoffs.get(queryClient) ?? new Set<symbol>()
  handoffs.add(token)
  staleRetentionSkipHandoffs.set(queryClient, handoffs)
}

/** 快照形态规范化单一真相源（R18-#6）：R7 信封 {items,partial} / R5 裸数组 / 旧分页信封
 *  三种形态只在此处解析。裸数组无完整性标志 → partial='page-failed'（R17-#3 保守语义）；
 *  信封读 .partial（缺失保守 'page-failed'（R34-#8 fail-closed：'none' 属 fail-open，完整性未知被当完整——行级「未配置」误导重复添加），意外值直通 cast——白名单口径在 PARTIAL_META 查表侧，
 *  R13-L-c/M-c）；hasData=「形态本身构成已知」：数组或含 items 数组（items:[] 是真空白
 *  租户的已知事实），undefined 与旧信封 {success,data,total} 不构成已知（R12-M-a）。
 *  此前五处消费方（presets/partial/hasData/cachedSnapshot/watch）各自解析，watch 已
 *  分叉（裸数组被忽略而非 page-failed，R18-#2）——同一快照 banner 有 toast 无 */
function normalizeSnapshot(data: unknown): { items: OutsourceProcessType[]; partial: PresetPartialKind; hasData: boolean } {
  if (Array.isArray(data)) return { items: data, partial: 'page-failed', hasData: true }
  const d = data as PresetTypesData | undefined
  if (Array.isArray(d?.items)) return { items: d.items, partial: d.partial ?? 'page-failed', hasData: true }
  return { items: [], partial: 'none', hasData: false }
}

/** 读旧缓存快照（三形态兼容：R7 对象 / R5 裸数组 / 更早信封→空；解析走 normalizeSnapshot
 *  单一真相源 R18-#6）。partial 供 stale-retention 透传（OCR-R13-M）：guard/page-failed/
 *  kept-guard 缓存被保留时，其「行确实可能缺失」标志不得降级。返回恒为具体
 *  PresetPartialKind（OCR-R21-L2）：normalizeSnapshot 三分支均落具体 kind，undefined
 *  只出现在调用点（fetchAllProcessTypes skip 分支合成对象），联合在调用点推断 */
function cachedSnapshot(queryClient: QueryClient): { items: OutsourceProcessType[]; partial: PresetPartialKind } {
  // R18-#6：解析走 normalizeSnapshot。行为差异论证：信封缺 partial 由 undefined 变 'none'
  // ——keptKind 判断只认 guard/page-failed/kept-guard（其余 → kept-stale），'none' 与
  // undefined 同落 kept-stale，无漂移；裸数组 → 'page-failed' 与 R17-#3 同口径
  const n = normalizeSnapshot(queryClient.getQueryData(OUTSOURCE_PRESET_TYPES_KEY))
  return { items: n.items, partial: n.partial }
}

/**
 * 分页拉全部工序预设（2026-10-19 审计 P1-23 + OCR-R7-M5）。
 * 逐页取满页即续拉、页不满即止、total 收口避免整数倍记录多拉空页、页数护栏兜底。
 * 首屏失败上抛（isError+重试，OCR-3 M4）；后续页失败保留已取数据，且旧缓存更
 * 完整时不用部分结果覆盖（否则 refetchOnMount always 下一次网络抖动就成批丢行）；
 * 本地变更（add/delete）发起的 refetch 例外——见 skipStaleRetention（OCR-R8-M1）。
 * 不在此弹 toast——通知与取数解耦（见 useOutsourcePresetTypes 内 watch）。
 */
async function fetchAllProcessTypes(queryClient: QueryClient, skipStaleRetention: () => boolean): Promise<PresetTypesData> {
  const all: OutsourceProcessType[] = []
  let truncatedByGuard = true
  for (let page = 1; page <= PRESET_MAX_PAGES; page += 1) {
    let items: OutsourceProcessType[] = []
    let total = 0
    try {
      const res = await outsourceApi.processTypes({ page, per_page: PRESET_PAGE_SIZE })
      items = res.data ?? []
      total = res.total ?? 0
    } catch (e) {
      if (page === 1) throw e // 首屏失败：交给上层 isError + 重试（OCR-3 M4）
      // OCR-R7-M5：部分失败时旧缓存更完整 → 保留旧数据（防「只有第 1 页」覆盖完整列表）。
      // OCR-R8-M1：本地变更（add/delete）发起的 refetch 跳过该保留——变更后的部分数据才是
      // 权威，旧缓存是变更前的世界，保留它=新增行消失/已删行复活
      // R29-L6：skip 场景无旧缓存可保留，prev 可空——不伪造 partial: undefined 越契约值（cachedSnapshot 恒返回具体 kind，见其 doc）
      const prev = skipStaleRetention() ? null : cachedSnapshot(queryClient)
      const prevItems = prev?.items ?? []

      const kept = prevItems.length > all.length ? prevItems : all
      console.warn(`工序预设第 ${page} 页拉取失败，已保留 ${kept.length} 条`) // OCR-R8-L1：报实际保留条数（kept-stale 时不得低估为本次已取数）
      // OCR-R13-M：保留旧缓存时透传其自身的 page-failed/kept-guard——旧缓存「行确实可能缺失」
      // 的标志不因保留动作降级为 kept-stale（「完整但过期」），行级收敛与横幅口径才不漂移。
      // R18-#7：guard 保留改传 'kept-guard'——透传 guard 会吞掉本次失败（isError=false +
      // retryable=false，无重试按钮）；kept-guard 透传自身（连续失败保留时 rowsUnknown 不降级）
      let keptKind: PresetPartialKind = 'kept-stale'
      if (prev?.partial === 'guard') keptKind = 'kept-guard'
      else if (prev?.partial === 'page-failed' || prev?.partial === 'kept-guard') keptKind = prev.partial
      // R38-L-k：意外 kind 保守 fail-closed（映射 page-failed，rowsUnknown=true）——
      // normalizeSnapshot 对持久化快照的 partial cast 直通（跨 build 写入的 kind 可达），
      // 且该链不受 Record<PresetPartialKind,…> 穷尽性保护；kept-stale 是「完整但过期」，
      // 未知 kind 不得假设完整（旧行为 fail-open：缺失行渲染「未配置」误导重复添加）。
      // String() 比较绕开 TS 收窄（联合类型下 else 分支被推断为不可达，运行时实际可越界）
      else if (prev && String(prev.partial) !== 'none' && String(prev.partial) !== 'kept-stale') keptKind = 'page-failed'
      return kept === prevItems
        ? { items: kept, partial: keptKind }
        : { items: kept, partial: 'page-failed' }
    }
    all.push(...items)
    if (items.length < PRESET_PAGE_SIZE || (total > 0 && all.length >= total)) {
      truncatedByGuard = false
      break
    }
  }
  if (truncatedByGuard) { console.warn(`工序预设达 ${OUTSOURCE_PRESET_MAX_TOTAL} 条护栏上限，超出部分未加载`); return { items: all, partial: 'guard' } }
  return { items: all, partial: 'none' }
}

/**
 * 工序预设取数 hook（OCR-R7-M5 自 OutsourcePresetTab 外移：组件贴 400 行门禁）。
 * refetchOnMount:'always'（OCR-R5 M168）：挂载必重取，信封快照不滞留空态；
 * partial 提示在组件侧 watch——同一 queryClient 内同一份部分结果只弹一次。
 */
export function useOutsourcePresetTypes() {
  const queryClient = useQueryClient()
  // 本地变更后的 refetch 跳过 stale-retention（OCR-R8-M1）：意图读写走模块级 WeakMap
  // 函数（OCR-R13-L-b + R36-Ld 双集合生命周期，见 staleRetentionSkipGrants 声明处注释）
  const { data: listData, isError, isFetching, isPaused, refetch } = useQuery({
    queryKey: OUTSOURCE_PRESET_TYPES_KEY,
    // OCR-R21-M2 + R36-Ld：skip 判定是「queryFn 启动时刻」的快照读——mutation 发起的
    // refetch 启动即读到（grant 在 refetch 前）；vue-query 同 key 并发触发复用在途
    // promise（piggyback）共享同一判定；offline 暂停恢复的 fetch 于 resume 时刻读，且
    // handoff token 读后即取走（one-shot：恢复的 fetch 保留 mutation 权威，此后再无
    // token）。在线路径行为不变（mutation 跳过/非 mutation 保留两主面由现有用例锁定）
    queryFn: () => {
      const skipNow = readStaleRetentionSkipSnapshot(queryClient)
      return fetchAllProcessTypes(queryClient, () => skipNow)
    },
    staleTime: 15_000,
    refetchOnMount: 'always', // OCR-R5 M168：fresh 快照 mount 默认不重取→信封快照 15s 内不自愈；always 保证挂载必重取（同 useOutsourceOrders 约定）
  })

  /** 旧缓存快照防御（OCR-4 H1）+ 三形态兼容：R7 {items,partial} / R5 裸数组 / 信封判空待重取
   *  替换。解析走 normalizeSnapshot 单一真相源（R18-#6） */
  const presets = computed<OutsourceProcessType[]>(() => normalizeSnapshot(listData.value).items)

  /** 取数完整性（OCR-R10-M-B + OCR-R11-M-E）：partial 供组件区分判据——page-failed/guard/
   *  kept-guard 属「行确实可能缺失」（未拉到的产品行「未配置」无据），kept-stale 旧数据完整
   *  可信不锁入口，由组件横幅给出常驻解释；hasData 供「已知空」判据用（L-f）。解析走
   *  normalizeSnapshot 单一真相源（R18-#6：R17-#3 裸数组保守化语义保持） */
  const partial = computed<PresetPartialKind>(() => normalizeSnapshot(listData.value).partial)

  /** 有任何成功数据（OCR-R11-L-f + OCR-R12-M-a shape 化）：与 normalizeSnapshot 同口径——
   * R7 {items} / R5 裸数组 为已知（items:[] 是真空白租户的已知事实）；undefined（从未成功/
   * 重试在途）与 P1-23 前旧分页 envelope {success,data,total}（presets 解析为 []，
   * persistQueryClient 未 bump buster 时可恢复）均不构成已知（R18-#6 走单一真相源） */
  const hasData = computed(() => normalizeSnapshot(listData.value).hasData)

  // OCR-R7-M5：通知与取数解耦——partial 时提示（queryFn 内 toast 会随 always 挂载重复堆叠）。
  // OCR-R8-M2：immediate——persistQueryClient 恢复的 partial 快照在 setup 时已是当前值，
  // 无 immediate 则 watch 对「当前值」永不触发；自愈重取若返回深度相等结果
  // （structuralSharing 同引用），toast 永不弹 → 用户静默看到不完整列表
  watch(listData, (d) => {
    // OCR-R11-L-e：局部命名 kind，勿遮蔽上面的 computed partial（回调内后续编辑易读到旧值）。
    // R18-#2/#6：形态解析走 normalizeSnapshot——R5 裸数组 → 'page-failed'（此前直读
    // .partial 得 undefined → early return，同一快照 banner 有 toast 无）
    const { items, partial: kind } = normalizeSnapshot(d)
    if (kind === 'none') { partialToastDedup.delete(queryClient); return } // R32-#5：删恒 false 的 !kind（normalizeSnapshot 三分支恒返回具体 kind，误导读者以为有 unknown 运行时值；意外值白名单已在 PARTIAL_META 查表侧）
    const key = `${kind}:${items.length}`
    if (partialToastDedup.get(queryClient) === key) return // 同一份部分结果不重复弹
    partialToastDedup.set(queryClient, key)
    const t = PARTIAL_META[kind]?.toast // R16-#2：查表（穷尽性由 Record 锁定）；运行时意外值（cast 直通）→ undefined 不提示（R13-M-c 白名单口径）
    if (t) toast.warning(t)
  }, { immediate: true })

  /** 本地变更（add/delete 成功）后的刷新（OCR-R8-M1）：变更后的数据即使 partial 也是权威，跳过 stale-retention */
  async function refetchAfterMutation() {
    // R36-Ld：登记一颗窗口期 token——由 queryFn 启动时刻读快照消费（在线）或 pause 抢先
    // 后移交 handoff、由恢复后的 queryFn one-shot 消费（离线），不再由 finally 无条件释放
    const skipToken = grantStaleRetentionSkip(queryClient)
    // OCR-R24-L3（race 结构保持）：offline（networkMode:'online' 默认）下 refetch() 的
    // promise 挂起至恢复在线（探针实证 query-core 5.100.10，logs/_fix_2026-10-18/
    // t78_probe.log）——await 卡住会让 saving 卡整个离线窗口，race isPaused 翻 true 即
    // 提前返回（刷新方不挂起）。flush:'sync' + immediate：isPaused 赋值瞬间即触发、调用
    // 时已离线（mutation 回包路上断网）也能命中；race 落败的 refetch promise 由 race
    // 内部消化，无 unhandled rejection
    let pausedWon = false
    let stopPauseWatch: (() => void) | undefined
    try {
      const pausedSignal = new Promise<void>((resolve) => {
        stopPauseWatch = watch(isPaused, (p) => { if (p) { pausedWon = true; resolve() } }, { flush: 'sync', immediate: true })
      })
      await Promise.race([refetch(), pausedSignal])
    } catch (e) {
      // OCR-R14-M-b（收窄 R11-M-F）：刷新失败 ≠ 变更失败——变更本身已成功，任何 rejection
      // （不只取消）上抛都会被 useApiMutation 的 run()/mutate() 捕获弹「添加/删除失败」
      // errorMsg，与已弹的成功 toast 矛盾；吞掉并留痕（console.warn），数据新鲜度由
      // 横幅（isError/partial 常驻解释）与后续重试兜底
      console.warn('工序预设变更后刷新失败（变更本身已成功，不构成变更失败）', e)
    } finally {
      stopPauseWatch?.()
      // R36-Ld 处置：正常结算（在线完成/失败/竞态落败）→ 撤销未被消费的窗口 token（在线
      // 语义下 queryFn 只读不取，须由发起方收口，防 piggyback 未消费时泄漏到后续取数）；
      // paused 抢先 → 移交 handoff，意图由恢复后 resume 的 queryFn one-shot 消费（pause
      // 不得释放意图——释放即丢失 R8-M1 的 mutation 权威，R36-Ld 根因）
      settleStaleRetentionSkip(queryClient, skipToken, pausedWon)
    }
  }

  /** 用户手动重试（横幅/空态按钮共用入口，R16-#1）：refetch 失败留痕不上抛（与
   * refetchAfterMutation 同口径，OCR-R14-M-b）——替代模板两处内联的空 catch */
  async function manualRetry() {
    try { await refetch() } catch (e) { console.warn('工序预设手动重试失败', e) }
  }

  // R17-#4：不暴露 raw refetch——它绕过 stale-retention skip 与 swallow-and-log 两个契约
  // （manualRetry / refetchAfterMutation 内部闭包仍持有 refetch，不受影响）；
  // isPaused 供组件 paused/offline 判据（R18-#4：离线首进 bannerText/按钮 gate）
  return { presets, partial, hasData, isError, isFetching, isPaused, refetchAfterMutation, manualRetry }
}
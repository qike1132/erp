import { computed, nextTick, ref, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/types/errors'
import type {
  OneClickGenerateRequest, OneClickGenerateResponse, PurchaseOrder, UnprocessedOrder,
} from '@/types'
import {
  consumeResumeAttempt, createResumeAttempt, firstMissingProduct, missingProducts,
  parseResumeSource, readResumeAttempt, writeResumeAttempt,
  type BomResumeAttemptV1, type PurchaseViewSnapshot, type ResumePhase, type ResumeProduct,
} from '@/utils/bomOrderResume'

interface RouterLocation {
  path: string
  query: Record<string, string>
}

interface ResumeRouteLike { query: Record<string, unknown> }
interface ResumeRouterLike {
  push: (location: RouterLocation) => Promise<unknown>
  replace: (location: RouterLocation) => Promise<unknown>
}
interface ResumeAuthLike {
  user: { id: number } | null
  hasPermission: (code: string) => boolean
}
interface UnprocessedState {
  orders: UnprocessedOrder[]
  currentPage: number
  totalPages: number
  refresh: () => Promise<unknown>
}
interface PurchaseOrderState {
  orders: PurchaseOrder[]
  page: number
  pages?: number
  selectedIds: number[]
  refresh: () => Promise<unknown>
}
type Generate = (
  data: OneClickGenerateRequest,
  options: { headers: Record<string, string> },
) => Promise<OneClickGenerateResponse>

export interface BomOrderResumeOptions {
  activeTab: Ref<'active' | 'history'>
  unprocessed: UnprocessedState
  purchaseOrders: PurchaseOrderState
  route?: ResumeRouteLike
  router?: ResumeRouterLike
  auth?: ResumeAuthLike
  generate?: Generate
  /** 采购页内直接打开 BOM 弹窗；未注入时保留旧路由跳转（兼容产品页测试/旧入口）。 */
  openBomEditor?: (product: ResumeProduct) => Promise<void> | void
}

function singleQueryValue(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null
}

function errorStatus(error: unknown): number | null {
  const status = (error as { response?: { status?: unknown } } | null)?.response?.status
  return typeof status === 'number' ? status : null
}

function resumeErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | null)?.response?.data?.detail
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message
    if (typeof message === 'string' && message) return message
  }
  return getErrorMessage(error, fallback)
}

function trustedSuccess(response: OneClickGenerateResponse): boolean {
  if (!response.success || response.code !== 'OK' || !Array.isArray(response.orders)) return false
  if (response.orders.length === 0 || typeof response.created_count !== 'number') return false
  if (response.idempotent) return response.created_count === 0
  return response.created_count > 0
}

export function useBomOrderResume(options: BomOrderResumeOptions) {
  const route = options.route ?? useRoute()
  const router = options.router ?? useRouter()
  const auth = options.auth ?? useAuthStore()
  const generate = options.generate ?? ((data, config) => purchaseApi.oneClickGenerate(data, config))
  const phase = ref<ResumePhase | 'IDLE'>('IDLE')
  const message = ref('')
  const pendingProducts = ref<ResumeProduct[]>([])
  const resumeInFlight = ref(false)
  const activeAttempt = ref<BomResumeAttemptV1 | null>(null)
  const canManageBom = computed(() => auth.hasPermission('product_manage'))
  const resumeSourceId = computed(() => activeAttempt.value?.source.composite_id ?? '')
  let navigationInFlight = false
  let initialization: Promise<void> | null = null

  function persist(attempt: BomResumeAttemptV1, nextPhase?: ResumePhase): void {
    if (nextPhase) attempt.phase = nextPhase
    attempt.updated_at = Date.now()
    writeResumeAttempt(attempt)
    activeAttempt.value = attempt
    phase.value = attempt.phase
  }

  function captureView(): PurchaseViewSnapshot {
    const main = document.querySelector('.main-content')
    const table = document.querySelector('.pc-table-wrap')
    return {
      active_tab: options.activeTab.value,
      purchase_page: Math.max(1, options.purchaseOrders.page),
      unprocessed_page: Math.max(1, options.unprocessed.currentPage),
      selected_ids: [...options.purchaseOrders.selectedIds],
      main_scroll_top: main?.scrollTop ?? 0,
      table_scroll_left: table?.scrollLeft ?? 0,
    }
  }

  async function startConfiguration(row: UnprocessedOrder): Promise<void> {
    if (navigationInFlight) return
    navigationInFlight = true
    try {
      const ownerId = auth.user?.id
      if (!ownerId || !auth.hasPermission('product_manage')) {
        showToast('缺 BOM，请联系产品管理员配置后再下单', 'warning')
        return
      }
      const source = parseResumeSource(row)
      if (!source) {
        showToast('来源或缺 BOM 产品信息已变化，请刷新后重试', 'warning')
        return
      }
      const rowMissing = missingProducts(row)
      const reusable = activeAttempt.value
        && activeAttempt.value.source.composite_id === source.composite_id
        && ['CONFIGURING', 'RETURNING', 'WAITING_NEXT_BOM', 'RESUME_FAILED'].includes(
          activeAttempt.value.phase,
        )
        ? activeAttempt.value : null
      // 返回采购页的列表可能仍是 BOM 保存前的 30s 快照；此时必须以上一轮
      // 服务端 MISSING_BOM/onSaved 已维护的 pending_products 为准，不能从旧
      // items 重新取 firstMissingProduct，否则会反复打开刚配置完的第一个 SKU。
      const nextPending = reusable?.pending_products?.length
        ? reusable.pending_products : rowMissing
      const product = nextPending[0] ?? firstMissingProduct(row)
      if (!product || row.has_bom !== false) {
        showToast('来源或缺 BOM 产品信息已变化，请刷新后重试', 'warning')
        return
      }
      const attempt = reusable ?? createResumeAttempt({
        owner_id: ownerId,
        source,
        pending_products: nextPending,
        current_product_id: product.product_id,
        view: captureView(),
      })
      attempt.current_product_id = product.product_id
      attempt.pending_products = nextPending
      persist(attempt, 'CONFIGURING')
      if (options.openBomEditor) {
        await options.openBomEditor(product)
        return
      }
      await router.push({
        path: '/product',
        query: { product_id: String(product.product_id), resume_attempt_id: attempt.attempt_id },
      })
    } catch (error) {
      showToast(getErrorMessage(error, '无法进入 BOM 配置'), 'error')
    } finally {
      navigationInFlight = false
    }
  }

  function applyView(attempt: BomResumeAttemptV1): void {
    options.activeTab.value = attempt.view.active_tab
    options.purchaseOrders.page = Math.max(1, attempt.view.purchase_page)
    options.unprocessed.currentPage = Math.max(1, attempt.view.unprocessed_page)
  }

  async function refreshLists(): Promise<void> {
    await nextTick()
    await Promise.all([options.unprocessed.refresh(), options.purchaseOrders.refresh()])
    const purchasePage = Math.min(
      options.purchaseOrders.page, Math.max(1, options.purchaseOrders.pages ?? options.purchaseOrders.page),
    )
    const unprocessedPage = Math.min(
      options.unprocessed.currentPage, Math.max(1, options.unprocessed.totalPages),
    )
    if (purchasePage === options.purchaseOrders.page && unprocessedPage === options.unprocessed.currentPage) return
    options.purchaseOrders.page = purchasePage
    options.unprocessed.currentPage = unprocessedPage
    await nextTick()
    await Promise.all([options.unprocessed.refresh(), options.purchaseOrders.refresh()])
  }

  async function restoreAndRefresh(attempt: BomResumeAttemptV1): Promise<void> {
    applyView(attempt)
    await refreshLists()
    const validIds = new Set(options.purchaseOrders.orders.map((order) => order.id))
    options.purchaseOrders.selectedIds = attempt.view.selected_ids.filter((id) => validIds.has(id))
    await nextTick()
    const main = document.querySelector('.main-content')
    const table = document.querySelector('.pc-table-wrap')
    if (main) main.scrollTop = attempt.view.main_scroll_top
    if (table) table.scrollLeft = attempt.view.table_scroll_left
  }

  async function clearResumeQuery(): Promise<void> {
    if (!('resume' in route.query)) return
    const query = Object.fromEntries(
      Object.entries(route.query)
        .filter(([key]) => key !== 'resume')
        .map(([key, value]) => [key, String(value)]),
    )
    await router.replace({ path: '/purchase', query })
  }

  async function finish(attempt: BomResumeAttemptV1, nextPhase: ResumePhase, text: string): Promise<void> {
    consumeResumeAttempt(attempt.attempt_id)
    activeAttempt.value = null
    phase.value = nextPhase
    message.value = text
    await clearResumeQuery()
  }

  function updateMissing(attempt: BomResumeAttemptV1, products: ResumeProduct[]): void {
    attempt.pending_products = products
    pendingProducts.value = products
    persist(attempt, 'WAITING_NEXT_BOM')
    message.value = `还需配置 ${products.length} 个 SKU：${products.map((item) => item.product_name).join('、')}`
  }

  async function runGeneration(attempt: BomResumeAttemptV1): Promise<void> {
    persist(attempt, 'RESUMING')
    try {
      const response = await generate(
        { composite_ids: [attempt.source.composite_id] },
        { headers: { 'X-Idempotency-Key': attempt.idempotency_key } },
      )
      if (response.code === 'MISSING_BOM') {
        updateMissing(attempt, response.missing_bom)
        return
      }
      if (response.code === 'SOURCE_INVALID') {
        await finish(attempt, 'ABORTED', response.message || '来源记录已失效')
        return
      }
      if (!trustedSuccess(response)) throw new Error('续提响应缺少可信采购单结果')
      await Promise.allSettled([options.unprocessed.refresh(), options.purchaseOrders.refresh()])
      const orderNos = response.orders.map((order) => order.order_no).join('、')
      const text = response.idempotent
        ? `采购单已生成，无需重复下单：${orderNos}` : `采购单生成成功：${orderNos}`
      showToast(text, 'success')
      await finish(attempt, 'DONE', text)
    } catch (error) {
      const status = errorStatus(error)
      if (status === 403 || status === 409) {
        await finish(attempt, 'ABORTED', resumeErrorMessage(error, '续提被服务器拒绝'))
        return
      }
      attempt.last_error = resumeErrorMessage(error, '续提失败，请手动重试')
      persist(attempt, 'RESUME_FAILED')
      message.value = attempt.last_error
    }
  }

  async function resumeActiveAttempt(attempt: BomResumeAttemptV1): Promise<void> {
    resumeInFlight.value = true
    message.value = '正在校验并继续下单'
    try {
      await refreshLists()
      await runGeneration(attempt)
    } catch (error: unknown) {
      attempt.last_error = resumeErrorMessage(error, '刷新校验失败，请重试')
      persist(attempt, 'RESUME_FAILED')
      message.value = attempt.last_error
    } finally {
      resumeInFlight.value = false
    }
  }

  /**
   * 同页 BOM 弹窗保存成功：不再跳 /product，直接刷新采购列表并走同一权威续提。
   * ProductList 的路由回程仍保留给旧入口，不经过这里。
   */
  async function completeConfiguration(productId: number): Promise<void> {
    const attempt = activeAttempt.value
    if (!attempt || attempt.phase !== 'CONFIGURING' || attempt.current_product_id !== productId) return
    attempt.phase = 'RETURNING'
    attempt.pending_products = attempt.pending_products.filter(
      (item) => item.product_id !== productId,
    )
    attempt.updated_at = Date.now()
    writeResumeAttempt(attempt)
    phase.value = attempt.phase
    pendingProducts.value = attempt.pending_products
    await resumeActiveAttempt(attempt)
  }

  /** 同页弹窗取消：只结束本次尝试，不写采购单、不离开采购页。 */
  function cancelConfiguration(): void {
    const attempt = activeAttempt.value
    if (!attempt || attempt.phase !== 'CONFIGURING') return
    consumeResumeAttempt(attempt.attempt_id)
    activeAttempt.value = null
    pendingProducts.value = []
    phase.value = 'CANCELLED'
    message.value = '已取消 BOM 配置，未发起下单'
  }

  async function initialize(attemptId: string, ownerId: number): Promise<void> {    const attempt = readResumeAttempt(attemptId, ownerId)
    if (!attempt) {
      phase.value = 'IDLE'
      message.value = '续提上下文不存在、已过期或已消费'
      await clearResumeQuery()
      return
    }
    activeAttempt.value = attempt
    pendingProducts.value = attempt.pending_products
    if (['DONE', 'ABORTED'].includes(attempt.phase)) {
      await finish(attempt, attempt.phase, attempt.last_error || '本次续提已结束')
      return
    }
    if (attempt.phase === 'CANCELLED') {
      await restoreAndRefresh(attempt)
      await finish(attempt, 'CANCELLED', '已取消 BOM 配置，未发起下单')
      return
    }
    persist(attempt, 'RESTORING_REVALIDATING')
    message.value = '正在校验并继续下单'
    await restoreAndRefresh(attempt)
    // 不在这里根据 unprocessed 快照提前返回：该列表有 30s 缓存，BOM 刚保存
    // 时可能仍显示旧 has_bom。生成端点会返回权威的 missing_bom 列表（且缺 BOM
    // 时 0 写入），以它作为下一份 BOM 的选择依据。
    await runGeneration(attempt)
  }

  async function initializeFromRoute(): Promise<void> {
    if (initialization) return initialization
    const attemptId = singleQueryValue(route.query.resume)
    const ownerId = auth.user?.id
    if (!attemptId || !ownerId) return
    resumeInFlight.value = true
    initialization = initialize(attemptId, ownerId)
      .catch(async (error: unknown) => {
        const attempt = activeAttempt.value
        if (attempt) {
          attempt.last_error = getErrorMessage(error, '刷新校验失败，请手动重试')
          persist(attempt, 'RESUME_FAILED')
          message.value = attempt.last_error
        }
      })
      .finally(() => {
        resumeInFlight.value = false
        initialization = null
      })
    return initialization
  }

  async function retryResume(): Promise<void> {
    const attempt = activeAttempt.value
    // 同页弹窗流程没有 ?resume= 查询参数；不能只依赖 initializeFromRoute，
    // 否则保存后网络失败的重试按钮无效。
    if (attempt && !('resume' in route.query)) {
      await resumeActiveAttempt(attempt)
      return
    }
    await initializeFromRoute()
  }

  return {
    phase, message, pendingProducts, resumeInFlight, activeAttempt,
    canManageBom, resumeSourceId,
    startConfiguration, completeConfiguration, cancelConfiguration,
    initializeFromRoute, retryResume,
  }
}

import { ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/types/errors'
import type { Product } from '@/types'
import {
  readResumeAttempt, writeResumeAttempt, type BomResumeAttemptV1,
} from '@/utils/bomOrderResume'

interface BomEditorRefLike {
  open: (product: { id: number; name: string }) => Promise<void> | void
}
interface ResumeRouteLike { query: Record<string, unknown> }
interface ResumeRouterLike {
  replace: (location: { path: string; query?: Record<string, string> }) => Promise<unknown>
}
interface ResumeAuthLike {
  user: { id: number } | null
  hasPermission: (code: string) => boolean
}

export interface ProductBomResumeOptions {
  route?: ResumeRouteLike
  router?: ResumeRouterLike
  auth?: ResumeAuthLike
  detail?: (productId: number) => Promise<Product>
}

function positiveRouteId(value: unknown): number | null {
  if (typeof value !== 'string' || !/^\d+$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

export function useProductBomResume(
  bomEditorRef: Ref<BomEditorRefLike | null>,
  options: ProductBomResumeOptions = {},
) {
  const route = options.route ?? useRoute()
  const router = options.router ?? useRouter()
  const auth = options.auth ?? useAuthStore()
  const detail = options.detail ?? ((productId: number) => productApi.detail(productId))
  const openedKey = ref('')
  let opening: Promise<void> | null = null

  async function backToPurchase(attemptId: string): Promise<void> {
    await router.replace({ path: '/purchase', query: { resume: attemptId } })
  }

  async function abort(attempt: BomResumeAttemptV1, reason: string): Promise<void> {
    attempt.phase = 'ABORTED'
    attempt.last_error = reason
    attempt.updated_at = Date.now()
    writeResumeAttempt(attempt)
    showToast(reason, 'error')
    await backToPurchase(attempt.attempt_id)
  }

  async function openMatchingEditor(attempt: BomResumeAttemptV1, productId: number): Promise<void> {
    if (attempt.phase !== 'CONFIGURING' || attempt.current_product_id !== productId) {
      await abort(attempt, '续提产品或状态不匹配，已停止自动下单')
      return
    }
    if (!auth.hasPermission('product_manage')) {
      await abort(attempt, '缺少产品 BOM 管理权限，请联系产品管理员')
      return
    }
    const key = `${attempt.attempt_id}:${productId}`
    if (openedKey.value === key) return
    if (opening) return opening
    opening = (async () => {
      try {
        const response = await detail(productId)
        const product = (response as Product & { product?: Product }).product ?? response
        if (product.id !== productId || typeof product.name !== 'string') {
          throw new Error('产品详情与续提上下文不一致')
        }
        await bomEditorRef.value?.open({ id: product.id, name: product.name })
        openedKey.value = key
      } catch (error) {
        await abort(attempt, getErrorMessage(error, '产品不存在或无法打开 BOM 编辑器'))
      } finally {
        opening = null
      }
    })()
    return opening
  }

  async function openFromRoute(): Promise<void> {
    const rawAttemptId = route.query.resume_attempt_id
    const attemptId = typeof rawAttemptId === 'string' ? rawAttemptId : ''
    if (!attemptId) return
    const ownerId = auth.user?.id
    const attempt = ownerId ? readResumeAttempt(attemptId, ownerId) : null
    if (!attempt) {
      showToast('续提上下文不存在、已过期或不属于当前用户', 'warning')
      await router.replace({ path: '/purchase' })
      return
    }
    if (attempt.phase !== 'CONFIGURING') {
      await backToPurchase(attemptId)
      return
    }
    const productId = positiveRouteId(route.query.product_id)
    if (!productId) {
      await abort(attempt, '产品参数无效，已停止续提')
      return
    }
    await openMatchingEditor(attempt, productId)
  }

  function watchResumeRoute(): void {
    watch(
      () => [route.query.resume_attempt_id, route.query.product_id],
      () => { void openFromRoute() },
      { immediate: true, flush: 'post' },
    )
  }

  async function onSaved(productId: number): Promise<void> {
    const attemptId = String(route.query.resume_attempt_id ?? '')
    const ownerId = auth.user?.id
    const attempt = ownerId ? readResumeAttempt(attemptId, ownerId) : null
    if (!attempt || attempt.phase !== 'CONFIGURING' || attempt.current_product_id !== productId) return
    attempt.phase = 'RETURNING'
    attempt.updated_at = Date.now()
    writeResumeAttempt(attempt)
    await backToPurchase(attemptId)
  }

  async function onClosed(): Promise<void> {
    const attemptId = String(route.query.resume_attempt_id ?? '')
    const ownerId = auth.user?.id
    const attempt = ownerId ? readResumeAttempt(attemptId, ownerId) : null
    if (!attempt || attempt.phase !== 'CONFIGURING') return
    attempt.phase = 'CANCELLED'
    attempt.updated_at = Date.now()
    writeResumeAttempt(attempt)
    await backToPurchase(attemptId)
  }

  return { watchResumeRoute, onSaved, onClosed }
}

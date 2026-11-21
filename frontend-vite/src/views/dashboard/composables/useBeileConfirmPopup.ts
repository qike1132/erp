import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { orderApi } from '@/api'
import { useAuthStore } from '@/stores/auth'

const BEILE_POPUP_KEY = 'beile_confirm_popup_shown'

export function useBeileConfirmPopup() {
  const router = useRouter()
  const authStore = useAuthStore()

  const beilePopupOpen = ref(false)
  const beilePopupText = ref('')
  const beilePopupSub = ref('')

  async function checkBeileConfirmPopup() {
    try {
      if (authStore.user?.factory !== '湖北') return
      // M-35（2026-11-21 审计）：后端 /beile-list 依赖 beile_order_view 权限——
      // 未配权限的湖北账号此前每次挂载都发注定 403 的请求并反复弹「权限不足」。
      if (!authStore.hasPermission('beile_order_view')) return
      if (sessionStorage.getItem(BEILE_POPUP_KEY)) return

      const resp = await orderApi.beileList({ page: 1, per_page: 1 })
      const unconfirmed = Number((resp as { unconfirmed_count?: number })?.unconfirmed_count ?? 0)
      if (unconfirmed <= 0) return

      beilePopupText.value = `湖北待确认记录：${unconfirmed} 条`
      beilePopupSub.value = '有订单或备货尚未确认，请及时处理'
      beilePopupOpen.value = true
    } catch (err) {
      if (import.meta.env.DEV) {
         
        console.warn('[Dashboard] 未确认订单提醒检查失败:', err)
      }
    }
  }

  function closeBeilePopup() {
    beilePopupOpen.value = false
    sessionStorage.setItem(BEILE_POPUP_KEY, '1')
  }

  function goConfirmBeileOrders() {
    closeBeilePopup()
    router.push('/beile-order')
  }

  return {
    beilePopupOpen,
    beilePopupText,
    beilePopupSub,
    checkBeileConfirmPopup,
    closeBeilePopup,
    goConfirmBeileOrders,
  }
}
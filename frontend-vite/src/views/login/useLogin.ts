import { useRouter, useRoute } from 'vue-router'
import { useQueryClient } from '@tanstack/vue-query'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { usePatternRoomStore } from '@/stores/patternRoom'
import { usePerfMark } from '@/composables/usePerfMark'
import { setAccessToken } from '@/utils/secureStorage'
import { getErrorMessage } from '@/types/errors'
import { preloadEcharts } from '@/utils/echartsPreload'
import { prefetchDashboardData } from '@/views/dashboard/composables/useDashboardStats'
import { devError, devLog } from '@/utils/devLog'

/**
 * 登录页共享逻辑（PC / Mobile 复用）
 *
 * P0 遗留修复：remembered_username 从 localStorage 改为 sessionStorage，
 * 关闭页面后自动清除，避免用户名明文持久化。
 */
export function useLogin() {
  const isCapacitor = !!import.meta.env.VITE_CAPACITOR
  const router = useRouter()
  const route = useRoute()
  const authStore = useAuthStore()
  const perf = usePerfMark('login')
  const queryClient = useQueryClient()

  const loading = ref(false)
  const showPassword = ref(false)
  const errorMsg = ref('')
  const form = reactive({ username: '', password: '', remember: false })

  onMounted(async () => {
    perf.markMountEnd()
    // 等待 DOM 完全落定后再设置表单值，避免与 FontAwesome dom.watch() 的
    // MutationObserver 在 Vue 补丁期间竞争，导致 insertBefore(null) TypeError
    await nextTick()
    const saved = sessionStorage.getItem('remembered_username')
    if (saved && saved.length <= 50) {
      form.username = saved.trim()
      form.remember = true
    }
  })

  async function handleLogin() {
    if (!form.username || !form.password) {
      errorMsg.value = '请输入用户名和密码'
      return
    }
    loading.value = true
    errorMsg.value = ''
    perf.mark('auth-start')

    // 登录成功标记：防止 finally 块在组件被路由销毁时仍修改响应式状态
    let loginSuccess = false

    try {
      if (form.remember) {
        sessionStorage.setItem('remembered_username', form.username.trim().slice(0, 50))
      } else {
        sessionStorage.removeItem('remembered_username')
      }
      const res = await authApi.login({
        username: form.username,
        password: form.password,
        remember: isCapacitor ? true : form.remember,
      })
      // 登录成功清除贝乐未确认订单弹窗标记，实现「每登录会话弹一次」
      sessionStorage.removeItem('beile_confirm_popup_shown')
      devLog('[Login] API 响应成功, has_user:', !!res.user)
      perf.markEnd('auth-start')
      perf.measure('auth-api', 'auth-start')
      perf.mark('init-start')

      // 🟢 提前触发 ECharts 预加载：与 authStore.init 并行，
      // 利用路由跳转 + Dashboard 组件挂载的时间窗口下载 ~1MB 图表库
      preloadEcharts()

      if (isCapacitor && res.access_token) {
        setAccessToken(res.access_token)
      }
      // ⚠️ 顺序敏感：下面两个预取都用「当前权限」做门控
      //   （prefetchDashboardData 看 STOCK_STATS_PERMISSIONS；
      //     patternRoom.prefetch 看 customer_sampling_manage），
      //   而权限来自登录响应的 user.permissions。若在 setUserInfo 之前预取，
      //   门控读到的是空 store → 恒 false → 两个预取都成了死代码（有权限的用户
      //   也拿不到「0ms 首载」）。故必须先写用户信息，再预取。
      //   位置须在 setAccessToken 之后：Capacitor 的 Bearer token 要先就绪。
      if (res.user) {
        authStore.setUserInfo(res.user)
        devLog('[Login] 已通过登录响应设置用户信息, username:', res.user.username)
      }
      // 🟢 并行预取 Dashboard 数据：登录成功后立即发起 stats + stock 请求，
      // 填充 Vue Query 缓存，用户到达 Dashboard 时命中缓存 → 首次加载 0ms
      prefetchDashboardData(queryClient)
      // 🟢 并行预取 Pattern-Room 数据（分组列表 + 版师列表），填充 patternRoom Store 缓存，
      // 首次进入 /pattern-room 命中缓存 → 0ms 渲染、无「加载中...」（移动端无此模块，跳过）
      if (!isCapacitor) {
        usePatternRoomStore().prefetch().catch(() => { /* 预取失败静默 */ })
      }
      await authStore.init(true)
      devLog('[Login] authStore.init 完成, loaded:', authStore.loaded, 'isLoggedIn:', authStore.isLoggedIn)
      perf.markEnd('init-start')
      perf.measure('auth-store-init', 'init-start')
      const defaultRedirect = isCapacitor ? '/' : '/dashboard'
      const rawRedirect = route.query.redirect
      const redirect = (typeof rawRedirect === 'string' && rawRedirect.startsWith('/') && !rawRedirect.startsWith('//'))
        ? rawRedirect
        : defaultRedirect
      devLog('[Login] 跳转到:', redirect)
      loginSuccess = true
      router.push(redirect)
    } catch (err: unknown) {
      // 不能把整个 err 交给 console：axios 的 AxiosError.config.data 就是登录请求体
      // `{"username":...,"password":...}`，任何失败（最常见的就是口令错 401）都会把
      // **明文口令**打进控制台，且 console.error 生产构建同样触发。只记状态码与消息。
      devError('[Login] 登录流程异常:', (err as { response?: { status?: number } })?.response?.status,
        (err as Error)?.message)
      perf.markEnd('auth-start')
      perf.measure('auth-api-failed', 'auth-start')
      const msg = getErrorMessage(err, '登录失败，请检查用户名和密码')
      errorMsg.value = msg
    } finally {
      // 仅在登录失败时重置 loading 状态
      // 登录成功时组件将由 router.push() 销毁，此时修改响应式状态会触发无效的 DOM 更新，
      // 导致 Vue 对已移除的父节点执行 insertBefore 操作，抛出 TypeError
      if (!loginSuccess) {
        loading.value = false
      }
    }
  }

  return { loading, showPassword, errorMsg, form, isCapacitor, handleLogin }
}

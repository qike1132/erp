import { useRouter, useRoute } from 'vue-router'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { usePerfMark } from '@/composables/usePerfMark'
import { setAccessToken } from '@/utils/secureStorage'
import { getErrorMessage } from '@/types/errors'
import { preloadEcharts } from '@/utils/echartsPreload'

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
      console.log('[Login] API 响应成功, has_user:', !!res.user)
      perf.markEnd('auth-start')
      perf.measure('auth-api', 'auth-start')
      perf.mark('init-start')

      // 🟢 提前触发 ECharts 预加载：与 authStore.init 并行，
      // 利用路由跳转 + Dashboard 组件挂载的时间窗口下载 ~1MB 图表库
      preloadEcharts()

      if (isCapacitor && res.access_token) {
        setAccessToken(res.access_token)
      }
      // 登录接口返回了用户信息时，直接写入 store（避免登录后再 GET /auth/me）
      if (res.user) {
        authStore.setUserInfo(res.user)
        console.log('[Login] 已通过登录响应设置用户信息, username:', res.user.username)
      }
      await authStore.init(true)
      console.log('[Login] authStore.init 完成, loaded:', authStore.loaded, 'isLoggedIn:', authStore.isLoggedIn)
      perf.markEnd('init-start')
      perf.measure('auth-store-init', 'init-start')
      const defaultRedirect = isCapacitor ? '/' : '/dashboard'
      const rawRedirect = route.query.redirect
      const redirect = (typeof rawRedirect === 'string' && rawRedirect.startsWith('/') && !rawRedirect.startsWith('//'))
        ? rawRedirect
        : defaultRedirect
      console.log('[Login] 跳转到:', redirect)
      loginSuccess = true
      router.push(redirect)
    } catch (err: unknown) {
      console.error('[Login] 登录流程异常:', err)
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

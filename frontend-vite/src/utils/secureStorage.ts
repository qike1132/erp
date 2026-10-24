/**
 * 安全存储抽象层（Capacitor 移动端）
 *
 * 在 Capacitor 环境下使用 @capacitor-community/secure-storage（Keychain/Keystore）
 * 替代 localStorage 存储 access_token，防止敏感凭据被明文读取。
 *
 * 设计要点：
 * - set/remove 同步更新内存缓存 + 异步写入 SecureStorage（fire-and-forget）
 * - Web 环境下所有操作为 no-op（web 使用 cookie 认证，不依赖 token）
 * - 模块名用变量拼接，避免 Vite 静态分析器尝试解析未安装的可选依赖
 *
 * AUD-16 批次 / F2-5（2026-10-24 审计）：删除零调用的 getAccessToken/
 * initTokenCache，并更正原注释「Axios 拦截器需要同步读取 token」——本仓 PC
 * 端是 Cookie 认证，request.ts 不组装任何 Authorization 头；set/remove 的
 * 内存缓存仅供 Capacitor 分支（useLogin）自用，当前 Capacitor 构建形态
 * （VITE_CAPACITOR/@capacitor-* 依赖）未启用，本模块处于休眠状态。
 */

const isCap = !!import.meta.env.VITE_CAPACITOR

// 用变量存储模块名，阻止 Vite/Rolldown 静态解析（该包仅在 Capacitor 构建时安装）
const _SECURE_STORAGE_MOD = '@capacitor-community' + '/secure-storage'

let _tokenCache: string | null = null

/**
 * 保存 access token：同步更新缓存 + 异步写入 SecureStorage。
 * fire-and-forget 模式，缓存立即生效，SecureStorage 后台写入。
 */
export function setAccessToken(token: string): void {
  _tokenCache = token
  if (isCap) {
    import(/* @vite-ignore */ _SECURE_STORAGE_MOD)
      .then(({ SecureStoragePlugin }: { SecureStoragePlugin: { set: (opts: { key: string; value: string }) => Promise<void> } }) =>
        SecureStoragePlugin.set({ key: 'access_token', value: token })
      )
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : 'unknown error'
        console.error('[SecureStorage] 保存 token 失败:', msg)
      })
  }
}

/**
 * 移除 access token：同步清空缓存 + 异步删除 SecureStorage 记录。
 * fire-and-forget 模式，缓存立即清空，SecureStorage 后台删除。
 */
export function removeAccessToken(): void {
  _tokenCache = null
  if (isCap) {
    import(/* @vite-ignore */ _SECURE_STORAGE_MOD)
      .then(({ SecureStoragePlugin }: { SecureStoragePlugin: { remove: (opts: { key: string }) => Promise<void> } }) =>
        SecureStoragePlugin.remove({ key: 'access_token' })
      )
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : 'unknown error'
        console.error('[SecureStorage] 删除 token 失败:', msg)
      })
  }
}

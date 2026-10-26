import { get, post, upload } from './request'
import service from './request'
import type { ApiResponse, LoginResponse, UserInfo } from '@/types'

export const websocketApi = {
  // M9（2026-10-26）：ticket 不是路由从属数据，必须 routeCancel:false。
  // 原用默认 tracked 请求：切路由时 abortPendingRequests() 取消它，而
  // _silenceCanceled() 返回的是**永不 settle** 的 Promise —— useWebSocket.connect()
  // 的 await 永久挂起，connecting 卡在 true（finally 也永不执行），此后该
  // composable 实例再也不会重连。路由守卫在「导航被取消/重定向且页面仍存活」
  // 的窄条件下正好命中。与 unreadCount/list 同一处理口径。
  ticket: () => get<{ ticket: string }>('/notifications/ws-ticket', undefined, { routeCancel: false }),
}

export const authApi = {
  login: (data: { username: string; password: string; remember?: boolean }) => post<LoginResponse>('/auth/login', data),
  logout: () => post('/auth/logout'),
  /**
   * 获取当前登录用户信息。
   *
   * 后端 `GET /auth/me` 的响应模型是 `UserInfoResponse`（**扁平**结构：
   * user_id / username / is_super / factory / permissions），不含 `user` 包装层。
   * 用户不存在或已禁用时直接返回 **401**，而不是返回 `{ user: null }`。
   *
   * 因此这里只声明扁平结构；调用方取 `res` 本身即可。
   * 原声明 `{ user: UserInfo } & UserInfo` 是对响应形状的过度声明：
   * 它允许 `user` 为 null，而 `res.user ?? res` 在 `{ user: null }` 输入下
   * 会退化成外层对象（`null ?? res` 结果为 res），从而造出 id=0 的伪用户。
   */
  me: () => service.get('/auth/me', { timeout: 5000 }) as Promise<UserInfo>,

  /**
   * 上传图片 / 附件（`POST /auth/upload`，multipart，需登录）。
   *
   * 后端限制 5MB 且校验扩展名（`ALLOWED_EXTENSIONS`），返回 `{ url, filename, file_id }`。
   * 走 `upload` 而非 `post`：multipart 需由 axios 自行设置 boundary，不能预设 Content-Type。
   */
  uploadFile: (formData: FormData) =>
    upload<ApiResponse & { url?: string; filename?: string; file_id?: number }>('/auth/upload', formData),
}

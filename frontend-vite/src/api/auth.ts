import { post } from './request'
import service from './request'
import type { LoginResponse, UserInfo } from '@/types'

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
}

import { post, get } from './request'
import type { LoginResponse, UserInfo } from '@/types'

export const authApi = {
  login: (data: { username: string; password: string; remember?: boolean }) => post<LoginResponse>('/auth/login', data),
  logout: () => post('/auth/logout'),
  me: () => get<{ user: UserInfo } & UserInfo>('/auth/me'),
}

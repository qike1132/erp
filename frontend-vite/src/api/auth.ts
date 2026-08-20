import { post } from './request'
import service from './request'
import type { LoginResponse, UserInfo } from '@/types'

export const authApi = {
  login: (data: { username: string; password: string; remember?: boolean }) => post<LoginResponse>('/auth/login', data),
  logout: () => post('/auth/logout'),
  me: () => service.get('/auth/me', { timeout: 5000 }) as Promise<{ user: UserInfo } & UserInfo>,
}

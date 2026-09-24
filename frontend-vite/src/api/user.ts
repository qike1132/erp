import { get, post, put, del } from './request'
import type { User, UserCreate, UserUpdate, PermissionItem, QueryParams } from '@/types'

export const userApi = {
  list: (params?: QueryParams) => get<{ users: User[]; total: number }>('/users/list', params),
  create: (data: UserCreate) => post<User>('/users/create', data),
  update: (id: number, data: UserUpdate) => put<User>(`/users/edit/${id}`, data),
  toggle: (id: number) => post(`/users/toggle/${id}`),
  delete: (id: number) => del(`/users/delete/${id}`),
  getPermission: (id: number) => get<{ success: boolean; user_id: number; user_permission_ids: number[] }>(`/users/permission/${id}`),
  savePermission: (id: number, permissionIds: number[]) =>
    post(`/users/permission/${id}`, { permission_ids: permissionIds }),
}

export const permissionApi = {
  list: () => get<PermissionItem[]>('/permissions/list'),
  tree: () => get<PermissionItem[]>('/permissions/tree'),
}

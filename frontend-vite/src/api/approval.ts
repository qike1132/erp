import { get, post } from './request'
import type { ApprovalListResult, QueryParams } from '@/types'

export const approvalApi = {
  list: (params?: QueryParams) => get<ApprovalListResult>('/approvals/list', params),
  approve: (id: number) => post(`/approvals/approve/${id}`),
  reject: (id: number, reason: string) => post(`/approvals/reject/${id}`, { reason }),
}

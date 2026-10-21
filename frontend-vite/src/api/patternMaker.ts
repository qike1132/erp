import { get, post, del } from './request'
import type { PatternMakerActionResponse as GenPatternMakerActionResponse, PatternMakerListResponse as GenPatternMakerListResponse } from '@/types/api'
import type { WithField, WithItems, WithRequired } from '@/types'

export interface PatternMaker {
  id: number
  name: string
}

export type PatternMakerListResponse = WithItems<Required<GenPatternMakerListResponse>, 'items', PatternMaker>

export type PatternMakerActionResponse = WithField<WithRequired<GenPatternMakerActionResponse, 'success' | 'message' | 'id'>, 'id', number>

export const patternMakerApi = {
  list: () => get<PatternMakerListResponse>('/pattern-maker/pattern-makers'),
  create: (data: { name: string }) =>
    post<PatternMakerActionResponse>('/pattern-maker/pattern-makers', data),
  delete: (id: number) =>
    del<PatternMakerActionResponse>(`/pattern-maker/pattern-makers/${id}`),
}

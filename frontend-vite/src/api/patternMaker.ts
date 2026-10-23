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
  // 登录预取（patternRoomStore.prefetch）会调用它，随后紧跟 router.push。
  // 默认参与路由取消会让 store 的单飞表残留永不 settle 的死 Promise，
  // 用户进 /pattern-room 后被永久卡在「加载中」（2026-10-22 同类事故）。
  list: () => get<PatternMakerListResponse>('/pattern-maker/pattern-makers', undefined, { routeCancel: false }),
  create: (data: { name: string }) =>
    post<PatternMakerActionResponse>('/pattern-maker/pattern-makers', data),
  delete: (id: number) =>
    del<PatternMakerActionResponse>(`/pattern-maker/pattern-makers/${id}`),
}

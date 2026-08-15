import { get, post, del } from './request'

export interface PatternMaker {
  id: number
  name: string
}

export interface PatternMakerListResponse {
  success: boolean
  items: PatternMaker[]
}

export interface PatternMakerActionResponse {
  success: boolean
  message: string
  id?: number
}

export const patternMakerApi = {
  list: () => get<PatternMakerListResponse>('/pattern-room/pattern-makers'),
  create: (data: { name: string }) =>
    post<PatternMakerActionResponse>('/pattern-room/pattern-makers', data),
  delete: (id: number) =>
    del<PatternMakerActionResponse>(`/pattern-room/pattern-makers/${id}`),
}

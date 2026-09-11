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
  list: () => get<PatternMakerListResponse>('/pattern-maker/pattern-makers'),
  create: (data: { name: string }) =>
    post<PatternMakerActionResponse>('/pattern-maker/pattern-makers', data),
  delete: (id: number) =>
    del<PatternMakerActionResponse>(`/pattern-maker/pattern-makers/${id}`),
}

import { get, post, del } from './request'

export const countryApi = {
  list: () => get<{ id: number; name: string }[]>('/aux/countries'),
  create: (name: string) => post('/aux/countries', { name }),
  delete: (id: number) => del(`/aux/countries/${id}`),
}

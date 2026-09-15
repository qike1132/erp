import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  countryApi: {
    list: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
  },
}))

vi.mock('@/api', () => ({ countryApi: mocks.countryApi }))

import { useCountryStore } from '@/stores/country'
import { useSidebarStore } from '@/stores/sidebar'

const STORAGE_KEY = 'erp_countries'

function freshStore() {
  setActivePinia(createPinia())
  return useCountryStore()
}

/** 构造带 HTTP 状态码的错误（getErrorStatus 的读取形式） */
function httpError(status: number) {
  const err = new Error(`HTTP ${status}`) as Error & { response: { status: number } }
  err.response = { status }
  return err
}

describe('country store', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mocks.countryApi.list.mockResolvedValue([])
  })

  afterEach(() => {
    localStorage.clear()
  })

  describe('初始状态', () => {
    it('从 localStorage 读取已有国家列表', () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['中国', '美国']))
      const s = freshStore()
      expect(s.countries).toEqual(['中国', '美国'])
    })

    it('localStorage 内容非法（非 JSON）时降级为空数组', () => {
      localStorage.setItem(STORAGE_KEY, '{broken')
      const s = freshStore()
      expect(s.countries).toEqual([])
    })

    it('首次加载无缓存时为空数组', () => {
      const s = freshStore()
      expect(s.countries).toEqual([])
      expect(s.loaded).toBe(false)
    })
  })

  describe('countryOptions', () => {
    it('映射为 PrimeVue 需要的 value/label 结构', () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['中国']))
      const s = freshStore()
      expect(s.countryOptions).toEqual([{ value: '中国', label: '中国' }])
    })
  })

  describe('fetchCountries', () => {
    it('接口成功后写入状态与 localStorage', async () => {
      const s = freshStore()
      mocks.countryApi.list.mockResolvedValue([{ name: '中国' }, { name: '德国' }])
      await s.fetchCountries()
      expect(s.countries).toEqual(['中国', '德国'])
      expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual(['中国', '德国'])
      expect(s.loaded).toBe(true)
    })

    it('接口失败时保留 localStorage 兜底数据（不清空）', async () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['兜底国']))
      const s = freshStore()
      mocks.countryApi.list.mockRejectedValue(new Error('network'))
      await s.fetchCountries()
      expect(s.countries).toEqual(['兜底国'])
      expect(s.loaded).toBe(true)
    })

    it('接口返回非数组时降级为空列表（不抛异常）', async () => {
      const s = freshStore()
      mocks.countryApi.list.mockResolvedValue({ nope: true } as never)
      await s.fetchCountries()
      expect(s.countries).toEqual([])
    })
  })

  describe('addCountry', () => {
    it('空字符串/纯空白被拒绝（不请求接口）', async () => {
      const s = freshStore()
      expect(await s.addCountry('')).toBe(false)
      expect(await s.addCountry('   ')).toBe(false)
      expect(mocks.countryApi.create).not.toHaveBeenCalled()
    })

    it('前后空白被 trim 后保存', async () => {
      const s = freshStore()
      mocks.countryApi.create.mockResolvedValue({})
      expect(await s.addCountry('  中国  ')).toBe(true)
      expect(mocks.countryApi.create).toHaveBeenCalledWith('中国')
      expect(s.countries).toContain('中国')
    })

    it('重复项直接拒绝（不请求接口）', async () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['中国']))
      const s = freshStore()
      expect(await s.addCountry('中国')).toBe(false)
      expect(mocks.countryApi.create).not.toHaveBeenCalled()
    })

    it('接口成功时加入列表并持久化', async () => {
      const s = freshStore()
      mocks.countryApi.create.mockResolvedValue({})
      await s.addCountry('日本')
      expect(s.countries).toContain('日本')
      expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toContain('日本')
    })

    it('409（已存在）返回 false 且不加入本地列表', async () => {
      const s = freshStore()
      mocks.countryApi.create.mockRejectedValue(httpError(409))
      expect(await s.addCountry('中国')).toBe(false)
      expect(s.countries).not.toContain('中国')
    })

    it('非 409 错误容忍并乐观加入本地（避免网络抖动阻断录入）', async () => {
      const s = freshStore()
      mocks.countryApi.create.mockRejectedValue(new Error('timeout'))
      expect(await s.addCountry('巴西')).toBe(true)
      expect(s.countries).toContain('巴西')
    })
  })

  describe('removeCountry', () => {
    it('不存在的项返回 false', async () => {
      const s = freshStore()
      expect(await s.removeCountry('不存在')).toBe(false)
    })

    it('存在时先按名称查 id 再调删除接口', async () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['中国']))
      const s = freshStore()
      mocks.countryApi.list.mockResolvedValue([{ id: 42, name: '中国' }])
      mocks.countryApi.delete.mockResolvedValue({})

      expect(await s.removeCountry('中国')).toBe(true)
      expect(mocks.countryApi.delete).toHaveBeenCalledWith(42)
      expect(s.countries).toEqual([])
    })

    it('查不到对应 id 时跳过删除接口但仍在本地移除', async () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['中国']))
      const s = freshStore()
      mocks.countryApi.list.mockResolvedValue([{ id: 1, name: '其他' }])

      expect(await s.removeCountry('中国')).toBe(true)
      expect(mocks.countryApi.delete).not.toHaveBeenCalled()
      expect(s.countries).toEqual([])
    })

    it('接口报错时仍在本地移除（保证 UI 可操作）', async () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(['中国']))
      const s = freshStore()
      mocks.countryApi.list.mockRejectedValue(new Error('down'))

      expect(await s.removeCountry('中国')).toBe(true)
      expect(s.countries).toEqual([])
      expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual([])
    })
  })
})

describe('sidebar store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('默认展开（未折叠）', () => {
    const s = useSidebarStore()
    expect(s.isCollapsed).toBe(false)
  })

  it('toggle 在两种状态间切换', () => {
    const s = useSidebarStore()
    s.toggle()
    expect(s.isCollapsed).toBe(true)
    s.toggle()
    expect(s.isCollapsed).toBe(false)
  })

  it('setCollapsed 显式设置状态', () => {
    const s = useSidebarStore()
    s.setCollapsed(true)
    expect(s.isCollapsed).toBe(true)
    s.setCollapsed(false)
    expect(s.isCollapsed).toBe(false)
  })

  it('setCollapsed 传入相同值保持幂等', () => {
    const s = useSidebarStore()
    s.setCollapsed(true)
    s.setCollapsed(true)
    expect(s.isCollapsed).toBe(true)
  })
})

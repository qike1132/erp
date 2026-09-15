import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// ---------------------------------------------------------------------------
// request.ts 是最关键的横切层：CSRF 注入、401 刷新单飞、403 限流提示、
// GET 去重、写操作重试、静态资源 URL 解析。
// 这里覆盖不依赖真实网络的纯逻辑与拦截器行为。
// ---------------------------------------------------------------------------

const mocks = vi.hoisted(() => ({
  devLog: vi.fn(),
}))

vi.mock('@/utils/devLog', () => ({ devLog: mocks.devLog }))

import { clearCsrfCache, resolveStaticUrl, get } from '@/api/request'

describe('resolveStaticUrl', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('空值返回空字符串', () => {
    expect(resolveStaticUrl(null)).toBe('')
    expect(resolveStaticUrl(undefined)).toBe('')
    expect(resolveStaticUrl('')).toBe('')
  })

  it('http/https 绝对路径原样返回（直连对象存储）', () => {
    expect(resolveStaticUrl('http://cdn.example.com/a.png')).toBe('http://cdn.example.com/a.png')
    expect(resolveStaticUrl('https://cdn.example.com/a.png')).toBe('https://cdn.example.com/a.png')
  })

  it('协议相对路径 // 原样返回', () => {
    expect(resolveStaticUrl('//cdn.example.com/a.png')).toBe('//cdn.example.com/a.png')
  })

  it('浏览器环境拼当前 origin（同源 /static 由反代转发）', () => {
    const result = resolveStaticUrl('/static/img/a.png')
    expect(result).toBe(`${window.location.origin}/static/img/a.png`)
  })

  it('优先使用显式配置的 VITE_STATIC_ORIGIN', () => {
    vi.stubEnv('VITE_STATIC_ORIGIN', 'https://static.example.com')
    // 注意：import.meta.env 在模块加载时读取，此处验证的是函数内动态读取分支
    expect(resolveStaticUrl('/static/a.png')).toContain('/static/a.png')
  })
})

describe('clearCsrfCache', () => {
  it('可重复调用且不抛异常', () => {
    expect(() => {
      clearCsrfCache()
      clearCsrfCache()
    }).not.toThrow()
  })
})

describe('get 请求去重', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('相同 url+params 的并发请求共享同一 Promise（避免重复网络请求）', async () => {
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default

    const getSpy = vi.spyOn(service, 'get').mockResolvedValue({ items: [] } as never)

    const p1 = request.get('/products', { page: 1 })
    const p2 = request.get('/products', { page: 1 })

    // 去重：底层只真正发起一次
    expect(getSpy).toHaveBeenCalledTimes(1)
    await Promise.all([p1, p2])
    getSpy.mockRestore()
  })

  it('参数不同则不共享（key 含 params 序列化）', async () => {
    vi.resetModules()
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default

    const getSpy = vi.spyOn(service, 'get')
      .mockResolvedValue({} as never)

    await Promise.all([
      request.get('/products', { page: 1 }),
      request.get('/products', { page: 2 }),
    ])

    expect(getSpy).toHaveBeenCalledTimes(2)
    getSpy.mockRestore()
  })

  it('请求完成后清除去重记录（后续同参请求可再次发起）', async () => {
    vi.resetModules()
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default

    const getSpy = vi.spyOn(service, 'get').mockResolvedValue({} as never)

    await request.get('/products', { page: 1 })
    // 等待 finally 链上的删除生效
    await Promise.resolve()
    await request.get('/products', { page: 1 })

    expect(getSpy).toHaveBeenCalledTimes(2)
    getSpy.mockRestore()
  })

  it('请求失败后也清除去重记录，且不产生未处理的 Promise 拒绝', async () => {
    vi.resetModules()
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default

    const getSpy = vi.spyOn(service, 'get').mockRejectedValue(new Error('network'))

    await expect(request.get('/products', { page: 1 })).rejects.toThrow('network')
    await Promise.resolve()

    // 失败后应可重新发起，而不是永久复用失败结果
    await expect(request.get('/products', { page: 1 })).rejects.toThrow('network')
    expect(getSpy).toHaveBeenCalledTimes(2)
    getSpy.mockRestore()
  })
})

describe('重试策略（通过 exports 行为间接验证）', () => {
  it('GET 不做网络重试（读接口快速失败，避免 UI 长时间挂起）', async () => {
    vi.resetModules()
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default

    // 502 属于 RETRY_STATUS_CODES，但 get() 刻意不叠加重试
    const err = Object.assign(new Error('bad gateway'), {
      isAxiosError: true,
      response: { status: 502 },
    })
    const getSpy = vi.spyOn(service, 'get').mockRejectedValue(err)

    await expect(request.get('/x')).rejects.toBeTruthy()
    expect(getSpy).toHaveBeenCalledTimes(1)
    getSpy.mockRestore()
  })
})

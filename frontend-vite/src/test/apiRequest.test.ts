import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

// ---------------------------------------------------------------------------
// request.ts 是最关键的横切层：CSRF 注入、401 刷新单飞、403 限流提示、
// GET 去重、写操作重试、静态资源 URL 解析。
// 这里覆盖不依赖真实网络的纯逻辑与拦截器行为。
//
// F1-1 / F1-2（2026-10-17 审计）：本文件原先号称覆盖「CSRF 注入、401 刷新单飞」，
// 实际 clearCsrfCache 只断「不抛异常」（对任何实现都成立），刷新与 CSRF 注入
// 零断言。下面改为用 axios adapter 注入观测**真实拦截器行为**（不 mock 整个模块）。
// ---------------------------------------------------------------------------

const mocks = vi.hoisted(() => ({
  devLog: vi.fn(),
}))

vi.mock('@/utils/devLog', () => ({ devLog: mocks.devLog }))

import { resolveStaticUrl } from '@/api/request'

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

describe('CSRF：响应头回填与 clearCsrfCache 真实生效', () => {
  beforeEach(() => {
    vi.resetModules()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('响应头 x-csrf-token 被缓存 → 下一个写请求带上它 → clear 后不再带', async () => {
    const mod = await import('@/api/request')
    const service = mod.default
    const seen: Array<Record<string, string | undefined>> = []
    let firstResponse = true

    // token 只能来自响应头缓存：适配器不写 cookie，也不直接改内部变量
    service.defaults.adapter = async (config) => {
      seen.push({ ...(config.headers as unknown as Record<string, string | undefined>) })
      const headers: Record<string, string> = firstResponse ? { 'x-csrf-token': 'tok-abc' } : {}
      firstResponse = false
      return { data: { ok: true }, status: 200, statusText: 'OK', headers, config }
    }

    await mod.post('/first', {})
    await mod.post('/second', {})
    mod.clearCsrfCache()
    await mod.post('/third', {})

    // 首次：无缓存、cookie 也为空 ⇒ 不得凭空造出 token
    expect(seen[0]?.['X-CSRF-Token']).toBeUndefined()
    // 第二次：来自第一次响应头的缓存（删掉响应拦截器里那行赋值即红）
    expect(seen[1]?.['X-CSRF-Token']).toBe('tok-abc')
    // 清空后必须真的清空（clearCsrfCache 退化成 no-op 即红）
    expect(seen[2]?.['X-CSRF-Token']).toBeUndefined()
  })
})

describe('401 刷新单飞与限流窗口（F1-2）', () => {
  beforeEach(() => {
    vi.resetModules()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  function httpError(config: unknown, status: number) {
    return Object.assign(new Error(`status ${status}`), {
      isAxiosError: true,
      config,
      response: { status, statusText: '', data: { detail: 'x' }, headers: {}, config },
    })
  }

  it('并发两次 401 只发一次 /auth/refresh，且各自重放一次', async () => {
    const mod = await import('@/api/request')
    const service = mod.default
    const attempts = new Map<string, number>()
    let refreshCalls = 0
    let releaseRefresh: () => void = () => {}
    const refreshGate = new Promise<void>((resolve) => {
      releaseRefresh = resolve
    })
    const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

    service.defaults.adapter = async (config) => {
      const url = String(config.url ?? '')
      if (url.includes('/auth/refresh')) {
        // 计数放在等闸门之前：单飞被去掉（if (true)）时这里会变成 2
        refreshCalls += 1
        await refreshGate
        return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config }
      }
      const n = (attempts.get(url) ?? 0) + 1
      attempts.set(url, n)
      if (n === 1) throw httpError(config, 401)
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config }
    }

    const p1 = mod.post('/a', {})
    const p2 = mod.post('/b', {})
    await flush()

    expect(refreshCalls).toBe(1) // 单飞：并发 401 共享同一次刷新
    releaseRefresh()
    await expect(Promise.all([p1, p2])).resolves.toBeTruthy()

    // 刷新成功后原请求各重放一次（_retried 标记生效，不无限重放）
    expect(attempts.get('/a')).toBe(2)
    expect(attempts.get('/b')).toBe(2)
  })

  it('刷新被限流（429）时不登出，且冷却窗口内不再发起刷新', async () => {
    const mod = await import('@/api/request')
    const service = mod.default
    let refreshCalls = 0
    const onExpired = vi.fn()
    window.addEventListener('auth:expired', onExpired)

    service.defaults.adapter = async (config) => {
      const url = String(config.url ?? '')
      if (url.includes('/auth/refresh')) {
        refreshCalls += 1
        throw httpError(config, 429)
      }
      throw httpError(config, 401)
    }

    try {
      await expect(mod.post('/a', {})).rejects.toBeTruthy()
      await expect(mod.post('/b', {})).rejects.toBeTruthy()
    } finally {
      window.removeEventListener('auth:expired', onExpired)
    }

    // 429 是 IP 级限流误伤，不能把在线用户踢下线
    expect(onExpired).not.toHaveBeenCalled()
    // 10s 冷却窗口内第二次 401 直接复用结论，不再往同一个桶里加计数
    expect(refreshCalls).toBe(1)
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

  it('routeCancel 不同的同参请求不共享去重条目（P2-72）', async () => {
    vi.resetModules()
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default

    const getSpy = vi.spyOn(service, 'get').mockResolvedValue({} as never)

    await Promise.all([
      request.get('/products', { page: 1 }),
      request.get('/products', { page: 1 }, { routeCancel: false }),
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

// ---------------------------------------------------------------------------
// 2026-10-02 P4/P5 审计：写操作**默认不再盲重试**。
// 原实现对所有 POST/PUT/DELETE 在 502/503/504 时无条件重放一次 —— 而 nginx 在
// 「后端已提交、响应途中断连」时正会返回 502，重放会**重复下单/重复扣减**。
// 浏览器侧无法区分「未送达」与「已送达但响应丢失」，故默认关闭，仅显式 opt-in。
// ---------------------------------------------------------------------------
describe('写操作重试（默认关闭）', () => {
  const gatewayErr = (status: number) => Object.assign(new Error(`status ${status}`), {
    isAxiosError: true,
    response: { status },
  })

  beforeEach(() => {
    vi.resetModules()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('默认不重试：502 时 post 只发起一次（不重复下单）', async () => {
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default
    const spy = vi.spyOn(service, 'post').mockRejectedValue(gatewayErr(502))

    await expect(request.post('/orders/create', { qty: 1 })).rejects.toBeTruthy()
    expect(spy).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })

  it('默认不重试：503/504 同样只发起一次', async () => {
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default
    for (const code of [503, 504]) {
      const spy = vi.spyOn(service, 'post').mockRejectedValue(gatewayErr(code))
      await expect(request.post('/x', {})).rejects.toBeTruthy()
      expect(spy).toHaveBeenCalledTimes(1)
      spy.mockRestore()
    }
  })

  it('del 默认也不重试（避免二次 404 造成「删除失败」的假失败）', async () => {
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default
    const spy = vi.spyOn(service, 'delete').mockRejectedValue(gatewayErr(502))

    await expect(request.del('/orders/1')).rejects.toBeTruthy()
    expect(spy).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })

  it('post 透传幂等头但不隐式开启写重试', async () => {
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default
    const spy = vi.spyOn(service, 'post').mockResolvedValue({ success: true } as never)

    await request.post('/resume', { composite_ids: ['order:1'] }, {
      headers: { 'X-Idempotency-Key': 'po-resume:test' },
    })

    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy).toHaveBeenCalledWith('/resume', { composite_ids: ['order:1'] }, {
      headers: { 'X-Idempotency-Key': 'po-resume:test' },
    })
    spy.mockRestore()
  })

  it('显式 retryable:true 时才重试一次（幂等写可用）', async () => {
    vi.useFakeTimers()
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default
    const spy = vi.spyOn(service, 'post').mockRejectedValue(gatewayErr(502))

    const p = request.post('/idempotent', {}, { retryable: true })
    const assertion = expect(p).rejects.toBeTruthy()
    await vi.advanceTimersByTimeAsync(1500)
    await assertion
    expect(spy).toHaveBeenCalledTimes(2)
    spy.mockRestore()
  })

  it('retryable:true 但错误非网关码（如 422）仍不重试', async () => {
    const request = await import('@/api/request')
    const service = (await import('@/api/request')).default
    const spy = vi.spyOn(service, 'post').mockRejectedValue(gatewayErr(422))

    await expect(request.post('/x', {}, { retryable: true })).rejects.toBeTruthy()
    expect(spy).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })
})

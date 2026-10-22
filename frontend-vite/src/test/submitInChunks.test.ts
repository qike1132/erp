/**
 * submitInChunks 共享分片提交内核单测（OCR-R28 M-B 重构主体）。
 *
 * 锁死的实现不变量：
 *   1) for (start=0; start<payload.length; start+=chunkSize)，chunkNo=floor(start/chunkSize)+1
 *   2) parseRows 返回 null 或长度!==chunk.length → rowResults=null（对位校验单点强制，M-C 根治）
 *   3) catch 留痕 console.error(`[${logTag}] ${domainLabel}分片提交失败:`, chunkNo, err)
 *   4) abortOn 中止后剩余未尝试片生成占位 outcome（attempted=false），ΣrowCount===payload.length
 *   5) isBusinessFailure 为 true → businessFailed=true 且 error=businessErrorText ?? null
 *   6) errorText 空串 normalize 为非空兜底（L-9 单点）
 *   7) shouldAbortChunkSubmit（L-6）：无状态码（传输失败/网络断）或 4xx → true；5xx → false
 */
import { describe, it, expect, vi } from 'vitest'
import { submitInChunks, shouldAbortChunkSubmit, BATCH_SUBMIT_CHUNK, normalizeDetail, type ChunkSubmitOutcome } from '@/utils/submitInChunks'

interface ChunkRow { id: number }
interface RowResult { ok: boolean }

const rows = (n: number, base = 0): ChunkRow[] => Array.from({ length: n }, (_, i) => ({ id: base + i }))

/** 与 chunk 等长的逐行结果解析（形状不符返回 null） */
const okParse = (res: unknown, chunk: ChunkRow[]): RowResult[] | null => {
  const results = (res as { results?: { ok?: boolean }[] } | null)?.results
  if (!Array.isArray(results) || results.length !== chunk.length) return null
  return results.map((r) => ({ ok: r?.ok === true }))
}

const errText = (err: unknown, chunkNo: number): string =>
  `第${chunkNo}批失败: ${err instanceof Error ? err.message : String(err)}`

/** R32-#15：lastError 已从 SubmitInChunksResult 删除——断言改为按实现原
 * 语义从 chunks 派生（尾部起首个「传输失败或 businessFailed 且 error 非
 * null」的片级文案，businessErrorText 为 null 的片不覆盖前者） */
const lastErrorOf = (chunks: ChunkSubmitOutcome<RowResult>[]): string | null => {
  for (let i = chunks.length - 1; i >= 0; i--) {
    const c = chunks[i]!
    if ((c.businessFailed || !c.delivered) && c.error !== null) return c.error
  }
  return null
}

describe('submitInChunks', () => {
  it('多片切分与尾片不满：apiFn 按片调用、chunkNo 连续、ΣrowCount===payload.length', async () => {
    const api = vi.fn(async (chunk: ChunkRow[]) => ({ results: chunk.map(() => ({ ok: true })) }))
    const res = await submitInChunks(api, rows(5), {
      chunkSize: 2, logTag: 'T', domainLabel: '测试', parseRows: okParse, errorText: errText,
    })

    expect(api).toHaveBeenCalledTimes(3)
    expect(api.mock.calls[0]?.[0]).toHaveLength(2)
    expect(api.mock.calls[1]?.[0]).toHaveLength(2)
    expect(api.mock.calls[2]?.[0]).toHaveLength(1) // 尾片不满
    expect(res.chunks).toHaveLength(3)
    expect(res.chunks.map((c) => c.chunkNo)).toEqual([1, 2, 3])
    expect(res.chunks.reduce((sum, c) => sum + c.rowCount, 0)).toBe(5) // 对位不变量单点
    // R32-#15：aborted/lastError 已删——断言改为 chunks 派生口径
    expect(res.chunks.some((c) => !c.attempted)).toBe(false)
    expect(res.firstError).toBeNull()
    expect(lastErrorOf(res.chunks)).toBeNull()
    expect(res.chunks.every((c) => c.attempted && c.delivered && !c.businessFailed && c.error === null)).toBe(true)
    expect(res.chunks.every((c) => c.rowResults !== null && c.rowResults.length === c.rowCount)).toBe(true)
  })

  it('parseRows 返回偏短数组 → rowResults=null（对位校验单点强制）', async () => {
    const api = vi.fn(async () => ({ results: [{ ok: true }] })) // 恒 1 行结果
    const res = await submitInChunks(api, rows(3), {
      chunkSize: 3, logTag: 'T', domainLabel: '测试', parseRows: okParse, errorText: errText,
    })

    expect(api).toHaveBeenCalledTimes(1)
    expect(res.chunks[0]?.delivered).toBe(true)
    expect(res.chunks[0]?.rowResults).toBeNull()
    expect(res.chunks[0]?.businessFailed).toBe(false)
    expect(res.chunks[0]?.error).toBeNull()
  })

  it('parseRows 返回非 null 偏短数组 → 共享模块对位校验强制 rowResults=null', async () => {
    const api = vi.fn(async () => ({ results: [{ ok: true }] }))
    // parseRows 自身不校验长度（返回非 null 偏短数组）——拦截面在共享模块
    const lenientParse = (res: unknown): RowResult[] | null =>
      (res as { results?: { ok?: boolean }[] }).results?.map((r) => ({ ok: r?.ok === true })) ?? null
    const res = await submitInChunks(api, rows(3), {
      chunkSize: 3, logTag: 'T', domainLabel: '测试', parseRows: lenientParse, errorText: errText,
    })

    expect(res.chunks[0]?.delivered).toBe(true)
    expect(res.chunks[0]?.rowResults).toBeNull() // 单点强制，不信任 parseRows 的长度
  })

  it('firstError/lastError：多片失败取首末（不中止场景）', async () => {
    const api = vi.fn(async (chunk: ChunkRow[]) => {
      if (chunk[0]?.id === 0) throw new Error('一')
      if (chunk[0]?.id === 4) throw new Error('三')
      return { results: chunk.map(() => ({ ok: true })) }
    })
    const res = await submitInChunks(api, rows(6), {
      chunkSize: 2, logTag: 'T', domainLabel: '测试', parseRows: okParse, errorText: errText,
    })

    // 片 1（id=0）失败、片 2 成功、片 3（id=4）失败
    expect(res.chunks.filter((c) => !c.delivered).map((c) => c.chunkNo)).toEqual([1, 3])
    expect(res.firstError).toBe('第1批失败: 一')
    expect(lastErrorOf(res.chunks)).toBe('第3批失败: 三')
    expect(res.chunks.some((c) => !c.attempted)).toBe(false)
  })

  it('abortOn 中止：本片记录后剩余未尝试片占位，ΣrowCount 仍等于 payload.length', async () => {
    const api = vi.fn(async (chunk: ChunkRow[]) => {
      if (chunk[0]?.id === 0) throw new Error('系统性')
      return { results: chunk.map(() => ({ ok: true })) }
    })
    const res = await submitInChunks(api, rows(5), {
      chunkSize: 2, logTag: 'T', domainLabel: '测试', parseRows: okParse, errorText: errText,
      abortOn: () => true,
    })

    expect(api).toHaveBeenCalledTimes(1) // 片 2/3 未尝试
    // R32-#15：aborted 派生口径——存在未尝试片
    expect(res.chunks.some((c) => !c.attempted)).toBe(true)
    expect(res.chunks).toHaveLength(3)
    // 片 1：attempted 且 !delivered；片 2/3：未尝试占位
    expect(res.chunks[0]).toMatchObject({ chunkNo: 1, rowCount: 2, attempted: true, delivered: false, rowResults: null })
    expect(res.chunks[1]).toMatchObject({ chunkNo: 2, rowCount: 2, attempted: false, delivered: false, rowResults: null, error: null })
    expect(res.chunks[2]).toMatchObject({ chunkNo: 3, rowCount: 1, attempted: false, delivered: false, rowResults: null, error: null })
    expect(res.chunks.reduce((sum, c) => sum + c.rowCount, 0)).toBe(5)
    expect(res.firstError).toBe('第1批失败: 系统性')
    expect(lastErrorOf(res.chunks)).toBe('第1批失败: 系统性')
  })

  it('businessFailed：isBusinessFailure 为 true 时置位并携带 businessErrorText', async () => {
    const api = vi.fn(async () => ({ success: false, error: '整片被拒' }))
    const res = await submitInChunks<ChunkRow, RowResult>(api, rows(2), {
      chunkSize: 2, logTag: 'T', domainLabel: '测试',
      parseRows: () => null,
      errorText: errText,
      isBusinessFailure: (res) => (res as { success?: boolean }).success === false,
      businessErrorText: (res) => (res as { error?: string }).error ?? null,
    })

    expect(res.chunks[0]?.delivered).toBe(true)
    expect(res.chunks[0]?.businessFailed).toBe(true)
    expect(res.chunks[0]?.error).toBe('整片被拒')
    expect(res.chunks[0]?.rowResults).toBeNull()
    // businessFailed 的片级 error 计入 firstError（lastError 已删，派生断言）
    expect(res.firstError).toBe('整片被拒')
    expect(lastErrorOf(res.chunks)).toBe('整片被拒')
  })

  it('errorText 空串 normalize 为非空兜底文案（L-9 单点）', async () => {
    const api = vi.fn(async () => { throw new Error('') })
    const res = await submitInChunks(api, rows(1), {
      chunkSize: 1, logTag: 'T', domainLabel: '测试', parseRows: okParse, errorText: () => '',
    })

    expect(res.chunks[0]?.attempted).toBe(true)
    expect(res.chunks[0]?.delivered).toBe(false)
    expect(res.chunks[0]?.error).toBeTruthy()
    expect(res.firstError).toBeTruthy()
    expect(lastErrorOf(res.chunks)).toBeTruthy()
  })

  it('catch 留痕格式：console.error(`[${logTag}] ${domainLabel}分片提交失败:`, chunkNo, err)', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const failure = new Error('网络中断')
      const api = vi.fn(async () => { throw failure })
      await submitInChunks(api, rows(2), {
        chunkSize: 1, logTag: 'useXxx', domainLabel: '域', parseRows: okParse, errorText: errText,
      })
      expect(errSpy).toHaveBeenCalledWith('[useXxx] 域分片提交失败:', 1, failure)
      expect(errSpy).toHaveBeenCalledWith('[useXxx] 域分片提交失败:', 2, failure)
    } finally {
      errSpy.mockRestore()
    }
  })
})

describe('shouldAbortChunkSubmit（L-6 判据：系统性/不可重试错误早停）', () => {
  it('无状态码（传输失败/网络断）→ true', () => {
    expect(shouldAbortChunkSubmit(new Error('network down'))).toBe(true)
    expect(shouldAbortChunkSubmit({ message: 'x' })).toBe(true)
    expect(shouldAbortChunkSubmit(undefined)).toBe(true)
  })
  it('4xx → true', () => {
    expect(shouldAbortChunkSubmit({ response: { status: 400 } })).toBe(true)
    expect(shouldAbortChunkSubmit({ response: { status: 404 } })).toBe(true)
    expect(shouldAbortChunkSubmit({ response: { status: 422 } })).toBe(true)
  })
  it('5xx → false（不早停）', () => {
    expect(shouldAbortChunkSubmit({ response: { status: 500 } })).toBe(false)
    expect(shouldAbortChunkSubmit({ response: { status: 502 } })).toBe(false)
    expect(shouldAbortChunkSubmit({ response: { status: 504 } })).toBe(false)
  })
})

describe('R29：OCR-R29 修复（L4 lastError 防 null 覆盖）', () => {
  it('L4：businessErrorText 返回 null 的失败片不得覆盖既有 lastError', async () => {
    // 片 1 businessFailed 带文案、片 2 businessFailed 无文案（error=null）——
    // lastError 须保持片 1 的非 null 文案（与 firstError 的防回退对称）
    const api = vi.fn(async (chunk: ChunkRow[]) =>
      chunk[0]?.id === 0 ? { success: false, error: '业务失败A' } : { success: false },
    )
    const res = await submitInChunks<ChunkRow, RowResult>(api, rows(2), {
      chunkSize: 1, logTag: 'T', domainLabel: '测试',
      parseRows: () => null,
      errorText: errText,
      isBusinessFailure: (res) => (res as { success?: boolean }).success === false,
      businessErrorText: (res) => (res as { error?: string }).error || null,
    })

    expect(api).toHaveBeenCalledTimes(2)
    expect(res.chunks.filter((c) => c.businessFailed)).toHaveLength(2)
    expect(res.chunks[0]?.error).toBe('业务失败A')
    expect(res.chunks[1]?.error).toBeNull()
    expect(res.firstError).toBe('业务失败A')
    // R29-L4：片 2 的 null 不覆盖片 1 文案——lastError 已删，派生断言
    expect(lastErrorOf(res.chunks)).toBe('业务失败A')
  })
})

describe('R30：OCR-R30 修复（M1 解析异常降级/L1 chunkSize 守卫/L6 入口快照/L7 空串 normalize）', () => {
  it('M1：parseRows 抛异常（响应形状意外）→ 该片 delivered=true、rowResults=null，abortOn 不触发不早停', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const api = vi.fn(async (chunk: ChunkRow[]) =>
        // 片 1（id=0）响应体为 null——出货式直接属性访问 parser 对 null 抛
        // TypeError（真实可触发路径：HTTP 200 空 body）；片 2 正常
        chunk[0]?.id === 0 ? null : { results: chunk.map(() => ({ ok: true })) },
      )
      // 直接属性访问式 parser（无可选链防护）：res 为 null 时抛 TypeError
      const directAccessParse = (res: unknown, chunk: ChunkRow[]): RowResult[] | null => {
        const results = (res as { results?: { ok?: boolean }[] }).results
        if (!Array.isArray(results) || results.length !== chunk.length) return null
        return results.map((r) => ({ ok: r?.ok === true }))
      }
      const res = await submitInChunks(api, rows(4), {
        chunkSize: 2, logTag: 'T', domainLabel: '测试',
        parseRows: directAccessParse,
        errorText: errText,
        // 传输层判据（无状态码 → true）：若解析异常被并入传输失败（M1 缺陷），
        // 该片会被记 !delivered 且触发早停 → 片 2 永不提交
        abortOn: shouldAbortChunkSubmit,
      })

      // 解析异常不得降级为传输失败：响应已到达（delivered=true），只是无法校验
      expect(api).toHaveBeenCalledTimes(2) // 不早停，片 2 照常提交
      expect(res.chunks.some((c) => !c.attempted)).toBe(false)
      expect(res.chunks[0]).toMatchObject({ chunkNo: 1, attempted: true, delivered: true, rowResults: null })
      expect(res.chunks[0]?.businessFailed).toBe(false)
      expect(res.chunks[0]?.error).toBeNull()
      // 片 2 正常解析不受影响
      expect(res.chunks[1]?.rowResults).not.toBeNull()
      expect(res.firstError).toBeNull() // 解析失败不是失败片，无 error 可报
      // 解析失败单独留痕（区别于传输失败的「分片提交失败」留痕）
      expect(errSpy).toHaveBeenCalledWith('[T] 测试分片结果解析失败:', 1, expect.any(TypeError))
    } finally {
      errSpy.mockRestore()
    }
  })

  it('L1：chunkSize=0/-1/1.5 → 抛 Error 拒绝执行（防 0 死循环/NaN 片号）', async () => {
    let calls = 0
    const api = async (): Promise<unknown> => {
      calls += 1
      return {}
    }
    for (const bad of [0, -1, 1.5]) {
      await expect(submitInChunks(api, rows(3), {
        chunkSize: bad, logTag: 'T', domainLabel: '测试', parseRows: okParse, errorText: errText,
      })).rejects.toThrow(/chunkSize 必须为正整数/)
    }
    expect(calls).toBe(0)
  }, 1000)

  it('L6：入口快照——提交期间调用方突变 payload，ΣrowCount 仍等于初始长度', async () => {
    const payload = rows(4)
    const api = vi.fn(async (chunk: ChunkRow[]) => {
      // 首片在途期间对活数组头部插入 + 尾部追加（无快照时循环边界与 slice
      // 窗口一起漂移：头部插入把已提交行重新切进后续片 = 重复提交）
      payload.unshift({ id: -1 })
      payload.push({ id: 99 })
      return { results: chunk.map(() => ({ ok: true })) }
    })
    const res = await submitInChunks(api, payload, {
      chunkSize: 2, logTag: 'T', domainLabel: '测试', parseRows: okParse, errorText: errText,
    })

    // 快照生效：ΣrowCount === 初始 4（不随活数组膨胀为 6），切片窗口不含插入行
    expect(res.chunks.reduce((sum, c) => sum + c.rowCount, 0)).toBe(4)
    expect(res.chunks).toHaveLength(2)
    expect(api).toHaveBeenCalledTimes(2)
    expect(api.mock.calls[0]?.[0]).toEqual([{ id: 0 }, { id: 1 }])
  })

  it('L7：businessErrorText 返回空串 → chunk.error=null，firstError 不被空串污染', async () => {
    // 片 1 businessFailed 带空串文案、片 2 businessFailed 带真实文案——
    // 空串须 normalize 为 null（L-9 对称），firstError 不得被 '' 占位
    const api = vi.fn(async (chunk: ChunkRow[]) =>
      chunk[0]?.id === 0 ? { success: false, error: '' } : { success: false, error: '后片失败原因' },
    )
    const res = await submitInChunks<ChunkRow, RowResult>(api, rows(2), {
      chunkSize: 1, logTag: 'T', domainLabel: '测试',
      parseRows: () => null,
      errorText: errText,
      isBusinessFailure: (res) => (res as { success?: boolean }).success === false,
      businessErrorText: (res) => (res as { error?: string }).error ?? null,
    })

    expect(res.chunks[0]?.error).toBeNull() // '' → null（非 ''）
    expect(res.chunks[1]?.error).toBe('后片失败原因')
    expect(res.firstError).toBe('后片失败原因') // 不被空串污染（'' 占位会挡住回填）
    expect(lastErrorOf(res.chunks)).toBe('后片失败原因')
  })
})

describe('R32：OCR-R31 修复（#3 分片常量导出 / #15 删 aborted/lastError）', () => {
  it('#3：BATCH_SUBMIT_CHUNK 导出且为 500（前后端分片上限单一真相源）', () => {
    // 与后端 auxiliary.py 的 BatchStockInRequest.stockins /
    // BatchStockOutRequest.stockouts 两处 max_length=500 对齐
    expect(BATCH_SUBMIT_CHUNK).toBe(500)
  })

  it('#15：返回值不含 aborted/lastError（接口面收缩，防误用）', async () => {
    const api = vi.fn(async (chunk: ChunkRow[]) => ({ results: chunk.map(() => ({ ok: true })) }))
    const res = await submitInChunks(api, rows(2), {
      chunkSize: 1, logTag: 'T', domainLabel: '测试', parseRows: okParse, errorText: errText,
    })

    // 两字段已从 SubmitInChunksResult 删除（生产零消费者，保留诱导误用）
    expect('aborted' in res).toBe(false)
    expect('lastError' in res).toBe(false)
    // 派生口径：aborted → chunks.some(c => !c.attempted)
    expect(res.chunks.some((c) => !c.attempted)).toBe(false)
  })
})

describe('R34：OCR-R33 修复（M1 判定/文案回调并入容错守卫）', () => {
  it('M1：isBusinessFailure 抛异常 → 降级为已送达未校验（delivered=true/businessFailed=false/rowResults=null），不早停', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const api = vi.fn(async (chunk: ChunkRow[]) =>
        // 片 1（id=0）响应体为 null（HTTP 200 空 body）——M1 缺陷链起点：
        // parseRows 容错返回 null，而出货侧无可选链的判定回调对 null 抛
        // TypeError → 控制流溢出到外层传输 catch（已接受的片被标未送达）
        chunk[0]?.id === 0 ? null : { success: true, results: chunk.map(() => ({ ok: true })) },
      )
      const res = await submitInChunks<ChunkRow, RowResult>(api, rows(2), {
        chunkSize: 1, logTag: 'T', domainLabel: '测试',
        parseRows: okParse, // res=null 时容错返回 null（不抛）
        errorText: errText,
        // 出货侧同款：无可选链属性访问，res=null 抛 TypeError
        isBusinessFailure: (res) => (res as { success?: boolean }).success === false,
        businessErrorText: (res) => (res as { error?: string }).error ?? null,
        // 无状态码 → true：判定回调异常若被并入传输失败（M1 缺陷）会误停剩余片
        abortOn: shouldAbortChunkSubmit,
      })

      // 判定回调异常只降级为「已送达未校验」，不得标 !delivered
      expect(api).toHaveBeenCalledTimes(2) // 不早停，片 2 照常提交
      expect(res.chunks.some((c) => !c.attempted)).toBe(false)
      expect(res.chunks[0]).toMatchObject({ chunkNo: 1, attempted: true, delivered: true, rowResults: null, businessFailed: false, error: null })
      // 片 2 正常解析不受影响
      expect(res.chunks[1]?.rowResults).not.toBeNull()
      expect(res.firstError).toBeNull() // 降级片无 error，不算失败片
      // 判定回调异常走「分片结果解析失败」留痕（区别于传输失败留痕）
      expect(errSpy).toHaveBeenCalledWith('[T] 测试分片结果解析失败:', 1, expect.any(TypeError))
    } finally {
      errSpy.mockRestore()
    }
  })

  it('M1 变体：businessErrorText 抛异常 → businessFailed 判定保留、error=null，已解析的 rowResults 不丢弃', async () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const api = vi.fn(async (chunk: ChunkRow[]) => ({ success: false, results: chunk.map(() => ({ ok: true })) }))
      const res = await submitInChunks<ChunkRow, RowResult>(api, rows(2), {
        chunkSize: 2, logTag: 'T', domainLabel: '测试',
        parseRows: okParse,
        errorText: errText,
        isBusinessFailure: (res) => (res as { success?: boolean }).success === false,
        businessErrorText: () => { throw new Error('boom') },
      })

      // businessErrorText 抛异常：已完成的判定（businessFailed=true）与解析
      // （rowResults）不丢弃，只降级文案为 null——回退到外层 catch 会让
      // delivered=false → 调用方保留已入库行 = 重复提交
      expect(res.chunks[0]).toMatchObject({ chunkNo: 1, attempted: true, delivered: true, businessFailed: true, error: null })
      expect(res.chunks[0]?.rowResults).not.toBeNull()
      expect(res.firstError).toBeNull() // 无文案的 businessFailed 片不贡献 firstError
      expect(errSpy).toHaveBeenCalledWith('[T] 测试分片结果解析失败:', 1, expect.any(Error))
    } finally {
      errSpy.mockRestore()
    }
  })
})

/* ===== R38（OCR-R37 L-h/L-j/L-c，t106）：对位守卫收紧 + 回调防御包装 + primitive trim ===== */

describe('R38：对位守卫与回调防御（OCR-R37 L-h/L-j）', () => {
  it('L-h: parseRows 返回 undefined → 不抛 TypeError、该片落「已送达未校验」、不中止剩余片', async () => {
    // 缺陷（Red）：parsed !== null 只排除 null——parseRows 返回 undefined（常见 JS
    // 失误，如无可选链的属性访问遇形状不符）时 parsed.length 抛 TypeError，且该
    // 表达式在内层 parse 守卫之外，被外层 transport catch 接住 → 已交付分片记
    // delivered:false + shouldAbortChunkSubmit(TypeError)=true 中止剩余片——正是
    // R30-M1/R34-M1 要防的重复提交/过早中止。
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      // 片 1（id=0）响应缺 results——常见失误形态（无可选链/无 null 兜底的
      // 直接属性访问式 parseRows）此时返回 undefined；片 2 正常解析
      const api = vi.fn(async (chunk: ChunkRow[]) =>
        chunk[0]?.id === 0 ? {} : { results: chunk.map(() => ({ ok: true })) },
      )
      const undefinedParse = (res: unknown): RowResult[] | null =>
        (res as { results?: { ok?: boolean }[] }).results as RowResult[] | null
      const res = await submitInChunks(api, rows(4), {
        chunkSize: 2, logTag: 'T', domainLabel: '测试', parseRows: undefinedParse, errorText: errText,
        // 传输层判据（无状态码 → true）：TypeError 被并入传输失败时该片会触发早停
        abortOn: shouldAbortChunkSubmit,
      })

      // Green：undefined 与 null 同为「形状不符」→ rowResults=null 占位（已送达
      // 未校验），不抛异常不中止
      expect(api).toHaveBeenCalledTimes(2)
      expect(res.chunks.some((c) => !c.attempted)).toBe(false)
      expect(res.chunks[0]).toMatchObject({ chunkNo: 1, attempted: true, delivered: true, rowResults: null })
      expect(res.chunks[0]?.error).toBeNull()
      expect(res.chunks[1]?.rowResults).not.toBeNull()
      expect(res.firstError).toBeNull()
    } finally {
      errSpy.mockRestore()
    }
  })

  it('L-j: errorText 抛异常 → 落 FALLBACK_ERROR_TEXT、其余分片继续、已收集结果不丢', async () => {
    // 缺陷（Red）：errorText 在外层 catch 里裸调——抛异常则失败片永不入列
    //（ΣrowCount===payload.length 不变量破坏）且异常逃出 submitInChunks、
    // submitAll 无 catch，用户无任何 toast。
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const api = vi.fn(async (chunk: ChunkRow[]) => {
        if (chunk[0]?.id === 0) throw new Error('网络断')
        return { results: chunk.map(() => ({ ok: true })) }
      })
      const res = await submitInChunks(api, rows(4), {
        chunkSize: 2, logTag: 'T', domainLabel: '测试', parseRows: okParse,
        errorText: () => { throw new Error('formatter boom') },
      })

      // Green：该片落兜底文案并入列，片 2 照常提交
      expect(api).toHaveBeenCalledTimes(2)
      expect(res.chunks[0]).toMatchObject({ chunkNo: 1, attempted: true, delivered: false, error: '提交失败' })
      expect(res.chunks[1]?.rowResults).not.toBeNull()
      expect(res.chunks.reduce((sum, c) => sum + c.rowCount, 0)).toBe(4)
      expect(res.firstError).toBe('提交失败')
      expect(errSpy).toHaveBeenCalledWith('[T] 测试分片失败文案生成异常:', 1, expect.any(Error))
    } finally {
      errSpy.mockRestore()
    }
  })

  it('L-j 变体: errorText 返回 undefined（.trim() 抛）→ 同样落兜底文案不逃逸', async () => {
    const api = vi.fn(async () => { throw new Error('网络断') })
    const res = await submitInChunks(api, rows(1), {
      chunkSize: 1, logTag: 'T', domainLabel: '测试', parseRows: okParse,
      // 类型标注 string 之外的运行时失误：formatter 无返回值（.trim() 抛 TypeError）
      errorText: (() => undefined) as unknown as (err: unknown, chunkNo: number) => string,
    })

    expect(res.chunks[0]?.error).toBe('提交失败')
    expect(res.firstError).toBe('提交失败')
  })

  it('L-j: abortOn 抛异常 → 落 false 不中止，该片正常入列（对位不变量保持）', async () => {
    // 缺陷（Red）：abortOn?.(err) 同样在外层 catch 里裸调——判定回调抛异常会
    // 逃出 submitInChunks，已收集分片结果全丢。
    const api = vi.fn(async (chunk: ChunkRow[]) => {
      if (chunk[0]?.id === 0) throw new Error('网络断')
      return { results: chunk.map(() => ({ ok: true })) }
    })
    const res = await submitInChunks(api, rows(4), {
      chunkSize: 2, logTag: 'T', domainLabel: '测试', parseRows: okParse, errorText: errText,
      abortOn: () => { throw new Error('abort boom') },
    })

    // Green：判定异常按不中止处理，片 2 照常提交
    expect(api).toHaveBeenCalledTimes(2)
    expect(res.chunks.some((c) => !c.attempted)).toBe(false)
    expect(res.chunks.reduce((sum, c) => sum + c.rowCount, 0)).toBe(4)
    expect(res.chunks[0]?.error).toBe('第1批失败: 网络断')
  })
})

describe('R38：normalizeDetail primitive 分支 trim+drop（OCR-R37 L-c）', () => {
  it('L-c: 空白 primitive 项 trim 后丢弃——不产出「; 」空段噪音', () => {
    // 缺陷（Red）：primitive 分支原样返回空白串，穿过 filter((s) => s !== null)
    // 产出「; 」段噪音——与相邻注释（R34-L5）声称要消除的正是同一种噪音。
    // 例：['msg', '  '] → 'msg;  ' → trim 后 'msg;'；['', 'msg'] → '; msg'。
    expect(normalizeDetail(['msg', '  '])).toBe('msg')
    expect(normalizeDetail(['', 'msg'])).toBe('msg')
    // 行为锁：非空白 primitive 仍保留（数字/布尔 String 化）
    expect(normalizeDetail(['msg', 0, false])).toBe('msg; 0; false')
  })
})

describe('R40：normalizeDetail 顶层对象 message/msg 取首个非空字符串（OCR-R39 t113）', () => {
  // OCR-R39 [Low]（2026-10-20）：顶层对象分支 `message ?? msg` 只认
  // message 优先——message 存在但为空串/非字符串（{message:'', msg:
  // '库存不足'}）时 ?? 不落到 msg，有效 msg 被丢 → text='' → null，
  // 丢掉服务端可读原因（正是本函数存在的目的）
  it('t113#3：message 为空串/非字符串/纯空白 → 回退取有效 msg（旧口径得 null）', () => {
    expect(normalizeDetail({ message: '', msg: '库存不足' })).toBe('库存不足')
    expect(normalizeDetail({ message: { code: 'X' }, msg: '库存不足' })).toBe('库存不足')
    // 纯空白 message 同为无效候选（与数组分支 L-c 的 trim 判空口径一致）
    expect(normalizeDetail({ message: '  ', msg: '库存不足' })).toBe('库存不足')
  })

  it('t113#3 行为锁：message 有效时优先；两者皆无效 → null（等价无 detail）', () => {
    expect(normalizeDetail({ code: 'MAINTENANCE', message: '系统维护中' })).toBe('系统维护中')
    expect(normalizeDetail({ message: '', msg: '' })).toBe(null)
    expect(normalizeDetail({ message: '   ' })).toBe(null)
    expect(normalizeDetail({})).toBe(null)
  })

  it('t113#3 回归：数组分支的对象元素取 msg——message 无效不影响数组段', () => {
    expect(normalizeDetail(['x', { message: '', msg: '库存不足' }])).toBe('x; 库存不足')
  })
})

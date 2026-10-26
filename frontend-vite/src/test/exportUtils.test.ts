import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { escapeCsvField, buildCsvRow, downloadCsv } from '../utils/csv'
import { downloadXls } from '../utils/xls'
import { escapeHtml, printHtml, printTable } from '../utils/print'

describe('csv utils', () => {
  describe('escapeCsvField', () => {
    it('null/undefined 转为空字符串', () => {
      expect(escapeCsvField(null)).toBe('')
      expect(escapeCsvField(undefined)).toBe('')
    })

    it('普通字符串原样返回', () => {
      expect(escapeCsvField('abc')).toBe('abc')
    })

    it('数字转为字符串', () => {
      expect(escapeCsvField(123)).toBe('123')
      expect(escapeCsvField(0)).toBe('0')
    })

    it('含逗号的字段用双引号包裹', () => {
      expect(escapeCsvField('a,b')).toBe('"a,b"')
    })

    it('含双引号的字段：包裹并将内部引号翻倍（RFC 4180）', () => {
      expect(escapeCsvField('say "hi"')).toBe('"say ""hi"""')
    })

    it('含换行的字段用双引号包裹（\\n 与 \\r）', () => {
      expect(escapeCsvField('line1\nline2')).toBe('"line1\nline2"')
      expect(escapeCsvField('a\rb')).toBe('"a\rb"')
    })

    it('不含特殊字符的字段不加引号（避免污染 CSV）', () => {
      expect(escapeCsvField('中文名称')).toBe('中文名称')
    })

    // H8：RFC 4180 转义不等于公式中和 —— 以 = + - @ 开头的单元格会被 Excel/WPS
    // 当公式求值（HYPERLINK 外带数据、旧版 DDE 可执行命令），而这些字段来自
    // 用户可控的客户名/产品名/条码。
    it('公式起始字符被中和为文本（= + @）', () => {
      expect(escapeCsvField('=1+1')).toBe("'=1+1")
      expect(escapeCsvField('=HYPERLINK("http://evil","x")')).toBe(
        '"\'=HYPERLINK(""http://evil"",""x"")"',
      )
      expect(escapeCsvField('+86 13800000000')).toBe("'+86 13800000000")
      expect(escapeCsvField('@SUM(A1)')).toBe("'@SUM(A1)")
    })

    it('公式起始字符被中和为文本（- 开头但非纯数字）', () => {
      expect(escapeCsvField('-1+1')).toBe("'-1+1")
      expect(escapeCsvField('-cmd|calc')).toBe("'-cmd|calc")
    })

    it('纯数字（含负数）不中和，避免数值列被转成文本', () => {
      expect(escapeCsvField(-123)).toBe('-123')
      expect(escapeCsvField('-123.45')).toBe('-123.45')
    })

    it('前导空白不能绕过公式中和', () => {
      expect(escapeCsvField('  =cmd')).toBe("'  =cmd")
      expect(escapeCsvField('\t=cmd')).toBe("'\t=cmd")
    })
  })

  describe('buildCsvRow', () => {
    it('按逗号拼接多个字段', () => {
      expect(buildCsvRow(['a', 'b', 'c'])).toBe('a,b,c')
    })

    it('逐字段独立转义：仅含特殊字符的字段被加引号', () => {
      expect(buildCsvRow(['normal', 'has,comma', 42])).toBe('normal,"has,comma",42')
    })

    it('空数组返回空字符串', () => {
      expect(buildCsvRow([])).toBe('')
    })

    it('null/undefined 字段转为空（不产生字面量 "null"）', () => {
      expect(buildCsvRow(['a', null, undefined, 'b'])).toBe('a,,,b')
    })
  })
})

describe('downloadCsv', () => {
  let createObjectURL: ReturnType<typeof vi.fn>
  let revokeObjectURL: ReturnType<typeof vi.fn>
  let clickSpy: ReturnType<typeof vi.fn>
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 跨用例捕获占位，赋值即副作用
  let capturedBlob: Blob | undefined
  let capturedParts: BlobPart[] | undefined
  let capturedType: string | undefined

  beforeEach(() => {
    capturedBlob = undefined
    capturedParts = undefined
    capturedType = undefined

    // jsdom 的 Blob 无 text() 方法，直接拦截构造函数以捕获内容与 MIME
    const RealBlob = globalThis.Blob
    vi.stubGlobal(
      'Blob',
      class {
        constructor(parts: BlobPart[], options?: BlobPropertyBag) {
          capturedParts = parts
          capturedType = options?.type
          capturedBlob = new RealBlob(parts, options)
        }
      },
    )

    createObjectURL = vi.fn(() => 'blob:mock-url')
    revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })

    clickSpy = vi.fn()
    // 拦截 createElement('a') 以捕获 download/href 且避免真实跳转
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreate(tag)
      if (tag === 'a') {
        el.click = clickSpy as unknown as () => void
      }
      return el
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('触发一次下载点击并释放对象 URL', () => {
    downloadCsv(['a,b', '1,2'], 'out.csv')
    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
  })

  it('内容以 BOM 开头（防 Excel 中文乱码）', () => {
    downloadCsv(['姓名', '张三'], 'out.csv')
    expect(String(capturedParts![0]).startsWith('\uFEFF')).toBe(true)
  })

  it('多行以 \\n 连接并保持顺序', () => {
    downloadCsv(['h1,h2', 'v1,v2'], 'out.csv')
    expect(String(capturedParts![0])).toBe('\uFEFF' + 'h1,h2\nv1,v2')
  })

  it('Blob MIME 类型为 text/csv;charset=utf-8', () => {
    downloadCsv(['a'], 'out.csv')
    expect(capturedType).toBe('text/csv;charset=utf-8')
  })

  it('download 属性使用传入的文件名', () => {
    downloadCsv(['a'], '导出结果.csv')
    const anchor = (document.createElement as unknown as { mock: { results: { value: HTMLAnchorElement }[] } })
    // 通过最后一次 createElement('a') 的返回值校验
    const created = anchor.mock.results.map((r) => r.value).filter(Boolean)
    const last = created[created.length - 1] as HTMLAnchorElement
    expect(last.download).toBe('导出结果.csv')
  })
})

describe('downloadXls', () => {
  let capturedParts: BlobPart[] | undefined
  let capturedType: string | undefined
  let clickSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    capturedParts = undefined
    capturedType = undefined

    const RealBlob = globalThis.Blob
    vi.stubGlobal(
      'Blob',
      class {
        constructor(parts: BlobPart[], options?: BlobPropertyBag) {
          capturedParts = parts
          capturedType = options?.type
          return new RealBlob(parts, options)
        }
      },
    )

    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:mock-url'),
      revokeObjectURL: vi.fn(),
    })
    clickSpy = vi.fn()
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreate(tag)
      if (tag === 'a') el.click = clickSpy as unknown as () => void
      return el
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('包裹为完整 HTML 文档并触发下载', () => {
    downloadXls('<table><tr><td>1</td></tr></table>', 'out.xls')
    const text = String(capturedParts![0])
    expect(text).toContain('<html>')
    expect(text).toContain('<meta charset="utf-8">')
    expect(text).toContain('<table><tr><td>1</td></tr></table>')
    expect(text.startsWith('\uFEFF')).toBe(true)
    expect(clickSpy).toHaveBeenCalledTimes(1)
  })

  it('MIME 为 application/vnd.ms-excel;charset=utf-8', () => {
    downloadXls('<table></table>', 'out.xls')
    expect(capturedType).toBe('application/vnd.ms-excel;charset=utf-8')
  })
})

describe('print utils', () => {
  describe('escapeHtml', () => {
    it('转义 & < > " 四类字符', () => {
      expect(escapeHtml('a & b')).toBe('a &amp; b')
      expect(escapeHtml('<script>')).toBe('&lt;script&gt;')
      expect(escapeHtml('say "hi"')).toBe('say &quot;hi&quot;')
    })

    it('& 先于其他字符转义（避免二次转义）', () => {
      // 若先转义 < 再转义 &，'&lt;' 会变成 '&amp;lt;'
      expect(escapeHtml('<')).toBe('&lt;')
      expect(escapeHtml('&')).toBe('&amp;')
    })

    it('普通文本不变', () => {
      expect(escapeHtml('普通中文 abc 123')).toBe('普通中文 abc 123')
    })
  })

  describe('printHtml', () => {
    let appendSpy: ReturnType<typeof vi.spyOn>
    let removeSpy: ReturnType<typeof vi.spyOn>
    let printed: number
    let written: string

    beforeEach(() => {
      vi.useFakeTimers()
      appendedEls.length = 0
      printed = 0
      written = ''

      appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation((el: Node) => {
        appendedEls.push(el as HTMLElement)
        return el
      })
      removeSpy = vi.spyOn(document.body, 'removeChild').mockImplementation((el: Node) => el)

      // 为 iframe 提供可控的 contentDocument / contentWindow
      vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
        if (tag === 'iframe') {
          const iframe = {
            style: {} as CSSStyleDeclaration,
            contentDocument: {
              open: vi.fn(),
              write: vi.fn((s: string) => { written = s }),
              close: vi.fn(),
            },
            get contentWindow() {
              return {
                print: () => { printed++ },
                document: (this as never as { contentDocument: unknown }).contentDocument,
              }
            },
          }
          return iframe as never
        }
        return document.createElement.constructor.prototype as never
      })
    })

    afterEach(() => {
      vi.useRealTimers()
      vi.restoreAllMocks()
    })

    it('追加隐藏 iframe 并在计时后触发打印', () => {
      printHtml('标题', '<p>内容</p>')
      expect(appendSpy).toHaveBeenCalledTimes(1)
      expect(printed).toBe(0)
      vi.advanceTimersByTime(300)
      expect(printed).toBe(1)
    })

    it('标题被 HTML 转义（防止标题注入破坏文档结构）', () => {
      appendSpy.mockClear()
      printHtml('<img src=x onerror=alert(1)>', '<p>x</p>')
      expect(written).not.toContain('<img src=x')
      expect(written).toContain('&lt;img src=x onerror=alert(1)&gt;')
    })

    it('打印后延迟移除 iframe（避免泄漏 DOM 节点）', () => {
      printHtml('t', 'b')
      vi.advanceTimersByTime(300)
      vi.advanceTimersByTime(1000)
      expect(removeSpy).toHaveBeenCalled()
    })
  })

  describe('printTable', () => {
    it('表头与单元格均经 HTML 转义', () => {
      const captured: string[] = []
      vi.useFakeTimers()
      vi.spyOn(document.body, 'appendChild').mockImplementation((el: Node) => el)
      vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
        if (tag === 'iframe') {
          return {
            style: {},
            contentDocument: {
              open: vi.fn(),
              write: vi.fn((s: string) => captured.push(s)),
              close: vi.fn(),
            },
            contentWindow: { print: vi.fn() },
          } as never
        }
        return {} as never
      })

      printTable('表格', ['<b>名称</b>'], [['<script>x</script>']])
      const html = captured.join('')
      expect(html).toContain('&lt;b&gt;名称&lt;/b&gt;')
      expect(html).toContain('&lt;script&gt;x&lt;/script&gt;')
      expect(html).not.toContain('<script>')

      vi.useRealTimers()
      vi.restoreAllMocks()
    })
  })
})

// 用于在 mock 中累积被追加的元素
const appendedEls: HTMLElement[] = []

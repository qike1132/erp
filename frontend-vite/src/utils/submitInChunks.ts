/**
 * submitInChunks — 共享分片提交内核（OCR-R28 M-B，2026-10-20）
 *
 * 为「大批量逐行提交」提供统一的分片循环：调用方只负责构造 payload、解析逐行结果
 * （parseRows）、产出用户面错误文案（errorText）与消费 chunks；切分、对位校验、
 * 留痕、早停、占位全部收口在本模块。
 *
 * ⚠️ 接线现状（2026-10-22 核对）：`useStagedItems` 没有 `submitStockins`，
 * `useStockOutActions.submitBatch` 仍是单次整批提交、尚未分片。本模块目前**零调用方**，
 * 接线前不属于任何既有路径的等价替换。
 *
 * 对位不变量（单点强制）：chunks 覆盖全部行，ΣrowCount === payload.length
 * ——无论中途多少片失败/中止，调用方按 chunks 逐片拼回的行级结果都与原
 * payload 严格等长对位（M-C 的根治：原先 results 少贡献条目只能事后判
 * resultsAligned 兜底，已成功行被整批留在暂存区，重提即重复出库）。
 *
 * 位置说明：本模块是纯异步工具函数（无 Vue 响应式），按项目惯例放 utils/
 * （composables/ 全部为 use 前缀的响应式组合函数）。
 */
import { getErrorStatus } from '@/types/errors'

/**
 * 批量提交分片大小（R32-#3，2026-10-20）：客户端分片粒度。
 *
 * ⚠️ 后端 `auxiliary.py` 的 `BatchStockInRequest.stockins` / `BatchStockOutRequest.stockouts`
 * 目前**没有** `max_length` 约束（2026-10-22 核对），所以这里不是「跨层上限」，
 * 只是把单次请求体控制在可控规模。若要变成硬契约，必须由后端同步加
 * `Field(max_length=BATCH_SUBMIT_CHUNK)`——只改这里不会有任何一方报错。
 */
export const BATCH_SUBMIT_CHUNK = 500

/** 单片提交结果（调用方消费的唯一事实来源） */
export interface ChunkSubmitOutcome<T> {
  chunkNo: number
  rowCount: number
  /** false = 因 abortOn 中止而未尝试（仍生成占位 outcome 保持对位） */
  attempted: boolean
  /** true = 响应到达（HTTP 200）；false = 传输失败（抛异常）或未尝试 */
  delivered: boolean
  /** 与片等长的逐行结果；响应形状不符或长度不对齐时为 null（占位语义由调用方决定） */
  rowResults: T[] | null
  /** HTTP 200 但业务级整片失败（resolved success === false）——出货路径使用 */
  businessFailed: boolean
  /** 片级错误用户面文案（attempted 且 !delivered 时非空；businessFailed 时可能为 null） */
  error: string | null
}

export interface SubmitInChunksResult<T> {
  /** 覆盖全部行：ΣrowCount === payload.length（对位不变量单点） */
  chunks: ChunkSubmitOutcome<T>[]
  /** 首个带非空 error 的失败片文案；无失败片为 null
   * R32-#15（2026-10-20）：aborted/lastError 已删除——生产零消费者，
   * 保留只有测试用到的返回值会诱导后续调用方误用其语义；aborted 可
   * 由 chunks.some(c => !c.attempted) 派生，lastError 可由尾部失败片派生 */
  firstError: string | null
}

export interface SubmitInChunksOptions<Row, T> {
  chunkSize: number
  /** 模块级日志标签（留痕 `[logTag] …` 的方括号部分，如 'useStagedItems'） */
  logTag: string
  /** 域词（备货/出货）：拼接留痕「[logTag] 域词分片提交失败:」逐字保持两调用方现状格式 */
  domainLabel: string
  /** 响应→与 chunk 等长的逐行结果；返回 null 或长度!==chunk.length → rowResults=null */
  parseRows: (res: unknown, chunk: Row[]) => T[] | null
  /** 异常→用户面文案（含 chunkNo 供措辞；空串/纯空白会被 normalize 为非空兜底——L-9 单点） */
  errorText: (err: unknown, chunkNo: number) => string
  /** 返回 true 时中止剩余片（系统性/不可重试错误） */
  abortOn?: (err: unknown) => boolean
  /** 片级业务失败判定（默认恒 false；备货路径无此概念，不传） */
  isBusinessFailure?: (res: unknown) => boolean
  /** businessFailed 时的片级错误文案 */
  businessErrorText?: (res: unknown) => string | null
}

/** errorText 兜底文案（L-9 单点）：调用方 errorText 返回空串/纯空白时使用 */
const FALLBACK_ERROR_TEXT = '提交失败'

/**
 * L-6 早停判据（单一真相源，备货/出货两调用方共用）：
 * getErrorStatus 返回 undefined（传输失败/网络断——请求未达或响应未回，
 * 继续打剩余片只会逐片吃满超时）或 4xx（>=400 且 <500，语义性失败重试
 * 必再败）→ true；5xx（可能瞬时，重试有意义）→ false 不早停。
 *
 * 注：errors.ts 的 getErrorStatus 实际返回 number | undefined（无状态码
 * 即 undefined，非 null），判据按 undefined 处理。
 */
export function shouldAbortChunkSubmit(err: unknown): boolean {
  const status = getErrorStatus(err)
  return status === undefined || (status >= 400 && status < 500)
}

/**
 * 按 chunkSize 顺序分片提交 payload。每片：
 * - 成功：parseRows 解析逐行结果（长度不对齐 → rowResults=null，调用方占位）
 * - 业务级整片失败：isBusinessFailure 判定 → businessFailed=true + 片级 error
 * - 传输失败：console.error 留痕（逐字保持两调用方现状格式）+ errorText
 *   文案（空串 normalize 兜底）；abortOn 判定为 true 时中止剩余片
 * - 中止后的未尝试片：生成占位 outcome（attempted=false）补进 chunks
 */
export async function submitInChunks<Row, T>(
  apiFn: (chunk: Row[]) => Promise<unknown>,
  payload: Row[],
  opts: SubmitInChunksOptions<Row, T>,
): Promise<SubmitInChunksResult<T>> {
  const { chunkSize, logTag, domainLabel, parseRows, errorText, abortOn, isBusinessFailure, businessErrorText } = opts
  // R30-L1（2026-10-20）：chunkSize 是共享内核的调用方输入，0/负值会让
  // start 永不前进（0 还派生 chunkNo=NaN）→ 死循环空片轰击 API；小数会
  // 静默错算片号与切片窗口。现调用方都传字面量 500，守卫防未来调用方
  //（或改成按请求配置的重构）挂死两条提交路径
  if (!Number.isInteger(chunkSize) || chunkSize < 1) {
    throw new Error(`submitInChunks: chunkSize 必须为正整数，收到 ${chunkSize}`)
  }
  const chunks: ChunkSubmitOutcome<T>[] = []
  // aborted 是循环内部状态（R32-#15 后不再外透）：是否中止可由
  // chunks.some(c => !c.attempted) 派生，lastError 可由尾部失败片派生
  let aborted = false
  let firstError: string | null = null

  // R30-L6（2026-10-20）：入口快照（对位不变量的前提）——不变量原先按
  // 「调用方持有的可变数组」计算：提交在途期间调用方增删行会让循环边界
  // 与 slice 窗口一起漂移（头部插入还能把已提交行重新切进后续片 = 重复
  // 提交），ΣrowCount === payload.length 不得依赖「调用方不修改入参」
  // 的约定，快照后与活数组解耦
  const rows = payload.slice()
  for (let start = 0; start < rows.length; start += chunkSize) {
    const chunk = rows.slice(start, start + chunkSize)
    const chunkNo = Math.floor(start / chunkSize) + 1

    if (aborted) {
      // 前片 abort 后的未尝试片：占位保持对位不变量（调用方不自行补齐）
      chunks.push({
        chunkNo,
        rowCount: chunk.length,
        attempted: false,
        delivered: false,
        rowResults: null,
        businessFailed: false,
        error: null,
      })
      continue
    }

    try {
      const res = await apiFn(chunk)
      // R30-M1（2026-10-20）：parseRows 抛异常（响应形状意外）不得并入传输
      // 失败——行已被服务端接收，误报 !delivered 会让调用方保留已入库行，
      // 且 abortOn(非 HTTP 错误)=true 会误停剩余片；降级为 rowResults=null
      //（已送达、未校验），占位语义交调用方决定
      // R34-M1（2026-10-20）：isBusinessFailure/businessErrorText 消费同一
      // res，原先在 parseRows 的守卫之外调用——apiFn resolve null（HTTP
      // 200 空 body）时无可选链的判定回调同样抛异常，控制流入外层 catch
      // → 已被服务端接受的片被标 delivered:false（调用方保留重试 +
      // abortOn 误停剩余片 = 重复提交/过早中止）。三个回调并入同一守卫
      // 块：任一抛异常只降级为「已送达未校验」，已完成的赋值不丢弃
      let parsed: T[] | null = null
      let businessFailed = false
      let rawBusinessError: string | null = null
      try {
        parsed = parseRows(res, chunk)
        businessFailed = isBusinessFailure?.(res) === true
        rawBusinessError = businessFailed ? (businessErrorText?.(res) ?? null) : null
      } catch (parseErr: unknown) {
        console.error(`[${logTag}] ${domainLabel}分片结果解析失败:`, chunkNo, parseErr)
      }
      // R30-L7（2026-10-20）：L-9 对称——businessErrorText 的空串/纯空白
      // 同样视为「无文案」（null），避免 '' 污染 firstError/lastError 与
      // 用户面（firstError 的 ?? 兜底不拦空串，会重现空原因括号）
      const error = rawBusinessError !== null && rawBusinessError.trim() ? rawBusinessError : null
      chunks.push({
        chunkNo,
        rowCount: chunk.length,
        attempted: true,
        delivered: true,
        // 对位校验单点强制：parseRows 返回 null/undefined 等非数组或长度不对齐 →
        // rowResults=null（R38-t106/L-h：parsed !== null 拦不住 undefined，
        // parsed.length 会抛 TypeError 且落外层 catch → 已交付片被记失败+误早停）
        rowResults: Array.isArray(parsed) && parsed.length === chunk.length ? parsed : null,
        businessFailed,
        error,
      })
      if (businessFailed) {
        if (firstError === null && error !== null) firstError = error
      }
    } catch (err: unknown) {
      // 留痕格式逐字保持两调用方现状：[模块名] 域词分片提交失败: 片号 错误对象
      console.error(`[${logTag}] ${domainLabel}分片提交失败:`, chunkNo, err)
      // L-9 单点：errorText 产出空串/纯空白时 normalize 为非空兜底，
      // 杜绝「100 条未入库（，已保留可重试）」这类空原因括号进用户面。
      // R38-t106/L-j：errorText 与 parseRows 等回调同为调用方输入——自身抛
      // 异常或返回 undefined（.trim() 抛）时不得逃出本 catch：失败片不入列
      // 会破坏 ΣrowCount===payload.length 且 submitAll 无兜底（用户无 toast）
      let rawText: string | null = null
      try {
        rawText = errorText(err, chunkNo) ?? null
      } catch (textErr: unknown) {
        console.error(`[${logTag}] ${domainLabel}分片失败文案生成异常:`, chunkNo, textErr)
      }
      const error = rawText?.trim() || FALLBACK_ERROR_TEXT
      chunks.push({
        chunkNo,
        rowCount: chunk.length,
        attempted: true,
        delivered: false,
        rowResults: null,
        businessFailed: false,
        error,
      })
      if (firstError === null) firstError = error
      // R38-t106/L-j：abortOn 判定异常按不中止落（防御对称——判定回调异常
      // 不得改变控制流，留痕后继续提交剩余片）
      let shouldAbort = false
      try {
        shouldAbort = abortOn?.(err) === true
      } catch (abortErr: unknown) {
        console.error(`[${logTag}] ${domainLabel}分片早停判定异常:`, chunkNo, abortErr)
      }
      if (shouldAbort) aborted = true
    }
  }
  return { chunks, firstError }
}

/**
 * R36-M-A（2026-10-20）：chunks→rows 的扁平化三态占位——该逻辑原计划在
 * 备货与出货两条路径各写一份（条件有微妙差异：出货侧判 businessFailed、
 * 备货侧只判 delivered），语义最重的一步（unverified=占位成功 + 失败/未尝试=占位
 * false）必须单点存在，否则两条路径迟早漂移。
 *
 * 三态规则（对位不变量 ΣrowCount === payload.length 由 submitInChunks 保证）：
 * - rowResults !== null → 直通透传（保留行级字段如 error，不重塑）
 * - attempted && delivered && !businessFailed（已送达但无法校验）→
 *   占位 unverifiedRow()（两消费方统一「按成功移除」防重复口径）+
 *   chunkNo 记入 unverifiedChunks
 * - attempted 其余（传输失败/业务级整片失败）→ 占位 failedRow(chunk) +
 *   chunkNo 记入 failedChunks
 * - !attempted（早停后未尝试）→ 占位 failedRow(chunk)，不记 failedChunks
 *   （未尝试 ≠ 失败）
 *
 * unverifiedRow/failedRow 由调用方注入：备货侧是 boolean 标量、出货侧
 * 是 {success, error?} 行对象（failedRow 按 chunk.error/attempted 分流
 * 占位文案）。
 */
export interface FlattenChunkRowsOptions<T> {
  /** 已送达未校验片（占位成功行）的工厂 */
  unverifiedRow: () => T
  /** 传输失败/业务拒绝/未尝试片（占位失败行）的工厂——接收片 outcome 供文案分流 */
  failedRow: (chunk: ChunkSubmitOutcome<T>) => T
}

export interface FlattenChunkRowsResult<T> {
  /** 与原 payload 严格等长对位的逐行结果 */
  rows: T[]
  /** 已送达但未校验（占位成功）的片号列表 */
  unverifiedChunks: number[]
  /** 传输失败/业务级整片失败（占位失败）的片号列表——未尝试片不计入 */
  failedChunks: number[]
}

export function flattenChunkRows<T>(
  chunks: ChunkSubmitOutcome<T>[],
  opts: FlattenChunkRowsOptions<T>,
): FlattenChunkRowsResult<T> {
  const rows: T[] = []
  const unverifiedChunks: number[] = []
  const failedChunks: number[] = []
  for (const chunk of chunks) {
    if (chunk.rowResults !== null) {
      rows.push(...chunk.rowResults)
      continue
    }
    if (chunk.attempted && chunk.delivered && !chunk.businessFailed) {
      // 已送达但无法校验：保守按成功移除（防重复入库/出库优先）
      unverifiedChunks.push(chunk.chunkNo)
      for (let i = 0; i < chunk.rowCount; i++) rows.push(opts.unverifiedRow())
      continue
    }
    if (chunk.attempted) failedChunks.push(chunk.chunkNo)
    for (let i = 0; i < chunk.rowCount; i++) rows.push(opts.failedRow(chunk))
  }
  return { rows, unverifiedChunks, failedChunks }
}

/**
 * 服务端 detail 的用户面 normalize（R32-#2，2026-10-20；R38-t105/L-e
 * 迁入——自 useStagedItems 抽出为备货/出货两条提交路径的单一真相源，
 * useStockOutActions 原本地松版（无截断/无顶层对象分支）随之获得
 * 对象分支+截断，strictest wins）：FastAPI/Pydantic 422 的 detail 是
 * [{loc, msg, type}] 数组——直接插值产出「[object Object]」，500 行片
 * 的数组还可能多 KB。口径：string 直用；数组 join 各项 msg；其他类型
 * String() 化；trim 后空视为无 detail（null）；超长截断（120 字符 +
 * …）防校验噪音倾倒用户面。
 */
export function normalizeDetail(raw: unknown): string | null {
  if (raw === null || raw === undefined) return null
  let text: string
  if (typeof raw === 'string') {
    text = raw
  } else if (Array.isArray(raw)) {
    // R34-L5（2026-10-20）：数组元素收紧——只收非空字符串 msg 与字符串
    // primitive 项：无 msg/非字符串 msg 的对象 String 化产出 [object
    // Object]，空串 msg 被 ?? 保留产出前导/中缀「; 」空段噪音
    text = raw
      .map((item) => {
        const msg = (item as { msg?: unknown } | null)?.msg
        if (typeof msg === 'string' && msg.trim()) return msg
        // 非 null/undefined 的 primitive（数字/布尔等）trim 后保留——FastAPI
        // 偶将裸标量混入 detail 数组；空白 primitive 丢弃（与空串 msg 同为
        // 「; 」空段噪音源，R38-t106/L-c）；对象无有效 msg 时丢弃
        //（String 化只会产出 [object Object]）
        if (['string', 'number', 'boolean', 'bigint'].includes(typeof item)) {
          const primitive = String(item).trim()
          return primitive || null
        }
        return null
      })
      .filter((s): s is string => s !== null)
      .join('; ')
  } else if (typeof raw === 'object') {
    // R36-M-D（2026-10-20）：顶层对象 detail（如维护模式 503 的
    // {code, message}）——原先落到 String() 产出「[object Object]」，
    // 服务端真实消息丢失；FastAPI 自定义异常常把可读原因放
    // message/msg 字段。R40-t113（2026-10-20）：message/msg 取首个
    // 非空字符串（空串/非字符串跳过）——原先 `message ?? msg` 在
    // message 为空串/非字符串（{message:'', msg:'库存不足'}）时 ??
    // 不回退，有效 msg 被丢 → text='' → null（丢服务端可读原因，
    // 正是本函数要防的）
    const candidates: unknown[] = [
      (raw as { message?: unknown }).message,
      (raw as { msg?: unknown }).msg,
    ]
    text = candidates.find((v): v is string => typeof v === 'string' && v.trim() !== '') ?? ''
  } else {
    text = String(raw)
  }
  const trimmed = text.trim()
  if (!trimmed) return null
  return trimmed.length > 120 ? `${trimmed.slice(0, 120)}…` : trimmed
}
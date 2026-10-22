/**
 * 控制台噪音过滤：只静默 Chrome 扩展的已知 runtime.lastError 消息。
 *
 * 根因：Manifest V3 扩展的 content script 向已休眠的 background service worker
 * 发消息时端口已关闭，与应用代码无关。
 *
 * 收窄口径：只匹配**以已知消息开头**的字符串；子串命中不吞（避免掩盖应用错误），
 * Error 对象永不吞。
 */
const SUPPRESS_PATTERNS = [
  'message port closed before a response was received',
  'Could not establish connection. Receiving end does not exist',
]

export function shouldSuppressConsoleError(args: unknown[]): boolean {
  const first = args[0]
  if (typeof first !== 'string') return false
  return SUPPRESS_PATTERNS.some((pattern) => first.startsWith(pattern))
}

export function installConsoleErrorFilter(): void {
  const original = console.error.bind(console)
  console.error = (...args: unknown[]) => {
    if (shouldSuppressConsoleError(args)) return
    original(...args)
  }
}

/**
 * 生成暂存项唯一标识（真相源）。
 *
 * crypto.randomUUID 仅在安全上下文（HTTPS/localhost）可用；
 * 内网 HTTP 部署下它未定义，降级为「时间戳 + 随机数」以避免崩溃。
 *
 * 页面内的既有导入入口是 customer-order/composables/useStagedItems
 * （再导出本模块，勿在该文件重复实现）。
 */
export function genUid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}-${Math.random().toString(36).slice(2, 10)}`
}

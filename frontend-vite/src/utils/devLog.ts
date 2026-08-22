/**
 * 开发模式日志工具 - 生产构建时自动静默（Vite tree-shaking）
 * 替代 console.log/console.warn/console.error/console.group/console.groupEnd，避免 eslint no-console 报错
 */

 

const isDev = import.meta.env?.DEV

export const devLog = (...args: unknown[]): void => {
  if (isDev) console.log(...args)
}

export const devWarn = (...args: unknown[]): void => {
  if (isDev) console.warn(...args)
}

export const devError = (...args: unknown[]): void => {
  if (isDev) console.error(...args)
}

export const devGroup = (...args: unknown[]): void => {
  if (isDev) console.group(...args)
}

export const devGroupEnd = (): void => {
  if (isDev) console.groupEnd()
}

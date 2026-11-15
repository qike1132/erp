/** 品牌单一真相源（F5-3：登录页/侧栏/我的页不得各自硬编码）。 */
export const APP_NAME = '滨发协同'
export const APP_NAME_FULL = '滨发协同系统'
export const APP_VERSION = 'v2.0'

/**
 * 实际部署版本：构建期注入优先，常量只作兜底。
 * 版本号只在这里解析一次，设置页/侧栏/我的页都引用它，避免各页显示不同版本。
 */
export const SYSTEM_VERSION: string =
  (import.meta.env.VITE_APP_VERSION as string | undefined) || APP_VERSION

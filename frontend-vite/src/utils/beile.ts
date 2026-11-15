/**
 * 「贝乐」账号判定（单一真相源）。
 *
 * 该账号只收货、不发货、不维护工序预设。这条规则无法用现有权限点表达：
 * 贝乐持有 outsource_manage（工序预设的读写接口都要它），所以前端必须额外按账号
 * 判定；等预设维护有独立权限码后再改为纯权限点门控。
 *
 * 注意：与后端 scripts/add_outsource_ship_receive_perms.py 的 BEILE_USERNAME 保持一致。
 */
export const BEILE_USERNAME = '贝乐'

export function isBeileUser(username: string | null | undefined): boolean {
  // trim：账号名带空格时精确相等会恒为 false，等于把门控整个弄丢
  return (username || '').trim() === BEILE_USERNAME
}

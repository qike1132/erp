import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import BackupActions from '@/components/backup/BackupActions.vue'

/**
 * 回归锁（2026-11-17 上线前审计 P1-20）：备份加密状态必须可见，密码框不能假装在生效。
 *
 * 事故形态：前端手动备份硬编码 `encrypt: true`，而 `BACKUP_ENCRYPTION_ENABLED=false`
 * 时后端**静默**忽略它产出明文包；页面上密码框永远在那儿，运维填了密码、看到备份
 * 成功，就以为拿到的是加密包。反过来，「加密开了但服务端没配密码」时后端会
 * fail-closed 拒绝，页面也必须提前说清楚。
 *
 * 注意 `encryption` 是**对象**而不是 boolean prop：Vue 对 Boolean 类型 prop 在「没传」
 * 时会强制成 false，正好把「状态没读到」误判成「加密已关闭」—— 本文件第 4 条用例
 * 就是那把锁。
 */
function mountActions(props: Record<string, unknown> = {}) {
  return mount(BackupActions, {
    props: { busy: false, task: null, onFull: () => {}, ...props },
  })
}

describe('P1-20 备份加密状态可见性', () => {
  it('加密关闭：显示「加密已关闭」徽标，且不渲染密码框', async () => {
    const w = mountActions({ encryption: { enabled: false, passwordConfigured: false } })

    expect(w.get('[data-testid="ba-enc-state"]').text()).toContain('加密已关闭')

    await w.get('.ba-adv-toggle').trigger('click')
    expect(w.find('#ba-enc-pw').exists()).toBe(false)
    expect(w.text()).toContain('BACKUP_ENCRYPTION_ENABLED')
  })

  it('加密开启：显示「已开启」徽标并保留密码框', async () => {
    const w = mountActions({ encryption: { enabled: true, passwordConfigured: true } })

    expect(w.get('[data-testid="ba-enc-state"]').text()).toContain('已开启')

    await w.get('.ba-adv-toggle').trigger('click')
    expect(w.find('#ba-enc-pw').exists()).toBe(true)
  })

  it('加密开启但服务端没配密码：提示要补密码（否则后端会拒绝）', async () => {
    const w = mountActions({ encryption: { enabled: true, passwordConfigured: false } })

    await w.get('.ba-adv-toggle').trigger('click')
    expect(w.text()).toContain('未配置密码')
  })

  it('状态未知（status 未加载/老后端）：不谎称已开启，但保留密码框', async () => {
    const w = mountActions()

    expect(w.find('[data-testid="ba-enc-state"]').exists()).toBe(false)
    await w.get('.ba-adv-toggle').trigger('click')
    expect(w.find('#ba-enc-pw').exists()).toBe(true)
    expect(w.text()).toContain('加密状态未知')
  })

  it('加密关闭时提交不携带密码（后端会忽略它，别让人以为生效了）', async () => {
    const calls: Array<{ password?: string }> = []
    const w = mountActions({
      encryption: { enabled: false, passwordConfigured: false },
      onFull: (opts?: { password?: string }) => calls.push(opts ?? {}),
    })

    await w.get('.ba-adv-toggle').trigger('click')
    await w.get('.ba-btn-primary').trigger('click')

    expect(calls).toHaveLength(1)
    expect(calls[0]?.password).toBeUndefined()
  })
})

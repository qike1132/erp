import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import BackupActions from '@/components/backup/BackupActions.vue'
import BackupRecordTable from '@/components/backup/BackupRecordTable.vue'

/**
 * 回归锁（2026-11-17 上线前审计 P1-20）：备份加密状态必须可见，密码框不能假装在生效。
 *
 * 事故形态：前端手动备份硬编码 `encrypt: true`，而 `BACKUP_ENCRYPTION_ENABLED=false`
 * 时后端**静默**忽略它产出明文包；页面上密码框永远在那儿，运维填了密码、看到备份
 * 成功，就以为拿到的是加密包。反过来「加密开了但服务端没配密码」时后端会降级为
 * 明文（服务端默认路径则 fail-closed），页面也得提前说清楚。
 *
 * 注意 `encryption` 是**对象**而不是 boolean prop：Vue 对 Boolean 类型 prop 在「没传」
 * 时会强制成 false，正好把「状态没读到」误判成「加密已关闭」—— 第 4 条用例即为此加锁。
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

  it('加密开启但服务端没配密码：提示会降级为明文（不是「后端会拒绝」）', async () => {
    const w = mountActions({ encryption: { enabled: true, passwordConfigured: false } })

    await w.get('.ba-adv-toggle').trigger('click')
    const text = w.text()
    expect(text).toContain('未配置密码')
    expect(text).toContain('降级为明文包')
  })

  it('状态未知（status 未加载/老后端）：不谎称已开启，但保留密码框', async () => {
    const w = mountActions()

    expect(w.find('[data-testid="ba-enc-state"]').exists()).toBe(false)
    await w.get('.ba-adv-toggle').trigger('click')
    expect(w.find('#ba-enc-pw').exists()).toBe(true)
    expect(w.text()).toContain('加密状态未知')
  })

  it('加密开启时提交会带上密码（正例，先证明这条通路是通的）', async () => {
    const calls: Array<{ password?: string }> = []
    const w = mountActions({
      encryption: { enabled: true, passwordConfigured: true },
      onFull: (opts?: { password?: string }) => calls.push(opts ?? {}),
    })

    await w.get('.ba-adv-toggle').trigger('click')
    await w.get('#ba-enc-pw').setValue('secret')
    await w.get('.ba-btn-primary').trigger('click')

    expect(calls).toHaveLength(1)
    expect(calls[0]?.password).toBe('secret')
  })

  it('加密关闭时提交丢弃密码（先开启填过密码，再被关掉）', async () => {
    const calls: Array<{ password?: string }> = []
    const w = mountActions({
      encryption: { enabled: true, passwordConfigured: true },
      onFull: (opts?: { password?: string }) => calls.push(opts ?? {}),
    })

    await w.get('.ba-adv-toggle').trigger('click')
    await w.get('#ba-enc-pw').setValue('secret')
    // 状态被改成「加密已关闭」后，提交不能继续把密码发过去（后端会忽略，带着只会误导人）
    await w.setProps({ encryption: { enabled: false, passwordConfigured: false } })
    await w.get('.ba-btn-primary').trigger('click')

    expect(calls).toHaveLength(1)
    expect(calls[0]?.password).toBeUndefined()
  })
})

describe('P1-20 备份记录表的加密列', () => {
  const rows = [
    { filename: 'a.zip.enc', encrypted: true },
    { filename: 'b.zip', encrypted: false },
    { filename: 'c.zip' }, // 老记录/文件系统补录：该列可空
  ]

  it('逐行显示 已加密 / 明文 / 未知（null 不当成明文）', () => {
    const w = mount(BackupRecordTable, {
      props: {
        rows, total: rows.length, page: 1, pageSize: 20,
        loading: false, onPageChange: () => {},
      },
    })

    const cells = w.findAll('tbody tr').map((tr) => tr.findAll('td')[2]?.text())
    expect(cells).toEqual(['已加密', '明文', '未知'])
  })
})

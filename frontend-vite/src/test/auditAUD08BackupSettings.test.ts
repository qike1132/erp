/**
 * AUD-08 回归：备份设置界面必须如实标注「保存不生效」（2026-10-17 审计）。
 *
 * 缺陷：backup_settings 表从未接线，清理/备份实际读环境变量，界面保存
 * 却返回「已保存」——用户以为改了保留天数/路径，实际按 env 跑。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import PathSettings from '@/components/backup/PathSettings.vue'

describe('AUD-08 备份设置诚实降级', () => {
  it('显示环境变量生效提示，并禁用保存按钮', () => {
    const wrapper = mount(PathSettings, {
      props: {
        settings: {
          backup_dir: 'D:\\saved',
          default_backup_dir: 'D:\\env-backups',
          effective_backup_dir: 'D:\\env-backups',
          effective_source: 'env',
          retention_days: 7,
          max_count: 30,
          encryption_mode: 'env',
        },
        onValidate: async () => ({ valid: true }),
        onSave: () => {},
      },
    })

    expect(wrapper.text()).toContain('BACKUP_DIR')
    expect(wrapper.text()).toContain('不会生效')
    expect(wrapper.text()).toContain('D:\\env-backups')

    const saveBtn = wrapper.findAll('button').find(b => b.text().includes('保存设置'))
    expect(saveBtn).toBeTruthy()
    expect(saveBtn!.attributes('disabled')).toBeDefined()
  })
})

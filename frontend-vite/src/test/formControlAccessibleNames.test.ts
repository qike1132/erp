/**
 * 表单控件的可访问名（2026-10-30 审计 A-M40）
 *
 * 现场：12 处表单控件只有 placeholder 或紧邻的视觉文本，没有 label/aria-label：
 * 读屏用户听到的是「编辑框」「组合框」，无法知道这一项在控什么（其中包含控制
 * 定时备份启停的开关）。placeholder 不是可访问名——一旦输入内容就消失。
 *
 * 这里按文件锁住「每个控件都带 aria-label」，并单独校验开关同时具备 role=switch。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

function read(path: string): string {
  return readFileSync(resolve(process.cwd(), path), 'utf-8')
}

describe('备份配置类控件的可访问名', () => {
  const schedule = read('src/components/backup/ScheduleConfig.vue')

  it('定时备份开关有 role=switch 且带名字', () => {
    expect(schedule).toContain('role="switch"')
    expect(schedule).toContain('aria-label="启用定时备份"')
  })

  it('任务类型 / 周期 / cron / 执行时间都有名字', () => {
    for (const label of ['aria-label="任务类型"', 'aria-label="备份周期"', 'aria-label="cron 表达式"', 'aria-label="执行时间"']) {
      expect(schedule, `缺少 ${label}`).toContain(label)
    }
  })

  it('ScheduleConfig 里每个 select/input 都带 aria-label', () => {
    const tags = schedule.match(/<(select|input)\b[^>]*>/g) ?? []
    const missing = tags.filter((t) => !t.includes('aria-label='))
    expect(missing, `未命名的控件：\n${missing.join('\n')}`).toEqual([])
  })

  const table = read('src/components/backup/BackupRecordTable.vue')

  it('备份记录表的两个筛选下拉与搜索框都有名字', () => {
    expect(table).toContain('aria-label="按备份类型筛选"')
    expect(table).toContain('aria-label="按备份状态筛选"')
    expect(table).toContain('aria-label="搜索备份名称"')
  })

  it('路径设置里的自定义路径输入框有名字', () => {
    expect(read('src/components/backup/PathSettings.vue')).toContain('aria-label="自定义备份路径"')
  })
})

describe('搜索类控件的可访问名', () => {
  const uiSearch = read('src/components/ui/UiSearchInput.vue')

  it('UiSearchInput 的输入框用 placeholder 作为名字（而不是无名字）', () => {
    expect(uiSearch).toContain(':aria-label="placeholder"')
  })

  const mSearch = read('src/mobile/components/MSearchBar.vue')

  it('MSearchBar 输入框有名字，清空按钮的标签描述真实动作', () => {
    expect(mSearch).toContain(':aria-label="placeholder || \'搜索\'"')
    expect(mSearch).toContain('aria-label="清空搜索"')
    // 历史写法「操作按钮」对读屏毫无信息量
    expect(mSearch).not.toContain('aria-label="操作按钮"')
  })
})

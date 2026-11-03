/**
 * 备份还原前端确认流（2026-11-03 审查 M20，延续 2026-10-30 审计 A-H4）。
 *
 * 已有 `backupAsyncImportConfirm.test.ts` 只锁住「API 客户端层不得硬编码 confirm=true」，
 * 但**调用点**与**对话框交互**都没有测试：删掉 BackupView 里的确认调用、或把对话框的
 * 「必须勾选」去掉，都不会有用例变红。本文件补这两块：
 *
 * 1. RestoreConfirmDialog：未勾选「我已知晓会覆盖」时「确认还原」按钮必须 disabled；
 * 2. BackupView.onUploadRestore：必须先拿到用户确认（confirmDialog.confirm + !ok 早退）
 *    才允许调用 backupApi.asyncImport。
 *
 * 第 2 条为什么用源码顺序守卫而不是挂载 BackupView：BackupView 的依赖图包含十余个
 * 子组件、3 个 onMounted 请求与轮询组合式函数，整页挂载的失败面远大于被验证的行为本身。
 * 本仓既有的结构守卫（如 test_batch_import_cache_invalidation.py）也采用同一权衡：
 * 行为证据在别处，这里只锁「调用点先后顺序」这一结构性契约。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

// 源码原文用 Vite 的 ?raw 导入，而不是 node:fs：
// 1) 不受 cwd 影响（fs 方案要依赖 `npm run test` 的工作目录）；
// 2) 本机 CLI 的 fs 代理对 URL 对象不兼容（实测 "The URL must be of scheme file"）。
import backupViewSource from '../views/backup/BackupView.vue?raw'

import RestoreConfirmDialog from '@/components/backup/RestoreConfirmDialog.vue'

const PLAN = { success: true, table_count: 3, encrypted: false }

function mountDialog() {
  return mount(RestoreConfirmDialog, {
    props: {
      // 先以 open=false 挂载：组件用 watch(open) 复位勾选并选中文件，
      // 直接以 open=true 挂载不会触发 watch，selected 会停留在空串（与真实使用不符）。
      open: false,
      initialFilename: 'backup_2026-11-03.zip',
      plan: PLAN,
      planLoading: false,
      task: null,
      result: null,
      onPlan: () => {},
      onExecute: async () => true,
    },
  })
}

describe('RestoreConfirmDialog 确认闸门', () => {
  it('未勾选「确认覆盖」时执行按钮不可点击，勾选后才可点击', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ open: true })

    const button = wrapper.find('.rw-btn-danger')
    expect(button.exists()).toBe(true)
    expect(button.attributes('disabled')).toBeDefined()

    // 敏感配置勾选不能替代覆盖确认（两个 checkbox 语义独立）
    await wrapper.find('.rw-sensitive-check input').setValue(true)
    expect(wrapper.find('.rw-btn-danger').attributes('disabled')).toBeDefined()

    await wrapper.find('.rw-overwrite-check input').setValue(true)
    expect(wrapper.find('.rw-btn-danger').attributes('disabled')).toBeUndefined()
  })

  it('打开弹窗时必须重置上一次的勾选状态', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ open: true })
    await wrapper.find('.rw-overwrite-check input').setValue(true)
    expect(wrapper.find('.rw-btn-danger').attributes('disabled')).toBeUndefined()

    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true })
    expect(wrapper.find('.rw-btn-danger').attributes('disabled')).toBeDefined()
  })
})

describe('BackupView.onUploadRestore 调用点守卫', () => {
  const source = backupViewSource

  it('必须先弹确认框并处理取消，才允许发起上传还原', () => {
    const fnStart = source.indexOf('async function onUploadRestore')
    expect(fnStart).toBeGreaterThan(-1)

    const importCall = source.indexOf('backupApi.asyncImport', fnStart)
    expect(importCall).toBeGreaterThan(fnStart)

    const gate = source.slice(fnStart, importCall)
    expect(gate).toContain('confirmDialog.confirm(')
    expect(gate).toMatch(/if \(!ok\) return/)
  })

  it('发起请求时必须显式传 confirm: true（后端闸门要求）', () => {
    const fnStart = source.indexOf('async function onUploadRestore')
    const importCall = source.indexOf('backupApi.asyncImport', fnStart)
    expect(source.slice(importCall, importCall + 200)).toContain('confirm: true')
  })
})

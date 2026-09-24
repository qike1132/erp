import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DialogImageUpload from '../views/pattern-room/components/DialogImageUpload.vue'

describe('DialogImageUpload 上传区状态与文案', () => {
  it('uploading 为真时展示「上传中」进行态', () => {
    const wrapper = mount(DialogImageUpload, {
      props: { previewUrl: '/static/uploads/a.png', uploading: true },
    })
    expect(wrapper.text()).toContain('上传中')
  })

  it('uploading 为真时「移除图片」被禁用，避免在途处理把移除静默撤销', () => {
    const wrapper = mount(DialogImageUpload, {
      props: { previewUrl: '/static/uploads/a.png', uploading: true },
    })
    expect(wrapper.get('.diu-img-remove').attributes('disabled')).toBeDefined()
  })

  it('空状态文案同时提示粘贴与拖拽', () => {
    const wrapper = mount(DialogImageUpload, { props: { previewUrl: null } })
    const text = wrapper.text()
    expect(text).toContain('粘贴')
    expect(text).toContain('拖拽')
  })

  it('pasteFlash 为真时根元素带高亮类，为假时还原', async () => {
    const wrapper = mount(DialogImageUpload, {
      props: { previewUrl: null, pasteFlash: false },
    })
    const idle = [...wrapper.classes()]

    await wrapper.setProps({ pasteFlash: true })
    const flashed = [...wrapper.classes()]

    expect(flashed).not.toEqual(idle)
    expect(flashed.some((cls) => cls.includes('flash'))).toBe(true)
  })
})

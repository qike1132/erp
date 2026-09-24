import { onBeforeUnmount, type Ref } from 'vue'

/**
 * 产品图片「粘贴上传」统一入口。
 *
 * 设计要点：
 * 1. 监听挂在 document 上 —— 用户填表时无需先聚焦上传区即可直接 Ctrl+V；
 * 2. 多实例（新增表单 / 编辑弹窗）通过 priority 仲裁，同一时刻只有一个实例响应；
 * 3. 通过 elementFromPoint 做遮挡检测：被弹窗遮住的区域不响应，避免图片被静默
 *    传到底层表单；BOM 等无图片区的弹窗打开时自然无人响应。
 */

export interface ImagePasteOptions {
  /** 上传区元素，用于可见性与遮挡判定 */
  target: Ref<HTMLElement | null>
  /** 命中后的回调（已确保剪贴板中存在图片文件） */
  onFile: (file: File) => void
  /** 是否允许响应，默认 true */
  enabled?: () => boolean
  /** 优先级，数值越大越优先（弹窗 > 表单），默认 0 */
  priority?: number
}

interface PasteHandler {
  target: Ref<HTMLElement | null>
  onFile: (file: File) => void
  enabled: () => boolean
  priority: number
}

const handlers: PasteHandler[] = []
let listenerBound = false

/** 从剪贴板取出第一张图片：items 覆盖截图/网页复制，files 兜底本地文件复制 */
function extractImageFile(dt: DataTransfer | null): File | null {
  if (!dt) return null
  for (const item of Array.from(dt.items ?? [])) {
    if (item.kind === 'file' && item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) return file
    }
  }
  return Array.from(dt.files ?? []).find((f) => f.type.startsWith('image/')) ?? null
}

/** 区域是否可见且未被更高层级元素遮挡 */
function isTargetUsable(target: HTMLElement | null): boolean {
  if (!target || !target.isConnected) return false
  const rect = target.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) return false
  if (rect.right < 0 || rect.bottom < 0 || rect.left > window.innerWidth || rect.top > window.innerHeight) return false
  // 无布局信息的环境（如 jsdom）跳过遮挡检测，避免因 API 缺失而失效
  if (typeof document.elementFromPoint !== 'function') return true
  const x = Math.min(Math.max(rect.left + rect.width / 2, 0), window.innerWidth - 1)
  const y = Math.min(Math.max(rect.top + rect.height / 2, 0), window.innerHeight - 1)
  const top = document.elementFromPoint(x, y)
  return !!top && (top === target || target.contains(top))
}

function onDocumentPaste(e: ClipboardEvent) {
  const file = extractImageFile(e.clipboardData)
  if (!file) return
  const hit = handlers
    .filter((h) => h.enabled())
    .sort((a, b) => b.priority - a.priority)
    .find((h) => isTargetUsable(h.target.value))
  if (!hit) return
  e.preventDefault()
  hit.onFile(file)
}

export function useImagePaste(options: ImagePasteOptions): void {
  const handler: PasteHandler = {
    target: options.target,
    onFile: options.onFile,
    enabled: options.enabled ?? (() => true),
    priority: options.priority ?? 0,
  }
  handlers.push(handler)
  if (!listenerBound) {
    document.addEventListener('paste', onDocumentPaste)
    listenerBound = true
  }
  onBeforeUnmount(() => {
    const index = handlers.indexOf(handler)
    if (index >= 0) handlers.splice(index, 1)
    if (!handlers.length && listenerBound) {
      document.removeEventListener('paste', onDocumentPaste)
      listenerBound = false
    }
  })
}

/**
 * 全局 Toast 提示 composable
 * Plush Cute 风格 · 毛玻璃质感 + 海洋色阴影 + 渐变图标盒
 *
 * 统一通知入口，支持配置化调用
 */
import { icon } from '@fortawesome/fontawesome-svg-core'
import { faCheck, faTimes, faExclamation, faInfo } from '@fortawesome/free-solid-svg-icons'

const TOAST_CONTAINER_ID = '__toast_container__'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface ToastOptions {
  /** 显示时长（毫秒），默认 2500 */
  duration?: number
  /** 是否可手动关闭，默认 false */
  closable?: boolean
  /** 关闭回调 */
  onClose?: () => void
}

/** 全局默认配置 */
let globalConfig: Required<ToastOptions> = {
  duration: 2500,
  closable: false,
  onClose: () => {},
}

/** 更新全局默认配置 */
export function configureToast(config: Partial<ToastOptions>) {
  globalConfig = { ...globalConfig, ...config }
}

const THEME: Record<ToastType, {
  accent: string
  accentShadow: string
  iconDef: typeof faCheck
  iconBg: string
  iconColor: string
}> = {
  success: {
    accent: '#28c76f',
    accentShadow: 'rgba(40, 199, 111, 0.18)',
    iconDef: faCheck,
    iconBg: 'linear-gradient(135deg, #3dc97a, #28c76f)',
    iconColor: '#fff',
  },
  error: {
    accent: '#ea5455',
    accentShadow: 'rgba(234, 84, 85, 0.18)',
    iconDef: faTimes,
    iconBg: 'linear-gradient(135deg, #ed5657, #ea5455)',
    iconColor: '#fff',
  },
  warning: {
    accent: '#ff9f43',
    accentShadow: 'rgba(255, 159, 67, 0.18)',
    iconDef: faExclamation,
    iconBg: 'linear-gradient(135deg, #ffa53d, #ff9f43)',
    iconColor: '#fff',
  },
  info: {
    accent: '#5b8def',
    accentShadow: 'rgba(91, 141, 239, 0.18)',
    iconDef: faInfo,
    iconBg: 'linear-gradient(135deg, #6d95f0, #5b8def)',
    iconColor: '#fff',
  },
}

function getContainer(): HTMLElement {
  let el = document.getElementById(TOAST_CONTAINER_ID)
  if (!el) {
    el = document.createElement('div')
    el.id = TOAST_CONTAINER_ID
    Object.assign(el.style, {
      position: 'fixed',
      top: '0',
      left: '0',
      width: '100%',
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'flex-start',
      paddingTop: '48px',
      pointerEvents: 'none',
      zIndex: '99999',
      // Note: no `gap` here. Spacing between toasts is owned by each toast's
      // `marginTop` so it can be transitioned to 0 on exit — flex `gap` does
      // NOT collapse with item height, so a collapsing toast would leave a
      // residual 10px gap that snaps shut only on `remove()`, causing the
      // exact jank the user reported.
    })
    el.setAttribute('aria-live', 'polite')
    el.setAttribute('aria-atomic', 'false')
    document.body.appendChild(el)
  }
  return el
}

function _renderToast(msg: string, type: ToastType, options: Required<ToastOptions>) {
  const container = getContainer()
  const theme = THEME[type] || THEME.info

  // wrapper — frosted glass card
  const wrap = document.createElement('div')
  Object.assign(wrap.style, {
    display: 'flex',
    alignItems: 'center',
    gap: '14px',
    padding: '12px 20px',
    borderRadius: '14px',
    background: 'rgba(255, 255, 255, 0.88)',
    border: '1px solid rgba(176, 224, 230, 0.35)',
    boxShadow: [
      `0 4px 20px rgba(176, 224, 230, 0.22)`,
      `0 1px 3px rgba(0, 0, 0, 0.04)`,
      `0 0 0 1px rgba(255, 255, 255, 0.6)`,
      `inset 0 1px 0 rgba(255, 255, 255, 0.9)`,
    ].join(', '),
    backdropFilter: 'blur(16px) saturate(180%)',
    WebkitBackdropFilter: 'blur(16px) saturate(180%)',
    color: '#1a1a2e',
    fontSize: '14px',
    fontWeight: '500',
    fontFamily: 'inherit',
    letterSpacing: '0.01em',
    lineHeight: '1.5',
    pointerEvents: 'auto',
    // Spacing between toasts (in place of container `gap`) — owned per-toast
    // so it can be transitioned to 0 on exit.
    marginTop: '10px',
    transition: 'opacity 0.35s cubic-bezier(0.4,0,0.2,1), transform 0.4s cubic-bezier(0.34,1.8,0.64,1)',
    opacity: '0',
    transform: 'translateY(-12px) scale(0.96)',
    maxWidth: '400px',
    minWidth: '180px',
    wordBreak: 'break-word',
    willChange: 'opacity, transform, max-height, margin-top',
  })
  wrap.setAttribute('role', 'alert')

  // icon circle
  const iconWrap = document.createElement('div')
  Object.assign(iconWrap.style, {
    width: '28px',
    height: '28px',
    borderRadius: '9px',
    background: theme.iconBg,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: '0',
    boxShadow: `0 2px 8px ${theme.accentShadow}`,
  })
  // 使用 FontAwesome icon() API 直接渲染 SVG，替代 dom.watch() 方案
  const renderedIcon = icon(theme.iconDef, {
    styles: { color: theme.iconColor },
  })
  const svgEl = renderedIcon.node[0] as SVGElement
  Object.assign(svgEl.style, {
    width: '14px',
    height: '14px',
  })
  svgEl.setAttribute('aria-hidden', 'true')
  iconWrap.appendChild(svgEl)
  wrap.appendChild(iconWrap)

  // text
  const text = document.createElement('span')
  text.textContent = msg
  Object.assign(text.style, {
    flex: '1',
    minWidth: '0',
  })
  wrap.appendChild(text)

  // close button (if closable)
  let closeBtn: HTMLButtonElement | null = null
  if (options.closable) {
    closeBtn = document.createElement('button')
    closeBtn.setAttribute('aria-label', '关闭通知')
    const closeIcon = icon(faTimes)
    closeBtn.innerHTML = Array.isArray(closeIcon.html) ? closeIcon.html.join('') : closeIcon.html
    const closeSvg = closeBtn.querySelector('svg')
    if (closeSvg) {
      closeSvg.style.width = '12px'
      closeSvg.style.height = '12px'
      closeSvg.setAttribute('aria-hidden', 'true')
    }
    Object.assign(closeBtn.style, {
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      padding: '4px',
      marginLeft: '4px',
      color: '#666',
      opacity: '0.6',
      transition: 'opacity 0.2s',
      pointerEvents: 'auto',
    })
    closeBtn.onmouseenter = () => { if (closeBtn) closeBtn.style.opacity = '1' }
    closeBtn.onmouseleave = () => { if (closeBtn) closeBtn.style.opacity = '0.6' }
    wrap.appendChild(closeBtn)
  }

  container.appendChild(wrap)

  // animate in
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      wrap.style.opacity = '1'
      wrap.style.transform = 'translateY(0) scale(1)'
    })
  })

  const removeToast = () => {
    // Capture current height so we can transition it to 0 — collapsing the
    // toast's own reserved space makes sibling toasts slide up smoothly
    // (continuous layout recalculation per frame) instead of snapping
    // into place after `remove()`.
    wrap.style.maxHeight = wrap.offsetHeight + 'px'
    // Capture current marginTop (10px) so we can transition it to 0 in
    // lockstep with max-height. Without this, the 10px gap below the
    // previous toast would snap shut on `remove()` — exactly the jank
    // the user reported in the multi-toast scenario.
    wrap.style.marginTop = '10px'
    // Force reflow so the captured max-height and marginTop are recorded
    // as the start point of the transition.
    void wrap.offsetWidth

    // Redesigned exit: fade + drift + collapse own space (height + margin)
    // in lockstep. The 0.04s delay on the collapse gives the fade a head
    // start so the toast visibly begins to disappear before its space
    // starts shrinking.
    wrap.style.transition = [
      'opacity 0.26s ease-out',
      'transform 0.26s ease-out',
      'max-height 0.26s ease-out 0.04s',
      'margin-top 0.26s ease-out 0.04s',
      'padding 0.26s ease-out 0.04s',
      'border-width 0.26s ease-out 0.04s',
    ].join(', ')
    // Drop the backdrop-filter during exit — recomputing the frosted-glass
    // blur every layout frame is expensive and compounds across multiple
    // simultaneously-exiting toasts. Opacity will hide the resulting
    // flat background long before the user notices.
    wrap.style.backdropFilter = 'none'
    ;(wrap.style as CSSStyleDeclaration & { WebkitBackdropFilter?: string }).WebkitBackdropFilter = 'none'
    wrap.style.opacity = '0'
    wrap.style.transform = 'translateY(-8px) scale(0.94)'
    wrap.style.maxHeight = '0'
    wrap.style.marginTop = '0'
    wrap.style.padding = '0 20px'
    wrap.style.borderWidth = '0'
    wrap.style.overflow = 'hidden'

    // 0.26s + 0.04s delay = 0.30s = 300ms; +40ms buffer for slow devices.
    setTimeout(() => {
      if (wrap.parentNode) wrap.remove()
      if (container.childNodes.length === 0) container.remove()
      options.onClose()
    }, 340)
  }

  // close button handler
  if (closeBtn) {
    closeBtn.onclick = (e) => {
      e.stopPropagation()
      removeToast()
    }
  }

  // auto dismiss
  const timer = setTimeout(removeToast, options.duration)

  // pause on hover (optional UX enhancement)
  wrap.onmouseenter = () => {
    // Could implement pause logic here if needed
  }
}

/**
 * 显示 Toast 通知
 * @param msg 消息内容
 * @param type 通知类型
 * @param options 额外配置
 */
export function showToast(msg: string, type: ToastType = 'info', options?: ToastOptions) {
  const merged: Required<ToastOptions> = {
    duration: options?.duration ?? globalConfig.duration,
    closable: options?.closable ?? globalConfig.closable,
    onClose: options?.onClose ?? globalConfig.onClose,
  }
  _renderToast(msg, type, merged)
}

/** 便捷方法集合 */
export const toast = {
  success: (msg: string, options?: ToastOptions) => showToast(msg, 'success', options),
  error: (msg: string, options?: ToastOptions) => showToast(msg, 'error', options),
  warning: (msg: string, options?: ToastOptions) => showToast(msg, 'warning', options),
  info: (msg: string, options?: ToastOptions) => showToast(msg, 'info', options),
}

/**
 * Composable 形式（用于 Vue 组件内）
 * @example
 * const { showToast, toast } = useToast()
 * toast.success('操作成功')
 */
export function useToast() {
  return { showToast, toast, configureToast }
}

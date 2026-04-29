/**
 * 全局 Toast 提示 composable
 * Plush Cute 风格气泡通知，页面居中显示
 */
const TOAST_CONTAINER_ID = '__toast_container__'

const THEME: Record<string, { bg: string; border: string; icon: string; color: string }> = {
  success: { bg: 'linear-gradient(135deg, #3dc97a, #28c76f)', border: '#28c76f', icon: 'fas fa-check-circle', color: '#fff' },
  error: { bg: 'linear-gradient(135deg, #ed5657, #ea5455)', border: '#ea5455', icon: 'fas fa-times-circle', color: '#fff' },
  warning: { bg: 'linear-gradient(135deg, #ffa53d, #ff9f43)', border: '#ff9f43', icon: 'fas fa-exclamation-circle', color: '#fff' },
  info: { bg: 'linear-gradient(135deg, #6d95f0, #5b8def)', border: '#5b8def', icon: 'fas fa-info-circle', color: '#fff' },
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
      paddingTop: '80px',
      pointerEvents: 'none',
      zIndex: '99999',
      gap: '12px',
    })
    document.body.appendChild(el)
  }
  return el
}

export function showToast(msg: string, type = 'info') {
  const container = getContainer()
  const theme = THEME[type] || THEME.info

  // wrapper
  const wrap = document.createElement('div')
  Object.assign(wrap.style, {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '14px 28px',
    borderRadius: '24px',
    background: theme.bg,
    border: `1px solid ${theme.border}`,
    boxShadow: '0 8px 32px rgba(135, 206, 235, 0.25), 0 2px 8px rgba(0,0,0,0.08)',
    color: theme.color,
    fontSize: '15px',
    fontWeight: '500',
    fontFamily: 'inherit',
    letterSpacing: '0.2px',
    lineHeight: '1.5',
    pointerEvents: 'auto',
    transition: 'opacity 0.4s cubic-bezier(0.4,0,0.2,1), transform 0.4s cubic-bezier(0.4,0,0.2,1)',
    opacity: '0',
    transform: 'translateY(-16px) scale(0.95)',
    backdropFilter: 'blur(8px)',
    WebkitBackdropFilter: 'blur(8px)',
    maxWidth: '480px',
    whiteSpace: 'nowrap',
  })

  // icon
  const icon = document.createElement('i')
  icon.className = theme.icon
  Object.assign(icon.style, {
    fontSize: '18px',
    flexShrink: '0',
  })
  wrap.appendChild(icon)

  // text
  const text = document.createElement('span')
  text.textContent = msg
  wrap.appendChild(text)

  container.appendChild(wrap)

  // animate in
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      wrap.style.opacity = '1'
      wrap.style.transform = 'translateY(0) scale(1)'
    })
  })

  // animate out after 2.5s
  setTimeout(() => {
    wrap.style.opacity = '0'
    wrap.style.transform = 'translateY(-12px) scale(0.95)'
    setTimeout(() => {
      if (wrap.parentNode) wrap.remove()
      if (container.childNodes.length === 0) container.remove()
    }, 400)
  }, 2500)
}

export function useToast() {
  return { showToast }
}

/**
 * 全局 Toast 提示 composable
 * Plush Cute 风格 · 毛玻璃质感 + 海洋色阴影 + 渐变图标盒
 */
const TOAST_CONTAINER_ID = '__toast_container__'

const THEME: Record<string, {
  accent: string
  accentShadow: string
  icon: string
  iconBg: string
  iconColor: string
}> = {
  success: {
    accent: '#28c76f',
    accentShadow: 'rgba(40, 199, 111, 0.18)',
    icon: 'fas fa-check',
    iconBg: 'linear-gradient(135deg, #3dc97a, #28c76f)',
    iconColor: '#fff',
  },
  error: {
    accent: '#ea5455',
    accentShadow: 'rgba(234, 84, 85, 0.18)',
    icon: 'fas fa-times',
    iconBg: 'linear-gradient(135deg, #ed5657, #ea5455)',
    iconColor: '#fff',
  },
  warning: {
    accent: '#ff9f43',
    accentShadow: 'rgba(255, 159, 67, 0.18)',
    icon: 'fas fa-exclamation',
    iconBg: 'linear-gradient(135deg, #ffa53d, #ff9f43)',
    iconColor: '#fff',
  },
  info: {
    accent: '#5b8def',
    accentShadow: 'rgba(91, 141, 239, 0.18)',
    icon: 'fas fa-info',
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
      gap: '10px',
    })
    document.body.appendChild(el)
  }
  return el
}

export function showToast(msg: string, type = 'info') {
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
    transition: 'opacity 0.35s cubic-bezier(0.4,0,0.2,1), transform 0.4s cubic-bezier(0.34,1.8,0.64,1)',
    opacity: '0',
    transform: 'translateY(-12px) scale(0.96)',
    maxWidth: '400px',
    minWidth: '180px',
    wordBreak: 'break-word',
  })

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
  const icon = document.createElement('i')
  icon.className = theme.icon
  Object.assign(icon.style, {
    fontSize: '12px',
    color: theme.iconColor,
  })
  iconWrap.appendChild(icon)
  wrap.appendChild(iconWrap)

  // text
  const text = document.createElement('span')
  text.textContent = msg
  Object.assign(text.style, {
    flex: '1',
    minWidth: '0',
  })
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
    wrap.style.transform = 'translateY(-8px) scale(0.96)'
    setTimeout(() => {
      if (wrap.parentNode) wrap.remove()
      if (container.childNodes.length === 0) container.remove()
    }, 350)
  }, 2500)
}

export function useToast() {
  return { showToast }
}

// 启动遮罩兜底：Vue 挂载成功后 #app-loading 会被替换掉。
// 若主 JS 加载失败 / 挂载报错导致 8 秒后它仍在，则改成失败提示并提供重试按钮，
// 杜绝"永久加载中"的白屏死锁。
//
// ⚠️ 本文件必须保持"零内联脚本、零内联事件处理器"——SPA 入口的 CSP 由
//    config/security-headers.conf 下发，script-src 已是 'self'（不再放行
//    'unsafe-inline'）。守卫测试：fastapi_app/tests/test_spa_csp_no_inline_scripts.py
setTimeout(function () {
  var el = document.getElementById('app-loading')
  if (el && document.getElementById('app')) {
    el.innerHTML =
      '<div class="app-loading-fail">' +
      '<p class="app-fail-text">页面加载失败，请检查网络后重试</p>' +
      '<button type="button" id="app-loading-retry">重新加载</button>' +
      '</div>'
    var retry = document.getElementById('app-loading-retry')
    if (retry) {
      retry.addEventListener('click', function () {
        location.reload()
      })
    }
  }
}, 8000)

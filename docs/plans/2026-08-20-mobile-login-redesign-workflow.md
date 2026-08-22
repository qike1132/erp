---
intent: 完全重构移动端登录页（MLoginView.vue），采用明亮 iOS 风，提升大气感，支持「记住账号」
success_criteria: 手机访问 /login 呈现新页面；记住账号可保存/回填用户名；登录流程正常
risk_level: low
auto_approve: true
worktree: false
---

## Steps

- [ ] **Step 1: 重写 MLoginView.vue 模板与样式（明亮 iOS 风）**
action: 整体重写 d:\erp_system\frontend-vite\src\mobile\views\login\MLoginView.vue。布局：安全区适配；背景 #F5F5F7 + 顶部极淡蓝白环境光渐变；品牌区（LOGO logo_plush.png 96px 圆角 24px + 大标题「滨发协同」+ 副标题）；毛玻璃表单卡片（backdrop-filter blur(24px) saturate(180%)、白 0.72、圆角 24px）；用户名/密码输入框（圆角 14px、聚焦 Apple 蓝环）；记住账号 iOS 开关；登录按钮（Apple 蓝渐变、52px、圆角 16px、按压回弹、loading spinner）；错误信息 Apple 红；底部版本信息。入场动效错峰淡入上浮并尊重 prefers-reduced-motion。样式全部使用 --m-* 设计令牌，不引入新依赖。
loop: false
verify:
  type: artifact
  path: d:\erp_system\frontend-vite\src\mobile\views\login\MLoginView.vue
  assert:
    kind: exists

- [ ] **Step 2: 接入共享 useLogin 并实现记住账号逻辑**
action: 在 MLoginView.vue script 中改为引入共享组合式函数 `@/views/login/useLogin`（返回 loading/showPassword/errorMsg/form/handleLogin），替换原内联登录逻辑；onMounted 时回填 sessionStorage 'remembered_username' 并置位 form.remember；提交时按 form.remember 保存/清除 sessionStorage（沿用 P0 约定）。删除 MLoginView 中原有的 authStore/authApi 内联逻辑。密码字段绑定 showPassword 切换显隐。
loop: false
verify:
  type: shell
  command: cd d:\erp_system\frontend-vite && node -e "const s=require('fs').readFileSync('src/mobile/views/login/MLoginView.vue','utf8'); if(!/useLogin/.test(s)){process.exit(1)}; console.log('useLogin wired')"

- [ ] **Step 3: 构建验证 + dev server 视觉确认**
action: 运行 npm run build 确认编译通过；通过 dev server（http://127.0.0.1:3000）抓取 /src/mobile/views/login/MLoginView.vue 源码模块，确认返回含「滨发协同」大标题、logo_plush、useLogin、记住账号 等关键标记；由用户在手机端 /login 做最终视觉验收（gate: human）。
loop: until npm run build 通过且模块抓取含关键标记
max_iterations: 3
verify:
  - type: shell
    command: cd d:\erp_system\frontend-vite && npm run build
  - type: shell
    command: powershell -Command "$r=Invoke-WebRequest -Uri 'http://127.0.0.1:3000/src/mobile/views/login/MLoginView.vue' -UseBasicParsing; $t=[System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()); if($t -match '滨发协同' -and $t -match 'logo_plush' -and $t -match 'useLogin'){'OK'}else{exit 1}"
gate: human

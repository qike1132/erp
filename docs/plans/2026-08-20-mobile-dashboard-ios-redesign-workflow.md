---
intent: 将移动端概览页按 iOS 风格重构：移除假状态栏、emoji 换 SF Symbol SVG、核心 Hero 置顶 + 分组、hairline 分隔、新增下拉刷新
success_criteria: 手机端概览页呈现 iOS 质感；下拉刷新可用；核心指标置顶、分组清晰；构建通过
risk_level: low
auto_approve: true
worktree: false
---

## Steps

- [ ] **Step 1: 重构 4 个卡片组件为 iOS 风格（SVG 图标 + 分组 + hairline）**
action: 修改 d:\erp_system\frontend-vite\src\mobile\views\dashboard\components\ 下 4 个文件：OrderOverviewCard.vue、StockOverviewCard.vue、ProductionDeptCard.vue、WarehouseCard.vue。将模板中的 emoji（📋📁🖥🏭📥📤💰💸 等）全部替换为 SF Symbol 风格线性 SVG（stroke-width 1.8，Apple 语义色），放入 tinted 圆角方盒（--m-radius-icon-box 12px，背景 --m-accent-glow 等）。卡片统一：背景 #FFFFFF、圆角 20px、内边距 20px、阴影 0 1px 3px rgba(0,0,0,0.08) + 0 4px 12px rgba(0,0,0,0.04)、边框 0.5px rgba(0,0,0,0.04)。行间分隔用 hairline 0.5px rgba(60,60,67,0.29)。指标数值用 --m-text-primary/#1D1D1F，重点数值用 --m-accent/#0071E3，标签用 --m-text-tertiary/#AEAEB2。数据绑定、props、fmtNum/fmtMoney 保持不变。
loop: false
verify:
  type: shell
  command: cd d:\erp_system\frontend-vite && node -e "const fs=require('fs');for(const f of ['OrderOverviewCard','StockOverviewCard','ProductionDeptCard','WarehouseCard']){const s=fs.readFileSync('src/mobile/views/dashboard/components/'+f+'.vue','utf8');if(/<svg/.test(s)===false){console.error(f+' missing svg');process.exit(1)}} console.log('all cards have svg icons')"

- [ ] **Step 2: 重写 DashboardMobile.vue（iOS Large Title + 核心 Hero + 分组 + 下拉刷新）**
action: 整体重写 d:\erp_system\frontend-vite\src\mobile\views\dashboard\DashboardMobile.vue。要点：(a) 移除假系统状态栏（.m-status-bar 时间/信号/电池）；(b) iOS Large Title 导航区：大标题「概览」34px/800/letter-spacing -0.5px + 副行（今日日期 + 「●实时」绿点）+ 右上刷新按钮（旋转箭头 SVG）；(c) 核心 Hero 卡置顶：今日订单数 + 今日总产值两个大数字（数据来自 data.orders.daily_qty / data.production.total_value，若为 null 显示 —），Apple 蓝渐变背景 rgba 渐变 + 白字，附次行小字（本月订单 data.orders.total_qty / 累计产值 data.stock.total_amount）；(d) 分组：分节小标题（uppercase、13px、--m-text-tertiary，如「业务」「生产」「仓储」）+ 白卡分组，卡片沿用 Step1 风格；(e) 下拉刷新：监听滚动容器（.m-layout-content）touchstart/touchmove/touchend，scrollTop<=0 时下拉累计距离 → 橡皮筋（transform translateY + 缩放）→ 松手触发 loadData/refresh，显示旋转刷新指示器；prefers-reduced-motion 时禁用动画；(f) 保留卡片错峰入场（使用 useDashboardMobileData 的 visibleCards/triggerReveal）与骨架屏，骨架屏改为 iOS 圆角风格。
loop: false
verify:
  type: artifact
  path: d:\erp_system\frontend-vite\src\mobile\views\dashboard\DashboardMobile.vue
  assert:
    kind: exists

- [ ] **Step 3: useDashboardMobileData 增加下拉刷新状态**
action: 修改 d:\erp_system\frontend-vite\src\mobile\views\dashboard\composables\useDashboardMobileData.ts：新增 `refreshing` ref（false）与 `onPullRefresh()` 函数——置 refreshing=true、调用现有 loadData()、结束后置 refreshing=false；保证与现有 loading/visibleCards 逻辑不冲突（刷新不重置 visibleCards 为 false，避免闪动）。导出新增的 refreshing 与 onPullRefresh。
loop: false
verify:
  type: shell
  command: cd d:\erp_system\frontend-vite && node -e "const s=require('fs').readFileSync('src/mobile/views/dashboard/composables/useDashboardMobileData.ts','utf8');if(!/onPullRefresh/.test(s)||!/refreshing/.test(s)){process.exit(1)};console.log('pull refresh wired')"

- [ ] **Step 4: 构建验证 + 线上确认**
action: 运行 npm run build 确认编译通过；通过 http://127.0.0.1:3000 访问移动端概览（dev 无鉴权时登录后可见；否则抓取源码模块确认关键标记：Large Title「概览」、无「m-status-bar」假状态栏、含「下拉刷新/refreshing」逻辑）；由用户在手机端做视觉与交互验收（gate: human）。
loop: until npm run build 通过且源码模块含关键标记
max_iterations: 3
verify:
  - type: shell
    command: cd d:\erp_system\frontend-vite && npm run build
  - type: shell
    command: powershell -Command "$r=Invoke-WebRequest -Uri 'http://127.0.0.1:3000/src/mobile/views/dashboard/DashboardMobile.vue' -UseBasicParsing; $t=[System.Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()); if($t -match '概览' -and $t -notmatch 'm-status-bar'){'OK'}else{exit 1}"
gate: human

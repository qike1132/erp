# 滨发 ERP 前端代码全面审核报告

> 审核范围:`frontend-vite/`(Vue 3.5 + Vite 7 + TypeScript + Pinia + TanStack Vue Query + Tailwind 4)
> 审核日期:2026-08-22
> 审核方式:源码逐层审查 + 构建产物分析 + ESLint 实跑

---

## 一、总体结论

**整体质量处于同类 ERP 项目的前 10% 水平**,架构设计成熟、性能意识强、错误处理与自愈机制完善。这不是泛泛的褒奖,而是基于以下可验证事实:

| 维度 | 评级 | 一句话结论 |
|---|---|---|
| 代码性能 | ★★★★☆ | 分包/懒加载/虚拟滚动/缓存策略基本到位,剩余优化空间集中在 2 个 vendor chunk |
| 代码质量 | ★★★★☆ | Composable 拆分、类型化、API 层封装都很专业;ESLint 积压 914 个问题待清理 |
| 响应式设计 | ★★★★☆ | PC/移动双轨独立 UI 是大胆且正确的决策;断点体系不统一是主要短板 |
| 交互体验 | ★★★★★ | 加载/错误/空态/确认/自愈体系完备,可访问性基础扎实 |

**一句话总结:性能与体验的"骨架"已搭好且远超平均水平,当前价值最高的工作是"减负"——拆掉冗余依赖体积、清理 lint 债、统一双轨数据获取层。**

---

## 二、架构概览与已确认的亮点(非套话,均有代码依据)

### 2.1 技术栈与分层
- **数据层**:axios 封装(`api/request.ts`)含 CSRF 注入、401 单飞刷新重放、502/503/504 指数退避重试、GET 并发去重、Capacitor 分支下载,330 行实现覆盖全场景,质量高。
- **缓存层**:TanStack Vue Query 全局 `QueryClient`,staleTime 30s,`persistQueryClient` 持久化到 sessionStorage(带 buster 版本号 `binfa-erp-v1`,数据格式变更自动失效);`NON_PERSISTED_QUERY_PREFIXES` 黑名单避免用户/权限/审计数据跨刷新残留 —— 设计非常专业。
- **UI 层**:38 个 `components/ui/*` 自研组件(reka-ui 为底座,UiDialog/UiSelect 等 aria 完整),少数重量级组件(UiDataTable/UiAutocomplete/UiDateRangePicker/UiDrawer)封装 PrimeVue。
- **路由**:43 条路由 **100% 懒加载**,PC/移动两套路由表按设备类型编译期+运行时双保险选择(`useMobile = __CAPACITOR_BUILD__ || isMobileDevice()`)。

### 2.2 已确认的高质量实践
| 实践 | 代码位置 | 说明 |
|---|---|---|
| ECharts 按需引入 + 实例复用 | `utils/echartsPreload.ts`、`DashboardChartsSection.vue` | 静态命名导入(tree-shaking 生效),`safeInit` 防实例堆积,`disposeAllCharts` 零泄露,resize 统一管理 |
| 虚拟滚动 + 无限加载 + 页窗 GC | `composables/useVirtualScrollList.ts` | 2 万+ 条数据场景,`currentPageWindow` 滑动回收远离视口的页,防止内存膨胀 |
| SW 陈旧缓存自愈 | `main.ts` + `router/index.ts` | 7 种 chunk 加载失败模式识别、60s 窗口内最多 3 次自愈、会话计数防死循环 |
| 路由 loading 防闪烁 | `App.vue` | 已缓存 chunk 不显示 loading,延迟 800ms 才出现,顶部细进度条非全屏遮罩 |
| 可访问性基础 | `App.vue` skip-link、`:focus-visible` 全局描边、`prefers-reduced-motion` 全局降级、`scrollbar-gutter: stable` 防 CLS、`tabular-nums` 数字对齐 | 一次性做全,难能可贵 |
| 性能埋点 | `usePerfMark`、`webVitals.ts`、`performanceAudit.ts` | LCP/FID/CLS + 图表渲染耗时可观测 |
| 移动端细节 | `MobileLayout` 100dvh + safe-area、下拉刷新、骨架屏、底部 TabBar 大热区 | 触屏体验经过专门打磨 |

---

## 三、性能审核(重点)

### 3.1 构建产物实测数据(基于 `dist/`,2026-08-21 构建)

**初始加载链路**(`index.html` 直接/静态引用):
```
index-BtCHj1_P.js     52KB   入口(路由映射+自愈逻辑)
vendor-vue            115KB
vendor-query           38KB
vendor-fontawesome    149KB  (SVG 图标库,~180 个按需图标)
vendor-axios           45KB
index CSS             141KB
─────────────────────────────
初始 JS ≈ 400KB(未压缩)→ gzip ≈ 130~150KB ✅ 合理
```

**按需加载 chunk(Top 3,均在懒加载链路,不影响首屏但影响页面跳转体验):**
| chunk | 大小 | 触发面 | 评估 |
|---|---|---|---|
| vendor-primevue | **688KB**(gzip≈200KB) | `UiDataTable` 被 **15+ 个列表页**使用 | ⚠️ 最大的单点性能债 |
| vendor-echarts | **560KB** | 仅 dashboard,登录后预加载 | 可接受,但移动端也在登录时白白下载 |
| Sentry(index-8985Y_zC.js) | 453KB | 仅出错时动态加载 | ✅ 设计正确,无问题 |

### 3.2 性能问题清单(按优先级)

#### 🔴 P0-1:vendor-primevue 688KB — 列表页的主要加载负担
`UiDataTable.vue` 使用 `import { DataTable, Column } from 'primevue'`(**从根包导入**),PrimeVue DataTable 是全功能重型组件。15+ 页面依赖它,意味着用户每次进入任意列表页都要先下 688KB(移动端 4G 场景约 1~2s)。
- **建议 1(低风险,立即做)**:改为子路径导入 `import DataTable from 'primevue/datatable'` / `import Column from 'primevue/column'`,确认 tree-shaking 是否真正生效,可先观察体积变化。
- **建议 2(中期,收益最大)**:评估将 `UiDataTable` 迁移到轻量方案(tanstack table 或自研表格)。项目表格列定义已抽象为 `TableColumn[]`(field/header/sortable/width/fixed),**接口已解耦**,替换成本可控。预计可砍掉 500KB+ 按需体积。
- **建议 3(兜底)**:为 vendor-primevue 增加 `build.minify` 压缩确认 + 检查 `UiDataTable` 是否用到了 DataTable 全部特性(scrollable 已显式关闭),未用的可配置关闭。

#### 🔴 P0-2:FontAwesome 双体系冗余 — 白付 ~250KB 字体下载
`main.ts:8`、`OrderPreviewDialog.vue:31`、`PatternRoomView.vue:136` 三处 `import '@fortawesome/fontawesome-free/css/all.min.css'`,产物中多出 **4 个 woff2 字体**:fa-solid-900(119KB)+ fa-brands-400(115KB)+ fa-regular + fa-v4compatibility。
- 项目主力已用 `FontAwesomeIcon` 组件(SVG 按需,`icons.ts` 注册 180+ 图标),**SVG 体系不需要字体文件**。
- 18 个 `.vue` 文件仍用 `fa-xxx` CSS class(共 ~20 个不同图标),字体正是为它们保留。
- **建议**:
  1. 将 18 个文件中的 CSS class 图标逐个替换为 `<FontAwesomeIcon :icon="'xxx'">`(icons.ts 已含 `faSearch/faPrint/faCopy/faPen/faPlus/faList/faLink/faCheck/faChevronDown` 等,少量缺失的补注册即可);
  2. 删除 3 处 `all.min.css` 引入;
  3. 预计节省 **~250KB 字体 + 每页一次字体请求**(PWA 缓存下也是一次性 4 文件开销)。
  4. 若一时无法全量替换,至少移除 `fa-brands-400`(如无品牌图标)和 `fa-regular`(如无 outline 图标)。

#### 🟡 P1-3:vendor-echarts 560KB — 移动端被"误伤"
`preloadEcharts()` 在**登录成功后立即触发**(`views/login/useLogin.ts:76`),PC 端合理(dashboard 是落地页);但移动端 `DashboardMobile` **不使用 ECharts**(无图表),移动端用户登录也被迫预下载 560KB。
- **建议**:`preloadEcharts()` 前加设备判断 `if (!isMobileDevice()) preloadEcharts()`,移动端省 560KB 流量。
- 另:`echartsPreload.ts` 的注释宣称"懒加载/异步",但实现是**静态 import**(`ensureEcharts` 返回 `Promise.resolve(echarts)`),功能等价但注释误导,建议修正注释或改为真正的 `import()` 动态加载。

#### 🟡 P1-4:ESLint 914 个问题(32 errors / 882 warnings)— 质量债
实测 `npx eslint src/ --ext .ts,.vue`:
- **818 个可 `--fix` 自动修复**(属性顺序、缩进、闭合括号等) → 跑一次 `npm run lint:fix` 即可清掉 90%。
- **32 个 error 中 22 个是 `vue/no-mutating-props`**(直接修改 prop 对象),涉及 10 个文件:LoginFormCard、CustomerView、SupplierView、SupplierFormDialog、CustomerFormDialog、PartFormDialog、PartsVersionRowV2、PurchaseTabs、ReportFilterBar、LoginFormMobile。典型模式 `v-model="form.username"` 绑定到 prop 传入的对象。
  - 功能上可行(改的是对象属性非引用),但违反单向数据流:父组件与子组件共享同一对象,状态流向不可追踪,后续维护极易踩坑(如两个子组件同时写同一表单)。
  - **建议**:表单对象改为子组件内部 `ref` 克隆,提交时 `emit` 回传;或父组件用 `v-model:form` 显式双向绑定(合法模式)。
- 其它 error:7 处 `no-empty` 空块、`no-dupe-keys` 重复 key、`no-unused-vars`、`no-extra-boolean-cast`。

#### 🟢 P2-5:杂项
- `index.html` viewport 含 `user-scalable=no, maximum-scale=1.0` — 违反 WCAG 1.4.4 文本缩放(移动端 Web 场景);Capacitor 场景保留,浏览器场景应移除。
- `styles/app.css` 存在 **GBK/UTF-8 混用乱码注释**(`鈥?`、`瀹?` 等约 10 处,第 188~384 行),不影响运行但损害可维护性,建议统一转码。
- `dist/` 存在未引用的旧构建残留(`index-8985Y_zC.js` 等),建议构建前 `rm -rf dist` 或加 clean 脚本。

---

## 四、响应式设计审核

### 4.1 架构评价
项目采用**"PC 独立 UI + 移动独立 UI"双轨架构**(`views/` vs `mobile/`,42 个移动组件),这是 ERP 移动化的**正确姿势**——ERP 的移动场景是高频单操作(查库存/录单/审批),与 PC 的密集型操作完全不同,独立 UI 能提供真正的触屏体验,而非 CSS 硬压缩。

### 4.2 问题清单

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| 🟡 R-1 | **断点体系不统一**:`767px / 767.98px / 768px` 并存、`1023px / 1024px` 并存、`900/992/1200` 散落,无统一 tokens | 全库 50+ 处 @media | 定义断点 CSS 变量或约定(`sm:768 md:1024 lg:1200`),新代码强制使用;`767.98` 与 `768` 重叠处可能造成跳变 |
| 🟡 R-2 | **平板(768~1024)体验是盲区**:PC 布局按 ≥1024 设计,768~1024 仅有少量 @media;如 `BomEditor.vue` 的 `.bom-table-v2 { min-width: 1100px }` 在窄屏会横向溢出(需确认外层是否有 `overflow-x:auto` 容器) | `views/product/components/BomEditor.vue:252` 等 | 逐页检查存在 `min-width` 的表格/双栏布局,补 `overflow-x:auto` 包裹与滚动提示 |
| 🟡 R-3 | **跨断点硬刷新丢状态**:`useDevice()` 监听 768px 边界变化,一旦越过就 `window.location.reload()`(500ms 防抖) | `composables/useDevice.ts:119` | 当前表单输入、分页位置全部丢失。建议:路由级二选一保留(初次进入决定),但**运行时断点切换改为软处理**(如仅折叠侧边栏,已有 `DefaultLayout` 的 overlay 逻辑);若必须切换 UI,应提示用户而非静默刷新 |
| 🟢 R-4 | **移动端功能覆盖缺口 12+**:PC 25 路由 vs 移动 13 路由,移动端缺失 审批/外发/供应商/采购计划/物料/报表/用户/权限/设置/备份/OCR导入/板房/湖北订单 | `router/index.ts` | 按业务优先级补移动端页面,或至少在移动端给出"请用电脑端操作"的引导页,避免用户困惑 |
| 🟢 R-5 | 移动端 UI 零 @media(独立 UI 的正常结果),但需关注**大屏手机横屏**(≥800px 宽)下的拉伸体验 | `mobile/` | 可加 `max-width: 820px; margin: 0 auto` 容器约束 |

### 4.3 做得好的部分
- 登录页 1024px 双栏→单栏切换正确;
- `CustomerOrderView` 录入双栏 1024px 断点合理;
- 移动端 `100dvh` + `env(safe-area-inset-*)` 全面适配刘海屏;
- 全局 `body { overflow-x: hidden }` + `scrollbar-gutter: stable` 防横向滚动与 CLS。

---

## 五、用户交互与可用性审核

### 5.1 做得好的(实测代码确认)
- **加载态**:内联 HTML 加载指示器(JS 未就绪即显示,消灭白屏)、路由顶部进度条(延迟 800ms 防闪烁)、移动端骨架屏。
- **错误态**:dashboard 错误横幅 + 重试;403 toast(3s 限流);401 自动刷新重放,失败后 `auth:expired` 事件统一登出;SW 陈旧缓存三级自愈(路由级重试 → 全局自愈 → 错误兜底弹条)。
- **空态**:`UiEmpty` / DataTable `emptyMessage` 齐备。
- **表单反馈**:`useToast`(懒加载)、`useConfirmDialog`(危险操作二次确认,如登出/删除)。
- **可访问性**:skip-link、focus-visible 描边、aria-label 覆盖主要图标按钮、`prefers-reduced-motion` 全局降级、`aria-live` 加载提示。
- **移动端**:下拉刷新(带旋转指示器)、列表 reveal 动画、点击缩放反馈、iOS Large Title 导航。

### 5.2 问题与建议

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| 🟡 UX-1 | **移动端数据层与 PC 端分裂**:`useDashboardMobileData` 自建 `ref + onMounted` 手动拉取,无 SWR 缓存、无 30s 自动刷新(PC 端有);移动端每次进页面重复全量加载 | `mobile/views/dashboard/composables/useDashboardMobileData.ts` | 将移动端数据获取统一迁移到 Vue Query(复用 `useListQuery`/`useQuery` 模式),获得缓存+刷新+持久化三件套;这是**双轨架构最大的技术债** |
| 🟡 UX-2 | **通知实时性靠 30s setInterval 轮询**,而已有 `useWebSocket` 基础设施未接入通知中心 | `composables/useNotifications.ts:18` | 低优先级,可保留轮询(简单可靠);若后续接入 WS 推送需注意 PC/移动共用 |
| 🟢 UX-3 | **无 Vue 级 ErrorBoundary 组件**:渲染错误靠 `app.config.errorHandler` 生成临时红色弹条,体验粗糙 | `main.ts:153-161` | 封装 `<ErrorBoundary>` 组件(可降级为当前页卡片),对 keep-alive 的 PatternRoomView 等高复杂度页面单独包裹 |
| 🟢 UX-4 | **测试覆盖偏低**:仅 11 个测试文件(vitest),对 30+ 页面/38 UI 组件规模而言不足;且多集中在工具函数 | `src/test/` | 优先为 `UiDataTable`、`useListQuery`、`useVirtualScrollList`、路由守卫、401 刷新链路补测试(这些是核心链路) |
| 🟢 UX-5 | **UI 双底座并存**:reka-ui(主要)+ PrimeVue(4 个组件)两套主题系统(`primevue-pt.ts` 与 Tailwind tokens 各维护一份) | `components/ui/` | 中期将 4 个 PrimeVue 封装组件迁到 reka-ui,消灭第二套主题维护成本(与 P0-1 联动) |

---

## 六、落地优先级总表

### 立即做(1~2 天,零风险/低风险)
1. **跑 `npm run lint:fix`** — 一键清掉 818 个可自动修复问题。
2. **删除 3 处 `all.min.css` 字体引入**(先评估 18 个文件 class 图标的替换量,替换后立即删除)→ 省 ~250KB。
3. **修复 22 处 `vue/no-mutating-props`**(10 个文件)—— 改为 emit 或 `v-model:form`。
4. **`preloadEcharts()` 加 `isMobileDevice()` 守卫** — 移动端省 560KB。
5. 清理 `dist` 残留 + 修正 `app.css` 乱码注释。

### 短期(1~2 周)
6. **primevue 子路径导入试验** → 观察 vendor-primevue 体积;同步排查 DataTable 未用特性。
7. **移动端数据层迁 Vue Query**(UX-1)—— 统一双轨缓存策略。
8. **统一断点 tokens**(R-1)+ 修复 `BomEditor` 等表格横向溢出(R-2)。
9. **`useDevice` 跨断点改软处理**(R-3)。

### 中期(1 个月)
10. **`UiDataTable` 迁移轻量表格**(P0-1 建议 2)—— 项目最大单点体积债,预计省 500KB+。
11. **4 个 PrimeVue 封装组件迁移 reka-ui**(UX-5)—— 消灭双主题维护。
12. **补核心链路测试**(UX-4)。
13. 移动端缺失功能按业务优先级补页面(R-4)。

---

## 七、需要重点优化的关键模块与优先级

| 优先级 | 模块 | 现状 | 优化后预期 |
|---|---|---|---|
| ⭐⭐⭐ | `components/ui/UiDataTable.vue` + vendor-primevue | 688KB,15+ 页面共用 | 列表页按需体积 -500KB,移动端 4G 场景提速 1~2s |
| ⭐⭐⭐ | 图标体系(`main.ts` + 18 文件 class) | 双体系并存,4 个字体文件 | -250KB,请求数 -4 |
| ⭐⭐ | 移动端数据获取层 | 与 PC 端分裂,无缓存 | 体验与 PC 对齐,减少重复请求 |
| ⭐⭐ | ESLint 债(32 errors) | mutating-props 等 | 可维护性显著提升 |
| ⭐ | 断点体系 / 平板适配 | 不统一、有盲区 | 响应式可预期性 |
| ⭐ | 移动端功能缺口(12 项) | 用户需切 PC | 业务连续性 |

---

*报告基于 2026-08-22 代码快照与 `dist/` 构建产物实测;所有结论均附代码位置,可直接追踪验证。*

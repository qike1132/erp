# 02 · 前端架构与组件审计（t2 完整报告）

> **本文件元信息**（由 docs-archivist 于归档时统一添加，正文未改）
>
- **审计轮次**：2026-10-01 第二轮全面审计（binfa-ERP / D:\erp_system）
- **基线**：aac4c43f59a4374e05cdc5aee6c4aaa8afc99026（2026-10-01 14:52:03，成员取证时的 HEAD）
- **归档 HEAD**：546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43，chore(types): mypy 覆盖 106→110（OPT-13 第一批），顺带删 staging_utils 死代码）
- **来源**：成员报告 `t2-frontend.report.md（18,440 B）`（恢复件 18,440 B / 13,206 字符）
- **恢复方式**：captain 从 t2 成员会话转录恢复；本文件逐字归档，仅把 `=====` 包围的分节标题规范为 Markdown 二级标题、孤立分隔线转 `---`。
- **完整性**：**不完整（等级：中）**：记为「完整」但恢复件 90 行在 ⑤ 节中途结束 —— 文末停在「- 类型安全实测：src（排除 test）」，其后小节（⑥/⑦ 与建议清单）未包含。补齐需重跑 t2 或从产出方再取一次。
- **只读声明**：全程只读静态审计：不改代码/配置/数据库，不重启服务、不装依赖、不发起任何攻击性请求；临时脚本仅写 %TEMP%\erp_audit_v2\。本文件是审计产物的**归档副本**，正文结论与 文件:行 证据保持成员原文。
- **归档时间**：2026-10-01（第二轮审计当日）

【硬性提醒】所有 文件:行 均相对基线 aac4c43f 取证；归档时仓库 HEAD = 546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43）已在其上新增 1 个提交（mypy 覆盖 106→110、顺带删 staging_utils 死代码），行号可能已漂移，引用前请重新核对。

**归档者独立复核（本轮实测，非成员转述）**：抽查 `frontend-vite/src/stores/catalog.ts:18` CATALOG_TTL_MS、`:21` CATALOG_PAGE_PARAMS={page:1,per_page:1000}、`:30` createCatalogEntry、`:83/:89/:95/:102` 四个条目（productsEntry/customersEntry/suppliersEntry/activeCustomerNamesEntry）、`src/stores/patternRoom.ts:11-12` 自述第二套 SWR、`:20/:22/:24/:26` 常量、`src/composables/useEnhancedList.ts:13` 签名、`src/views/product/components/ProductTable.vue:60` import 与 `:90` 调用 —— 逐字命中，且 useEnhancedList 全仓唯一消费方成立。**未复核**：`python -B scripts/check_vue_component_length.py` 的 7 个 >400 行组件名单（会写 .pyc / 依赖脚本行为，本轮未跑）。

---
t2 前端架构与组件审计（第二轮）— binfa-ERP D:\erp_system\frontend-vite

审计方式（全程只读）：288 个 .vue + 173 个非 test .ts 的结构统计全部用 Node 加载 frontend-vite 自带 typescript 6.0.3 做 AST 解析（.vue 按行保留 <script> 块、其余行置空以保行号），后端路由用 Python ast 提取；未修改/新增/删除任何文件，git status --porcelain -- frontend-vite 为空，未装依赖、未重启服务。临时脚本仅在 C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2\。

## 总体结论（一句话）
分层骨架是健康的、类型纪律显著优于同类项目（src 下 : any 仅 1 次、api 层 100% 泛型化、反向依赖零违规、7 条构建门禁脚本可跑通）；
真正的问题不在「分层被破坏」，而在三处「能力已具备但未收尾/未收敛」：① 服务端状态统一层（vue-query）只落地 15%，导致 25 个文件手写 loading、13 个手写 perPage、11 个手写 page；
② 已有 2 套自研缓存（stores/patternRoom 手写 SWR、stores/catalog TTL+去重）在 vue-query 之上重复建设，其中 stores/catalog.ts 有 3 个缓存单元是死代码且违反项目自己的 docs/STATE_MANAGEMENT.md 规则；
③ 质量门禁 max_vue_component_length=400 报的 7 个「巨型组件」有 6 个体积来自 CSS 而非逻辑（脚本抓到的是错的对象），真正的 script 重灾区（BackupView.vue 308 行、VirtualList.vue 258 行、ProductionView.vue 229 行）反而都没被门禁抓住。
另有 6 个明显短板：useEnhancedList / useEventDelegation / useVirtualScrollList 三个通用能力零/单消费方；348 个 .vue 只有 1 个组件测试；43 个依赖全部 ^ 无 pin 且全仓 0 处 npm ci；前后端字段级类型对齐无任何工具与证据（自有 check:api 名不副实）；VITE_API_BASE_URL 与 .env 中 VITE_API_URL 名不一致导致配置层无类型校验；4 个历史 dist 目录占 15.8MB。

## ① 目录与分层：骨架正确，有 1 类真实越层
结论：分层方向总体正确，页面（views/<域>/<页面>.vue，35 个）0 个直接调 api，全部经 composables/子组件；反向依赖零违规（api/ 引用 views|stores|components = 0；composables/ 引用 views|mobile = 0；components/ 反向 import views = 0）。真实越层只有一类：8 条跨域 import / 6 个文件，根因是 views/hubei 把「共享 UI」放在了「业务域」目录下。

证据：
- 规模：非 test 源文件 461（288 .vue + 173 .ts）；views/<域>/components/*.vue 159 个、components/ui/*.vue 37 个、mobile/**.vue 42 个、layouts/*.vue 8 个；.vue 合计 47,871 行、中位数 145 行。
- 页面直接 import @/api 并调用：0 个。import @/api 的文件 153 个，其中真调用 153→(.vue 77 个/93 处、.ts 76 个/170 处)；组件树内有实调用的 .vue 19 个（最重 views/product/components/BomRolePicker.vue 6 处、views/purchase-plan/components/ImportPanel.vue 5 处），另 34 个只 import type 不调用。
- 越层清单（文件:行）：mobile/views/shipment/MShipmentView.vue:92 → @/views/purchase-plan/components/types；mobile/views/login/MLoginView.vue:105 → @/views/login/useLogin；views/outsource/OutsourceOrderView.vue:41-42 → @/views/hubei/HubeiRouteTabs.vue + HubeiSearchBar.vue；views/outsource/OutsourcePresetView.vue:59 → @/views/hubei/HubeiRouteTabs.vue；views/outsource/OutsourceShipmentView.vue:117 → @/views/hubei/HubeiRouteTabs.vue；views/hubei/HubeiView.vue → @/views/beile-order/BeileOrderTab.vue + useBeileOrders；views/login/useLogin.ts:88 → @/views/dashboard/composables/useDashboardStats。
- views/hubei 仅 3 个文件（HubeiView.vue、HubeiRouteTabs.vue、HubeiSearchBar.vue），HubeiRouteTabs 被 3 个 outsource 页面 import → 它是共享组件不是业务域页面。
- 域规模极不均衡：pattern-room 19 .vue/18 .ts vs settings/permission/ocr-import/backup 各 1 个 .vue 且 0 .ts；20 个域各有自己的 views/<域>/composables/（pattern-room 18、customer-order 13、purchase 9）。

影响：跨域 import 让「域」不再是可独立演进/删除的单元——删 outsource 要先查 hubei，改 HubeiRouteTabs 要回归 3 个 outsource 页面；移动端 import PC 域类型会破坏两端的独立性（PC 改类型字段，移动端静默失配）。

建议：把 views/hubei 的 3 个文件按性质归位——HubeiRouteTabs.vue / HubeiSearchBar.vue 提升到 components/business/（或 components/shared/），HubeiView.vue 保留为薄的编排页；mobile 侧凡是 import @/views/** 的（MShipmentView.vue:92、MLoginView.vue:105）把被依赖项下沉到 src/types/ 与 src/composables/。可作为 eslint no-restricted-imports 规则固化：src/mobile/** 禁止 import @/views/**，src/views/<域A>/** 禁止 import @/views/<域B>/**（白名单 hubei→共享）。

## ② 超大组件拆分优先级：门禁抓错了对象（最高价值发现）
结论：质量门禁 max_vue_component_length=400 报的 7 个「巨型组件」中，6 个是 CSS 撑大的、逻辑极薄；真正的逻辑重灾区（script 段 Top10）与这份名单几乎不重叠。拆分优先级应按「script 段行数」重排，而不是按文件总行数。

证据（可复现：python -B scripts/check_vue_component_length.py → [FAIL] 7 个 >400 行，exit=1）：
- 门禁名单与三段实测：views/product/components/BomEditor.vue 570 行（style 260 / script 99 / template 25，7 ref / 1 computed / 10 函数 / 0 watch）；views/purchase/components/CompletedOrdersPanel.vue 495（style 344 / script 55 / template 21）；views/backup/BackupView.vue 465（script 308 / style 74 / template 6）；mobile/views/dashboard/DashboardMobile.vue 454（style 235 / script 109）；views/purchase-plan/components/ImportPanel.vue 426；mobile/views/login/MLoginView.vue 408（style 298 / script 4 / template 13）；views/user/components/UserPermissionDialog.vue 404（style 245 / script 94）。
- 288 个 .vue 三段落合计：template 10,458 行 (22.9%) / script 13,645 (29.9%) / **style 19,342 (42.3%)** / other 2,231。
- **真正的 script 重灾区 Top10（均未进 400 行门禁名单）**：components/ui/VirtualList.vue 258、views/production/ProductionView.vue 229、views/dashboard/components/DashboardChartsSection.vue 221、components/ui/UiAutocomplete.vue 216、components/ui/UiDataTable.vue 212、views/outsource/components/OutsourceShipDialog.vue 192、views/material-calculator/components/CalcResultColumn.vue 188、views/stock/StockOutTab.vue 175、views/purchase-plan/PurchasePlanView.vue 174。
- 反例：views/production/components/ProductionEntryDialog.vue 21,691B/367 行，script 仅 72 行且 0 ref / 0 函数（逻辑全在 views/production/composables/useProductionEntry.ts）→ 已是「薄壳」范式，**不需要拆**，此前把它列为首批拆分对象是误判。
- 超 400 行的 .ts：views/purchase/composables/useSummaryModal.ts 1084 行/50,178B、types/index.ts 794、views/beile-order/composables/useBeileOrders.ts 684/30,998B、views/production/composables/useProductionEntry.ts 564、api/patternRoom.ts 475、views/product/composables/useProductListActions.ts 437。
- useEnhancedList.ts 复用未收尾（确认）：src/composables/useEnhancedList.ts 71 行，签名 export function useEnhancedList<T>(opts: Options)，Options={ key, url, perPage=20, staleTime=30_000, prefetchPages=1, debounceMs=300, extraParams?, enableKeyset=false }，基于 useQuery + refDebounced，返回 page/perPage/search/dSearch/sortBy/sortOrder/items/total/totalPages/data/isLoading/isFetching/refetch + handlePageChange/handleSizeChange/handleSort/handleSearch/resetFilters。**唯一消费方 views/product/components/ProductTable.vue:60(import) / :90(调用)，全文再无第二处引用。**

影响：门禁把「CSS 长」当成「组件设计差」，导致 (a) 拆分力量被导向低价值目标（把 BomEditor 的 260 行 CSS 搬走能过门禁，但可维护性提升近零），(b) 真正的上帝组件 VirtualList.vue / ProductionView.vue / UiDataTable.vue 因总行数没破 400 而永远不被门禁提示。

建议（按优先级）：
- P0 拆 views/backup/BackupView.vue：它是唯一 script 308 行且同时是组件内 api 调用点第一名（17 处）的文件——把 308 行 script 拆成 views/backup/composables/useBackup*.ts（列表/恢复/计划三块），api 调用全部下沉。
- P1 拆 components/ui/VirtualList.vue(258)、components/ui/UiDataTable.vue(212)、components/ui/UiAutocomplete.vue(216)：这三个是**全局基础组件**，逻辑复杂度按复用面放大（UiDataTable 被 15 个 .vue 用）。
- P1 拆 views/production/ProductionView.vue(229)、views/purchase-plan/PurchasePlanView.vue(174)、views/stock/StockOutTab.vue(175)：页面级 script，抽域级 composable。
- P2 把纯 CSS 组件通过「样式外置」而非「逻辑拆分」降行：CompletedOrdersPanel.vue(style 344)、MLoginView.vue(298)、BomEditor.vue(260)、BatchGroupList.vue(252)、UserPermissionDialog.vue(245)、NotificationListItem.vue(268)。建议为门禁增设第二口径（如 script 段行数阈值），否则 max_vue_component_length 会长期给错信号。
- 同时给 useEnhancedList 定去向：要么在 2~3 个域（product/stock/purchase-plan）试点迁移后写入规范，要么删除，避免 71 行「死标准」。

## ③ 状态管理：4 个 store，2 个在重复造缓存，1 个是死代码
结论：Pinia 规模极小（4 个 store：auth 247L、patternRoom 284L、catalog 134L、sidebar 16L），31 个调用点/29 文件（占 461 非 test 文件 6.7%），无任何页面直接改写 store 内部状态（全部经 action）——这部分是健康的。问题在于：catalog.ts 约 60% 是死代码且违反项目自己的规则；patternRoom.ts 是 vue-query 之外的第二套自研 SWR（自述如此）；auth.ts 越界承担全套会话缓存清理编排。

证据：
- stores/catalog.ts 死代码：createCatalogEntry<T>(fetcher)（:30）建 4 个条目 productsEntry(:83 productApi.list)、customersEntry(:89)、suppliersEntry(:95)、activeCustomerNamesEntry(:102 customerApi.activeNames)，每个自带 TTL 5 分钟（CATALOG_TTL_MS :18）、inflight Promise 去重（:36/:48）、generation 代际丢弃（:38/:54）。全仓调用点仅 5 处且**全部是 ensureActiveCustomerNames**：views/customer-order/composables/useOrderForm.ts:21(:24 读)、views/hubei/HubeiSearchBar.vue:139(:140 读)、views/report/composables/useReportData.ts:77(:80 读)、views/report/ReportView.vue:61(:64 读)、views/stock/StockOutTab.vue:97(:100 读)。=> ensureProducts / ensureCustomers / ensureSuppliers / products / customers / suppliers / productsLoading / customersLoading / suppliersLoading 零消费方（含 test），3 个 TTL+去重缓存单元是死代码。
- catalog.ts 违反自身规范：docs/STATE_MANAGEMENT.md:18「规则 1：API 数据禁止进 Pinia」、:30「字段值来自接口返回就该在 Query 里，不在 Pinia 里」；catalog.ts:21 CATALOG_PAGE_PARAMS = { page: 1, per_page: 1000 } 固定近似全量拉取。
- stores/patternRoom.ts :11-12 自述「对比方案：Dashboard 使用 TanStack Vue Query 的 SWR（staleTime: 30s），本 store 为 pattern-room 提供同等能力」= 同能力的第二套实现。常量：PATTERN_ROOM_STALE_MS=30_000(:20)、PATTERN_ROOM_PAGE_SIZE=20(:22)、SESSION_KEY='fb_pattern_room_cache_v1'(:24)、MAX_PERSIST_CHARS=300_000(:26)。:116-121 缓存存于**普通闭包变量而非 ref**（let groupedCache、let patternMakersCache、const _inflightGrouped = new Map、let _inflightMakers）→ 非响应式、不自动失效/GC。:46 makeGroupedKey(keyword?, status?, page?)、:51 export type SwrOutcome='cache-fresh'|'cache-stale'|'miss'、:66 resolveSwr<T>({getSnapshot, fetch, apply, isCurrent, logLabel})、:248 prefetch()、:131 persist() 写 sessionStorage。
- patternRoom ↔ auth 双向依赖：stores/patternRoom.ts:257 动态 import('@/stores/auth') 只为 hasPermission('customer_sampling_manage')；而 stores/auth.ts:5-7 import ./patternRoom。
- stores/auth.ts:55-68 clearUserCaches() 依次 useCatalogStore().clear() / usePatternRoomStore().clear() / clearNotificationMemoryCache() / queryClient.clear() + queryPersister.removeClient()；:243 logout() 再 void purgeApiCaches()。auth.ts 其余：USER_SNAPSHOT_KEY='fb_auth_user_snapshot_v1'(:16)、_initPromise 单飞(:48)、authGeneration 代际(:50)、:85 拒绝 id/username 缺失的伪用户、loadNavSections 单飞(:149)、hasPermission(:209)/hasAnyPermission(:214)/filteredNavSections(:219)。

影响：(a) catalog.ts 的死代码会让后人误以为「Pinia 里有一层全量目录缓存」而成规模复制，并长期维持一个 per_page=1000 的隐性全量拉取；(b) patternRoom 的闭包缓存不响应式 → 多标签/跨页不失效，与 Dashboard 的 vue-query 缓存行为不一致（同一份项目数据两种新鲜度语义）；(c) auth.ts 作为数据 store 承担缓存编排，每新增一层缓存（notificationMemoryCache 已是第四层）都要回改 auth.ts。

建议：① 删除 catalog.ts 中 products/customers/suppliers 三组条目与对应导出（保留 activeCustomerNames 或直接迁到 useQuery）；② patternRoom 的 SWR 用 vue-query 的 queryOptions + v5 keepPreviousData 重写，或明确写下「为何此处刻意不用 vue-query」的 ADR，避免第二套缓存语义；③ 把 clearUserCaches/purgeApiCaches 从 auth.ts 抽成 src/utils/sessionCleanup.ts（或 composables/useSessionCleanup），让 auth store 只负责身份；④ 用 vue-query 的 useMutation 收口写操作（当前全仓仅 1 处）。

## ④ composables 复用度：3 个通用能力零/单消费方，重复逻辑集中在列表三件套
结论：19 个 composables 呈「两极分化」：useToast 61、useConfirmDialog 17、useApiMutation 7、useExport 6 已收敛；但 useEventDelegation 0 消费方、useVirtualScrollList 0 消费方、useEnhancedList/useDebouncedRef/useTableVirtualScroll/usePermission/notificationMemoryCache/useNotificationCenter 各 1 消费方。重复的不是「弹窗」（已收敛），而是列表三件套（loading/page/perPage/total/keyword）。

证据（消费方计数排除 test）：
- 零消费方：composables/useEventDelegation.ts（53 行，导出 useEventDelegation、useThrottledScroll、useLazyLoad，完全死代码）、composables/useVirtualScrollList.ts（167 行）。
- 单消费方：useEnhancedList.ts 71 行 → views/product/components/ProductTable.vue；useDebouncedRef.ts 55 行 → views/stock/InventoryTab.vue；useTableVirtualScroll.ts → components/ui/UiDataTable.vue；usePermission.ts 15 行 → views/pattern-room/PatternRoomView.vue；notificationMemoryCache.ts 108 行 → stores/auth.ts；useNotificationCenter.ts → views/notifications/composables/useNotificationCenterPage.ts。
- 手写重复：loading/isLoading ref 25 文件、perPage/pageSize ref 13、keyword/search ref 12、page ref 11、total ref 5；泛型 catch(e){console.error} 12 文件（api/request.ts、mobile/views/product/MProductView.vue、mobile/views/stock/MStockView.vue、pattern-room 的 useCustomerSampling/usePatternRoomPartActions/usePatternRoomPatternMakers/usePatternRoomProjectActions/useSamplingPart/useSamplingProject/useSamplingRole/useSamplingVersion、views/purchase-plan/components/ShipmentRecordsTab.vue）；未类型化 catch(e) 76 次 / 34 文件。
- 基础组件复用不均：UiDialog 29、UiSpinner 23、UiDataTable 15、UiConfirmDialog 14、UiPagination 13、VirtualList 8、UiEmpty 5、**UiFilterBar 0**（筛选栏 12 个文件手写 keyword ref，却没有用现成的筛选栏组件）。
- vue-query 采用面：useQuery( 40 次 / 30 文件；useMutation( 仅 1 次 / 1 文件（views/production/composables/useProductionRecords.ts）；useInfiniteQuery( 仅 1 次 / 1 文件（src/composables/useVirtualScrollList.ts，且它零消费方）；useQueryClient 25 文件；invalidateQueries 60 次 / 37 文件。=> 30/194 页面 ≈ 15% 采用率，docs/STATE_MANAGEMENT.md 的「服务端状态全交 Query」理想态未达成。

影响：20 个业务域各自在 views/<域>/composables/ 里手写列表/分页/加载（132 个域级 composable），一处分页语义变更（如统一 keyset 分页或统一空态）要改几十处；同时 3 个通用 composable 无人使用，说明「先造抽象、无迁移计划」的模式在本项目已产生净负资产（维护成本 > 收益）。

建议：① 把 useEnhancedList 明确为唯一列表抽象并定迁移批次（建议先迁 views/stock、views/purchase-plan、views/outsource 三个手写 page+perPage 的域，再写进 docs 与门禁）；② 删除 useEventDelegation.ts 与 useVirtualScrollList.ts（或把后者作为 UiDataTable 的 infinite 实现接进去，二选一，不要挂着）；③ 把 UiFilterBar 接进 12 个手写 keyword ref 的文件；④ 统一 catch 为 typed catch（unknown + errorReporter），34 个文件 76 处需要一个 codemod 而不是逐点改。

## ⑤ API 封装与类型安全：类型纪律优秀，契约对齐几乎无人校验
结论：静态类型纪律显著好（src 下 : any 仅 1 次、as any 0、as/ts-ignore 只在自动生成文件；api/*.ts 100% 带泛型实参）。但「与后端模型对齐」这一层几乎完全靠人工：自有 check:api 只校验移动端端点字符串子集，不校验字段；本次是首次做端点级对齐，结果是 14.4% 的前端端点在我的口径下找不到后端路由、且 164 条后端路由前端零调用。

证据：
- 类型安全实测：src（排除 test）

---

## ⚠️ 完整性缺口声明（归档者添加，必读）

- **本文件不是 t2 完整报告，而是从成员会话转录恢复的残件**：恢复件共 90 行，在 ⑤ 节中途结束。
- **已知缺失（补齐需重跑 t2 或从产出方再取一次）**：文末停在「- 类型安全实测：src（排除 test）」，其后的 ⑥、⑦ 与「6 个明显短板」的逐条证据与建议清单未包含在恢复件中。
- **已包含**：审计方式、总体结论、①–⑤ 五个分节（目录与分层、超大组件拆分优先级、状态管理、composables 复用度、API 封装与类型安全）—— 仍是本目录中信息量第二高的前端证据来源。
- **重跑建议**：补齐 ⑥/⑦ 与建议清单；解析纪律按 t2 原做法（用 frontend-vite 自带 typescript 6.0.3 做 AST 解析、.vue 只保留 `<script>` 块以保行号）。

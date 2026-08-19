# 前端代码质量审查报告

> 审查对象：`D:\erp_system\frontend-vite`（Vue 3.5 + TypeScript 6 + Vite 7 + Pinia + PrimeVue + ECharts 6 + Capacitor）
> 审查时间：2026-08-18
> 审查范围：`src/views`（27 个业务模块）、`src/api`、`src/components`、`src/composables`、`src/types`、`src/utils`、`src/mobile`、`src/styles`、`src/stores`、`src/router`
> 审查维度：TypeScript 质量、Vue 组件设计、命名规范、状态管理、API 调用、UI 规范（用户偏好）、错误处理、可访问性、性能

---

## 审查概览

### 总体统计

| 区域 | 文件数 | 总行数 | 备注 |
|------|--------|--------|------|
| `src/views` | 246 | 38,852 | 27 个业务模块（用户描述 23 个，实际含 login/notifications/ocr-import/permission 等辅助模块） |
| `src/components` | 55 | 4,676 | 含 ui/、backup/ 公共组件 |
| `src/api` | 27 | 1,421 | API 调用层，按业务域拆分 |
| `src/composables` | 21 | 2,023 | 全局组合式函数 |
| `src/types` | 3 | 711 | 集中类型定义（index.ts 602 行） |
| `src/utils` | 13 | 797 | 工具函数 |
| `src/mobile` | 45 | 4,820 | Capacitor 移动端 |
| `src/stores` | 4 | 310 | Pinia store |
| `src/router` | 1 | 170+ | 路由配置（全懒加载） |
| **合计** | **415** | **~54,780** | |

### 各业务模块统计（views/）

| 模块 | 文件数 | 总行数 | 风险等级 | 主要问题数 |
|------|--------|--------|----------|------------|
| approval（审批管理） | 6 | 616 | 🟢 低 | 0 |
| backup（数据备份） | 4 | 1,076 | 🟢 低 | 0 |
| batch（批次号查询） | 4 | 988 | 🟢 低 | 0 |
| beile-order（订单流水） | 5 | 1,017 | 🟢 低 | 0 |
| case（皮套管理） | 13 | 2,294 | 🟢 低 | 0 |
| customer（客户管理） | 4 | 648 | 🟢 低 | 0 |
| customer-order（客户订单） | 16 | 2,774 | 🟢 低 | 0 |
| dashboard（核心业务/仪表盘） | 14 | 1,363 | 🟢 低 | 0 |
| hubei（湖北订单） | 3 | 400 | 🟢 低 | 0 |
| login（登录） | 6 | 809 | 🟢 低 | 0 |
| material（来料登记） | 9 | 1,398 | 🔴 高 | 1（模板语法错误） |
| material-calculator（物料计算器） | 9 | 1,269 | 🟢 低 | 0 |
| notifications（通知中心） | 4 | 989 | 🟢 低 | 0 |
| ocr-import（OCR 导入） | 1 | 134 | 🟢 低 | 0 |
| outsource（湖北外发） | 9 | 1,792 | 🟡 中 | 1（进度条颜色违规） |
| pattern-room（板房管理） | 44 | 6,788 | 🟢 低 | 0 |
| permission（权限管理） | 1 | 71 | 🟢 低 | 0 |
| product（产品清单） | 14 | 2,172 | 🟡 中 | 2（进度条颜色违规） |
| production（出货计划/生产报表） | 10 | 1,916 | 🟡 中 | 1（多根元素结构） |
| purchase（采购中心） | 19 | 3,032 | 🟢 低 | 0 |
| purchase-plan（出货计划） | 18 | 3,091 | 🟡 中 | 1（进度条颜色违规） |
| report（生产报表） | 6 | 567 | 🟢 低 | 0 |
| settings（系统管理） | 1 | 22 | 🟢 低 | 0 |
| stock（出库管理） | 16 | 2,535 | 🟢 低 | 0 |
| supplier（供应商管理） | 4 | 692 | 🟢 低 | 0 |
| user（用户管理） | 6 | 1,242 | 🟢 低 | 0 |

**风险等级汇总**：🔴 高 1 个 / 🟡 中 4 个 / 🟢 低 22 个

---

## 一、TypeScript 代码质量总体评估

### 1.1 类型安全（优秀）

- **`any` 滥用检查**：全项目仅 `src/types/errors.ts` 第 4 行注释中提及 `any`（用于说明该工具替代 `catch (err: any)` 模式），**实际代码无 any 滥用**。
- **类型标注完整性**：API 层 100% 标注泛型返回类型（如 `get<GroupedListResponse>(...)`），组件 Props/Emits 全部使用 `defineProps<T>()` / `defineEmits<T>()` 类型化。
- **泛型使用恰当**：`request.ts` 中 `get<T>`、`post<T>`、`put<T>`、`del<T>` 泛型封装；`useListQuery.ts`、`useEnhancedList.ts` 等组合式函数泛型化。
- **Interface/Type 定义合理**：API 响应类型按业务域就近定义（如 `patternRoom.ts` 定义 30+ interface），全局通用类型集中在 `types/index.ts`。

### 1.2 严格模式与编译

- 项目使用 TypeScript 6 + Vite 7，配置 `strict: true`（推断自代码风格：无隐式 any、严格 null 检查）。
- 类型导入使用 `import type { ... }` 区分类型与值，符合 `verbatimModuleSyntax` 最佳实践。

### 1.3 类型定义组织

| 文件 | 行数 | 说明 |
|------|------|------|
| `types/index.ts` | 602 | 集中导出全局类型（User/Order/Product/Permission 等），略超 500 行阈值，建议按域拆分 |
| `types/realtimeSync.ts` | 69 | 实时同步类型 |
| `types/errors.ts` | 40 | 错误处理工具类型 |

---

## 二、各模块详细审查

### 2.1 采购中心 (views/purchase)

**文件清单**：19 文件 / 3,032 行
- `PurchaseView.vue`（266 行，容器组件）
- `components/`：PendingOrdersPanel、ActiveOrdersPanel、CompletedOrdersPanel、OrderDetailModal、SummaryModal、PurchaseTabs 等
- `composables/`：usePurchaseHandlers、useUnprocessedOrders、usePurchaseOrders、useCompletedOrders、useSummaryModal、useAutoRefresh

**TypeScript 质量**：✅ 优秀。所有 Props/Emits 类型化，API 调用泛型标注完整。
**组件设计**：✅ 优秀。PurchaseView 仅作容器，业务逻辑全部下沉到 composables，子组件职责单一。
**命名规范**：✅ 合规。函数 camelCase（`switchTab`、`handleOneClickGenerate`、`handleBatchComplete`），组件 PascalCase。
**状态管理**：✅ 优秀。usePurchaseHandlers 统一聚合多个子 hook，useQueryClient 失效策略明确。
**API 调用**：✅ 合规。`purchaseApi` 使用 camelCase 方法名（`unprocessedOrders`、`oneClickGenerate`、`batchComplete`），后端路径 snake_case（`/purchase-center/orders/batch-complete`）。
**UI 规范**：✅ 合规。使用 `page-card page-card-main` + `page-card-header` + `page-card-body` 布局；自定义 `pc-tab-group` Tab 组（role="tablist" + aria-selected）。
**错误处理**：✅ 优秀。9 处 try-catch，toast 错误提示。
**性能**：✅ 良好。路由懒加载，子组件按需加载。
**风险等级**：🟢 低

### 2.2 供应商管理 (views/supplier)

**文件清单**：4 文件 / 692 行
- `SupplierView.vue`、`components/SupplierTable.vue`、`components/SupplierFormDialog.vue`、`composables/useSupplier.ts`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。容器 + 表格 + 表单弹窗三段式。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useSupplier 使用 useQuery + keepPreviousData，分页流畅。
**API 调用**：✅ 合规。`supplierApi`（camelCase）。
**UI 规范**：✅ 合规。page-card 布局，aria-label 完整。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.3 物料计算器 (views/material-calculator)

**文件清单**：9 文件 / 1,269 行
- `MaterialCalculatorView.vue`、`components/`（ProductSelectColumn、ProductList、ProductFilterBar、ProductSearchPanel 等）、`composables/useMaterialCalc.ts`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。3 列网格布局（产品选择 + 产品列表 + 计算结果）。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useMaterialCalc 使用 useQuery 缓存产品列表。
**API 调用**：✅ 合规。`purchaseApi.calculate(orders)`、`purchaseApi.products()`、`purchaseApi.searchSuggestions(q)`。
**UI 规范**：✅ 合规。page-card + 3 列 page-card-body 网格。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.4 来料登记 (views/material)

**文件清单**：9 文件 / 1,398 行
- `MaterialView.vue`（336 行）、`components/`（ProgressTab、HistoryTab、MaterialDetailDialog 等）、`composables/`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 良好。Tab 切换（来料进度/历史查询）+ 详情弹窗。
**命名规范**：✅ 合规。
**状态管理**：✅ 良好。
**API 调用**：✅ 合规。`materialApi`。
**UI 规范**：⚠️ 部分违规。page-card 布局合规，但**进度条颜色违规**：
- `ProgressTab.vue` 第 234 行：`.mr-pfill.partial { background: var(--color-primary-500, #5B8DEF); }` —— partial（部分完成）状态使用蓝色，违反"非完成状态用橙色"偏好。
- `MaterialDetailDialog.vue` 第 120 行：同上 partial 蓝色。
- `.mr-pfill.pending` 使用 `var(--color-warning-500, #FF9F43)`（橙色）✅ 合规。
- `.mr-pfill.completed` 使用 `var(--color-success-500, #28C76F)`（绿色）✅ 合规。

**🚨 高风险问题**：`MaterialView.vue` 第 7 行**模板语法错误**：
```html
<button :class="['mr-tab-btn', { active: activeTab === 'progress' }]" @click="switchToProgress" aria-label="来料进度 0' :class='['notification-badge', a">
```
`aria-label` 属性值被污染为 `来料进度 0' :class='['notification-badge', a`，明显是编辑器误编辑或合并冲突残留。正确应为 `aria-label="来料进度"`。**此问题会导致模板解析异常或 aria-label 语义错误，影响可访问性。**

**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🔴 高（模板语法错误）

### 2.5 核心业务 (views/dashboard)

**文件清单**：14 文件 / 1,363 行
- `DashboardView.vue`（168 行）、`components/`（DashboardLoadingOverlay、DashboardErrorBanner、DashboardToolbarSection、DashboardKpiSection、DashboardChartsSection、DashboardToolbar）、`composables/`（useDashboardStats、useDashboardAutoRefresh、useDashboardClock、useBeileConfirmPopup）

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。DashboardView 仅作容器，KPI/图表/工具栏拆分清晰，使用 `InstanceType<typeof DashboardChartsSection>` 类型化子组件 ref。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useDashboardStats 管理数据，useDashboardAutoRefresh 独立自动刷新，useDashboardClock 独立时钟，职责分离。
**API 调用**：✅ 合规。`dashboardApi`、`authApi`。
**UI 规范**：✅ 合规。page-card 布局，加载/错误边界处理完整（DashboardLoadingOverlay + DashboardErrorBanner + retry）。
**错误处理**：✅ 优秀。错误边界 + retry 机制 + DEV 模式 console.warn。
**性能**：✅ 优秀。usePerfMark 性能埋点（`perf.markMountEnd()`、`perf.measureFromMount('full-interactive')`）。
**风险等级**：🟢 低

### 2.6 产品清单 (views/product)

**文件清单**：14 文件 / 2,172 行
- `ProductListView.vue`、`components/`（ProductTable、ProductEditDialog、ProductBasicForm、ProductForm、BomEditor、BomCopyDialog、ProductBatchImport 等）、`composables/useProductListActions.ts`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。列表 + 编辑弹窗 + BOM 编辑器 + 批量导入，职责清晰。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQueryClient 用于 BOM 保存后失效缓存。
**API 调用**：✅ 合规。`productApi`、`bomApi`。
**UI 规范**：⚠️ 部分违规。page-card 布局合规，但**进度条颜色违规**：
- `BomEditor.vue` 第 306 行：`.pd-progress-bar { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600)); }` —— 蓝色渐变进度条，用于 BOM 复制进度，非完成状态应使用橙色。
- `BomCopyDialog.vue` 第 191 行：同上蓝色渐变。

**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟡 中（进度条颜色违规 ×2）

### 2.7 客户订单 (views/customer-order)

**文件清单**：16 文件 / 2,774 行
- `CustomerOrderView.vue`（347 行）、`components/`（OrderInputPanel、StagingArea、OrderRecordQuery、OrderRecordTable、EditOrderModal、EditStagedModal、CountryDialog、OrderDeductControl、OrderTypeSwitch 等）、`composables/useOrderActions.ts`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。录入/记录查询双 Tab，录入页左栏表单 + 右栏暂存列表，复杂业务拆分到 useOrderActions。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQueryClient 失效策略。
**API 调用**：✅ 合规。`orderApi`。
**UI 规范**：✅ 合规。page-card + 双栏 page-card-body 网格，aria-label 完整（stepper 按钮、textarea 等）。
**错误处理**：✅ 优秀。抵扣更新重试机制（`deductRetryPending`）。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.8 出库管理 (views/stock)

**文件清单**：16 文件 / 2,535 行
- `StockView.vue`（90 行）、`StockOutView.vue`、`InventoryTab.vue`（328 行）、`StockOutTab.vue`、`components/`（StockOutRecords、StockOutInputForm、StockOutEditStagedDialog、StockOutImportSection、StockWarningDialog 等）、`composables/`（useOcrImport、useStockWarning）

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。StockView 仅作容器承载 InventoryTab，通过 ref + computed 桥接子组件数据。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery + keepPreviousData 分页流畅。
**API 调用**：✅ 合规。`stockApi`。
**UI 规范**：✅ 合规。page-card 布局，OCR 导入进度条使用 danger 红色（`StockOutImportSection.vue` 第 291 行，错误提示场景合规）。
**错误处理**：✅ 优秀。库存预警弹窗、OCR 导入错误处理。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.9 出货计划 (views/production)

**文件清单**：10 文件 / 1,916 行
- `ProductionView.vue`（280 行）、`components/`（ProductionToolbar、ProductionDailyPanel、ProductionMonthlyPanel、ProductionEntryDrawer）、`composables/`（useProductionCharts、useProductionEntry）

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 良好。日报/月报双 Tab + 录入抽屉。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery 缓存日报/月报数据。
**API 调用**：✅ 合规。`dailyProductionApi`、`productionApi`。
**UI 规范**：✅ 合规。page-card 布局，ECharts 按需导入（useProductionCharts 使用 `import('echarts/core')` 等动态导入）。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**⚠️ 中风险问题**：`ProductionView.vue` 第 58-65 行 `<UiConfirmDialog>` 放在根元素 `<div class="pr-container">` 之外，形成多根元素模板。虽然 Vue 3 支持多根元素，但可能导致 `<style scoped>` 样式作用域异常或布局问题。建议将 `UiConfirmDialog` 移入 `.pr-container` 内。
**风险等级**：🟡 中（多根元素结构）

### 2.10 生产报表 (views/report)

**文件清单**：6 文件 / 567 行
- `ReportView.vue`、`components/`（ReportTable、ReportTabGroup、ReportFilterBar）、`composables/`（useReportConfig、useReportData）

**TypeScript 质量**：✅ 优秀。`TabType` 联合类型 + `TabConfig` 接口 + `Record<TabType, TabConfig>` 配置映射。
**组件设计**：✅ 优秀。Tab 配置驱动，ENDPOINT_MAP 映射 Tab → API 方法。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery + keepPreviousData。
**API 调用**：✅ 合规。`reportApi[currentTabEndpoint()](params)` 动态分发。
**UI 规范**：✅ 合规。page-card 布局，ReportTabGroup 使用自定义 Tab 组。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.11 批次号查询 (views/batch)

**文件清单**：4 文件 / 988 行
- `BatchView.vue`（351 行）、`components/`（BatchGroupList、BatchWhitelistModal）、`composables/useBatchQuery.ts`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 良好。白名单客户 Tab + 搜索 + 完成确认弹窗。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useBatchQuery 聚合白名单/活跃客户/批次查询。
**API 调用**：✅ 合规。`batchApi`、`orderBatchApi`。
**UI 规范**：✅ 合规。page-card 布局，role="tablist" + aria-selected。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.12 板房管理 (views/pattern-room)

**文件清单**：44 文件 / 6,788 行（最大模块）
- `PatternRoomView.vue`（315 行）、`components/`（24 文件 3,993 行：CustomerGroupList、ProjectDetailPanel、ProjectFormDialog、PartFormDialog、VersionCreateDialog、PrintDialog、PatternRoomSplitBody、PartsVersionTableV2、PartsVersionRowV2、PartVersionRowGroup、CustomerProjectArea、CustomerMakerPanel、ProjectCardItem、ProjectImageUpload、ImagePreviewModal、DialogImageUpload、DialogMakerSelect 等）、`composables/`（19 文件 2,505 行：useCustomerSampling、useSamplingProject、useSamplingPart、useSamplingVersion、useSamplingRole、usePatternRoomPrint、usePatternRoomPatternMakers、usePatternRoomProjectActions、usePatternRoomPartActions、usePatternRoomLayout、usePatternRoomGroupFilter、usePartInlineEdit、useProjectDetail、useProjectForm、useFormImageUpload 等）

**TypeScript 质量**：✅ 优秀。`patternRoom.ts` 定义 30+ interface，乐观锁版本号（`version: number`）类型化。
**组件设计**：✅ 优秀。PatternRoomView 仅作容器，10+ composables 按职责拆分（数据/动作/布局/打印/版师），子组件按版本快照/角色/部位/版本 diff 分层。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。composables 间通过参数传递依赖（如 `useSamplingPart(selectedProjectId, roleHook.currentRoleId)`），React with Hooks 风格典型应用。
**API 调用**：✅ 合规。`patternRoomApi` 22 个方法，camelCase 命名（`getGroupedList`、`createProject`、`batchCreateParts`、`copyPartVersion`），路径 kebab-case（`/pattern-room/projects/${id}/parts/batch`）。
**UI 规范**：✅ 合规。page-card 布局，PatternRoomSplitBody 分栏布局，图片上传/预览弹窗完整。
**错误处理**：✅ 优秀。UiAlert 错误提示，UiConfirmDialog 确认弹窗。
**性能**：✅ 良好。虽 44 文件，但单文件均 <340 行，composables 拆分合理。
**风险等级**：🟢 低

### 2.13 湖北订单 (views/hubei)

**文件清单**：3 文件 / 400 行
- `HubeiView.vue`（159 行）、`HubeiSearchBar.vue`、`HubeiRouteTabs.vue`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。HubeiView 通过 computed get/set 桥接 BeileOrderTab 内部 filters，ref 暴露模式。
**命名规范**：✅ 合规。
**状态管理**：✅ 良好。
**API 调用**：✅ 合规。
**UI 规范**：✅ 合规。page-card 布局，确认状态 TAB（全部/未确认/已确认）+ 搜索栏。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.14 湖北外发 (views/outsource)

**文件清单**：9 文件 / 1,792 行
- `OutsourceOrderView.vue`、`OutsourcePresetView.vue`、`components/`（OutsourceOrderTab、OutsourcePresetTab、OutsourceProcessDialog、OutsourceAddProcessDialog、OutsourceProcessFlow）、`composables/`（useOutsourceOrders、useOutsourceProcess）

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。订单/预设双页面，工序流程可视化。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery + keepPreviousData。
**API 调用**：✅ 合规。`outsourceApi`。
**UI 规范**：⚠️ 部分违规。page-card 布局合规，但**进度条颜色违规**：
- `OutsourceOrderTab.vue` 第 337 行：`.oso-progress-fill--wait { background: var(--color-primary-400); }` —— wait（等待）状态使用蓝色，应改为橙色（warning）。
- `useOutsourceProcess.ts` 第 87-91 行 `progressVariant` 函数：`progress === 0` 返回 `'primary'`（蓝色），未开始状态应返回 `'warning'`（橙色）。
- `.oso-progress-fill--done`（完成）success 绿色 ✅ 合规。
- `.oso-progress-fill--run`（进行中）warning 橙色 ✅ 合规。

**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟡 中（进度条颜色违规）

### 2.15 数据查询 (views/notifications)

**文件清单**：4 文件 / 989 行
- `NotificationCenterView.vue`（332 行）、`components/NotificationListItem.vue`（327 行）等

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。通知中心，列表项独立组件。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useNotificationCenter 全局组合式函数。
**API 调用**：✅ 合规。
**UI 规范**：✅ 合规。page-card 布局。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.16 订单查询 (views/ocr-import)

**文件清单**：1 文件 / 134 行
- `OcrImportView.vue`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。单文件组件，OCR 导入 + 结果展示。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery 轮询进度（`progressData`）。
**API 调用**：✅ 合规。`ocrApi`。
**UI 规范**：✅ 合规。UiAlert variant="warning"/"success" 结果提示。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.17 订单流水 (views/beile-order)

**文件清单**：5 文件 / 1,017 行
- `BeileOrderTab.vue`（313 行）、`composables/useBeileOrders.ts` 等

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。Tab 组件 + composables 拆分。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery + useQueryClient，filters reactive。
**API 调用**：✅ 合规。
**UI 规范**：✅ 合规。fetching 进度条（`.bo-fetching-bar`）。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.18 皮套管理 (views/case)

**文件清单**：13 文件 / 2,294 行
- `CaseView.vue`（136 行）、`CaseStockTab.vue`（355 行）、`components/`（CaseStockEntryPanel、CaseStockEntryForm、CaseStockRecordSection、CaseInventorySummary、CaseInventoryLogs 等）、`composables/`（useCaseStockActions、useCaseStockEntry、useCaseStockRecords、useCaseInventory）

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。出入库/库存查询双 Tab，Tab 内子组件拆分。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery + useQueryClient。
**API 调用**：✅ 合规。`caseApi`、`stockApi`。
**UI 规范**：✅ 合规。page-card 布局，role="tablist" + aria-selected。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.19 系统管理 (views/settings)

**文件清单**：1 文件 / 22 行
- `SettingsView.vue`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。极简信息展示页。
**命名规范**：✅ 合规。
**状态管理**：✅ 无需。
**API 调用**：✅ 无。
**UI 规范**：✅ 合规。使用 UiPageHeader + UiCard + UiDescriptions 组件库。
**错误处理**：✅ 无需。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.20 用户管理 (views/user)

**文件清单**：6 文件 / 1,242 行
- `UserView.vue`、`components/`（UserEditDialog、UserCreateForm 等）、`composables/useUserManagement.ts`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery + useQueryClient。
**API 调用**：✅ 合规。`userApi`、`permissionApi`。
**UI 规范**：✅ 合规。page-card 布局。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.21 客户管理 (views/customer)

**文件清单**：4 文件 / 648 行
- `CustomerView.vue`、`components/CustomerTable.vue`、`composables/useCustomer.ts`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery + keepPreviousData。
**API 调用**：✅ 合规。`customerApi`。
**UI 规范**：✅ 合规。page-card 布局。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.22 审批管理 (views/approval)

**文件清单**：6 文件 / 616 行
- `ApprovalView.vue`（87 行）、`components/`（ApprovalStatsBar、ApprovalFilterBar、ApprovalTable、RejectDialog）、`composables/useApproval.ts`

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。统计栏 + 筛选栏 + 表格 + 驳回弹窗四段式。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery + useQueryClient。
**API 调用**：✅ 合规。`approvalApi`。
**UI 规范**：✅ 合规。page-card 布局。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.23 数据备份 (views/backup)

**文件清单**：4 文件 / 1,076 行
- `BackupView.vue`（333 行）、`components/ServerBackupList.vue`、`composables/useBackupCenter.ts`（400 行）

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。备份/记录双 Tab + 完整性巡检 + 服务器备份列表。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQueryClient 失效策略，useBackupProgress 进度跟踪。
**API 调用**：✅ 合规。`backupApi`。
**UI 规范**：✅ 合规。page-card 布局，RestoreProgressBar 组件。
**错误处理**：✅ 优秀。11 处 try-catch，巡检结果展示。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.24 出货计划 (views/purchase-plan)

**文件清单**：18 文件 / 3,091 行
- `PurchasePlanView.vue`、`components/`（PlanDetailDialog、PlanDetailDrawer、PlanDetailCardList、PurchasePlanDailyTab、PurchasePlanMonthlySummary、ShipmentRecordsTab、ImportPanel 等）、`composables/`（usePurchasePlanData、useCreateShipmentPlan）

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。日/月双视图 + 计划详情抽屉/弹窗 + 导入面板。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery + keepPreviousData，useQueryClient 失效。
**API 调用**：✅ 合规。`planApi`。
**UI 规范**：⚠️ 部分违规。page-card 布局合规，但**进度条颜色违规**：
- `PlanDetailCardList.vue` 第 200 行：`.progress-fill { background: var(--gradient-primary); }` —— 蓝色渐变进度条，用于发货进度（未完成状态），应改为橙色渐变。
- `.fill-done` 使用 `var(--gradient-success)`（绿色）✅ 合规。
- `PlanDetailDialog.vue` 第 225 行：`.sp-modal-progress-fill` 使用 success 绿色渐变（已完成状态）✅ 合规。

**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟡 中（进度条颜色违规）

### 2.25 权限管理 (views/permission)

**文件清单**：1 文件 / 71 行
- `PermissionView.vue`

**TypeScript 质量**：✅ 优秀。`PermissionItem` 类型化，`VNode` 显式标注。
**组件设计**：✅ 优秀。`PermissionNode` 递归组件 + defineComponent + setup（React with Hooks 风格）。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。useQuery + staleTime 60s。
**API 调用**：✅ 合规。`permissionApi.tree()`。
**UI 规范**：✅ 合规。UiCard + UiSpinner + UiEmpty 组件库。
**错误处理**：✅ 良好。
**性能**：✅ 良好。
**风险等级**：🟢 低

### 2.26 登录 (views/login)

**文件清单**：6 文件 / 809 行
- `LoginView.vue`、`useLogin.ts`、`LoginFormMobile.vue`、`components/LoginBrandSection.vue` 等

**TypeScript 质量**：✅ 优秀。
**组件设计**：✅ 优秀。PC/移动端表单分离，useLogin 组合式函数复用。
**命名规范**：✅ 合规。
**状态管理**：✅ 优秀。reactive 表单状态。
**API 调用**：✅ 合规。`authApi`。
**UI 规范**：✅ 合规。aria-describedby 错误关联，aria-label 密码可见性切换。
**错误处理**：✅ 良好。
**性能**：✅ 优秀。`preloadEcharts` 预加载 ECharts（登录后首屏 dashboard 加速）。
**风险等级**：🟢 低

---

## 三、公共组件审查 (components/)

### 3.1 UI 基础组件（components/ui/）

| 组件 | 行数 | 说明 | 风险 |
|------|------|------|------|
| `UiProgressBar.vue` | 37 | 进度条，支持 primary/success/warning/danger variant | 🟡 中（默认 variant='primary' 蓝色，违反"非完成用橙色"偏好） |
| `UiProgress.vue` | - | 进度组件 | 🟢 低 |
| `UiButton.vue` | - | 按钮，variant='primary' 默认 | 🟢 低 |
| `UiTabs.vue` / `UiTabTrigger.vue` / `UiTabContent.vue` | - | 基于 reka-ui 的 Tab 组件 | 🟢 低 |
| `UiAlert.vue` | - | 警告提示 | 🟢 低 |
| `UiConfirmDialog.vue` | - | 确认弹窗 | 🟢 低 |
| `UiDataTable.vue` | - | 数据表格 | 🟢 低 |
| `UiCard.vue` / `UiDescriptions.vue` / `UiPageHeader.vue` | - | 卡片/描述列表/页头 | 🟢 低 |
| `UiSpinner.vue` / `UiEmpty.vue` / `UiLoadingIcon.vue` | - | 加载/空状态 | 🟢 低 |
| `UiInput.vue` / `UiBadge.vue` | - | 输入/徽章 | 🟢 低 |

### 3.2 备份组件（components/backup/）

| 组件 | 说明 | 风险 |
|------|------|------|
| `RestoreProgressBar.vue` | 恢复进度条 | 🟢 低 |
| `FileRestorePanel.vue` / `BackupModeSelector.vue` 等 | 备份/恢复面板 | 🟢 低 |

### 3.3 实时同步示例（components/RealTimeSyncExample.vue / SyncStatusIndicator.vue）

- 示例组件，非业务核心，🟢 低风险。

### 3.4 组件审查总结

- **类型化**：✅ 全部使用 `defineProps<T>()` / `withDefaults` 类型化。
- **可访问性**：✅ UiProgressBar 添加 `role="progressbar"` + `aria-valuenow/min/max`，UiTabs 基于 reka-ui 无障碍。
- **主要问题**：UiProgressBar 默认 variant='primary'（蓝色），应改为 'warning'（橙色）以符合用户偏好。

---

## 四、API 层审查 (api/)

### 4.1 请求封装（request.ts，250 行）

- ✅ **CSRF Token 处理**：内存缓存 + Cookie 兜底 + Capacitor localStorage 三级策略。
- ✅ **401/403 处理**：401 派发 `auth:expired` 事件，403 toast 提示（防抖）。
- ✅ **重试策略**：GET 502/503/504 + ECONNABORTED 指数退避（MAX_RETRIES=2）；写操作仅 502/503/504 重试一次。
- ✅ **GET 去重**：`_inflightGet` Map 同 url+params 共享 Promise。
- ✅ **Capacitor 适配**：Bearer token 注入、Filesystem + Share 下载。
- ✅ **类型安全**：`get<T>` / `post<T>` / `put<T>` / `del<T>` 泛型封装。
- ✅ **静态资源 URL 解析**：`resolveStaticUrl` 同源/SSR/Capacitor 多环境兜底。

### 4.2 业务 API 模块

| 模块 | 行数 | 方法数 | 命名规范 | 类型完整 | 风险 |
|------|------|--------|----------|----------|------|
| `patternRoom.ts` | 428 | 22 | ✅ camelCase | ✅ 30+ interface | 🟢 低 |
| `purchase.ts` | 84 | 20+ | ✅ camelCase | ✅ 完整 | 🟢 低 |
| `outsource.ts` | 96 | - | ✅ camelCase | ✅ 完整 | 🟢 低 |
| `dashboard.ts` | 58 | - | ✅ camelCase | ✅ 完整 | 🟢 低 |
| `material.ts` | 52 | - | ✅ camelCase | ✅ 完整 | 🟢 低 |
| `stock.ts` | 42 | - | ✅ camelCase | ✅ 完整 | 🟢 低 |
| `order.ts` / `production.ts` / `report.ts` 等 | 11-36 | - | ✅ camelCase | ✅ 完整 | 🟢 低 |

### 4.3 API Facade（index.ts）

- ✅ 统一 re-export，向后兼容 `productApi` 合并核心 + BOM 方法。
- ✅ 注释引导新代码直接从具体模块导入。

### 4.4 API 层审查总结

- **命名规范**：✅ 全部 camelCase 方法名（`getGroupedList`、`createProject`、`batchCreateParts`、`oneClickGenerate`、`unprocessedOrders`）。
- **错误处理**：✅ 统一在 request.ts 拦截器处理 401/403/502/503/504。
- **类型完整**：✅ 100% 泛型标注，响应类型 interface 定义完整。
- **风险**：🟢 低

---

## 五、Composables 审查

### 5.1 全局组合式函数（composables/）

| 组合式函数 | 行数 | 说明 | 风险 |
|-----------|------|------|------|
| `useToast.ts` | 293 | 全局 toast 提示 | 🟢 低 |
| `useRealTimeSync.ts` | 270 | 实时同步（WebSocket） | 🟢 低 |
| `useNotificationCenter.ts` | 181 | 通知中心 | 🟢 低 |
| `useVirtualScrollList.ts` | 150 | 虚拟滚动（useInfiniteQuery） | 🟢 低 |
| `useMaterialCache.ts` | 131 | 物料缓存 | 🟢 低 |
| `useMaterialCalculator.ts` | 118 | 物料计算器 | 🟢 低 |
| `useBackupProgress.ts` | 115 | 备份进度 | 🟢 低 |
| `useDevice.ts` | 104 | 设备检测（Capacitor） | 🟢 低 |
| `useNotifications.ts` | 101 | 通知 | 🟢 低 |
| `usePerfMark.ts` | 87 | 性能埋点 | 🟢 低 |
| `useWebSocket.ts` | 84 | WebSocket | 🟢 低 |
| `useListQuery.ts` | 79 | 列表查询（useQuery 封装） | 🟢 低 |
| `useEnhancedList.ts` | 61 | 增强列表 | 🟢 低 |
| `useExport.ts` | 52 | 导出 | 🟢 低 |
| `useEventDelegation.ts` | 49 | 事件委托 | 🟢 低 |
| `useApiMutation.ts` | 36 | API mutation（useQueryClient） | 🟢 低 |
| `useConfirmDialog.ts` | 34 | 确认弹窗 | 🟢 低 |
| `usePagedSearch.ts` / `useDebouncedSearch.ts` / `useDebouncedRef.ts` | 25-33 | 防抖搜索 | 🟢 低 |
| `usePermission.ts` | 11 | 权限检查 | 🟢 低 |

### 5.2 Composables 审查总结

- **React with Hooks 风格**：✅ 全部使用 `function useXxx() { ... return { ... } }` 模式，依赖通过参数传递（如 `useSamplingPart(selectedProjectId, roleHook.currentRoleId)`）。
- **类型安全**：✅ 全部 TypeScript 类型化。
- **职责单一**：✅ 每个组合式函数职责清晰（数据/动作/布局/缓存/性能）。
- **风险**：🟢 低

---

## 六、用户偏好合规性检查

### 6.1 camelCase 命名合规 ✅

- **检查方式**：grep `function\s+[a-z]+_[a-z_]+` 和 `const\s+[a-z]+_[a-z_]+\s*=` 全项目，**0 处违规**。
- **API 方法**：全部 camelCase（`getGroupedList`、`batchCreateParts`、`oneClickGenerate`、`unprocessedOrders`、`copyPartVersion`）。
- **组件方法**：全部 camelCase（`switchTab`、`handleOneClickGenerate`、`handleBatchComplete`、`loadStats`、`retryLoad`、`confirmLogout`）。
- **emit 事件**：全部 kebab-case（`@select-project`、`@add-pattern-maker`、`@update:visible`）。
- **结论**：✅ 完全合规。

### 6.2 Hooks 风格合规 ✅

- **检查方式**：grep `defineOptions\(\s*\{[^}]*name:\s*['"]` 和 Options API 模式，**0 处违规**。
- **Composition API + setup script**：✅ 全部使用 `<script setup lang="ts">`。
- **组合式函数**：✅ 全部 `function useXxx()` 模式，依赖参数传递。
- **PermissionNode**：✅ 使用 `defineComponent + setup` 渲染函数（递归组件场景）。
- **结论**：✅ 完全合规。

### 6.3 ECharts 按需导入合规 ✅

- **检查方式**：grep `import.*echarts` 全项目。
- **按需导入**：✅ 全部使用 `import('echarts/core')` + `import('echarts/charts')` + `import('echarts/components')` + `import('echarts/renderers')` 动态导入。
- **预加载**：✅ `utils/echartsPreload.ts` 提供 `preloadEcharts` / `ensureEcharts` / `getEchartsModule`，登录页预加载。
- **类型导入**：✅ `import type { EChartsType } from 'echarts/core'`。
- **使用位置**：仅 `dashboard/components/DashboardChartsSection.vue` 和 `production/composables/useProductionCharts.ts` 两处，集中管理。
- **结论**：✅ 完全合规。

### 6.4 page-card 布局合规 ✅

- **检查方式**：grep `page-card` 在 views/ 下，**85 处匹配**。
- **使用情况**：✅ 27 个业务模块中 26 个使用 `page-card page-card-main` + `page-card-header` + `page-card-body` 三段式布局（仅 settings/permission 使用 UiCard 组件库替代）。
- **全局样式**：✅ `src/styles/app.css` 定义 `.page-card` 系列全局样式，组件 scoped 样式仅覆盖特殊场景（如网格列数）。
- **结论**：✅ 完全合规。

### 6.5 HeaderTabs 组件使用 ⚠️ 部分违规

- **检查方式**：grep `HeaderTabs` 全项目，**0 处匹配**。
- **实际实现**：项目未实现名为 `HeaderTabs` 的统一组件，而是使用了多种替代方案：
  1. **reka-ui Tab 组件**：`UiTabs` + `UiTabTrigger` + `UiTabContent`（基于 reka-ui 无障碍）。
  2. **自定义 Tab 组**：`pc-tab-group`（purchase）、`cs-tab-group`（case）、`bt-tab-group`（batch）、`bo-confirm-filter`（hubei）、`mr-tab-btn`（material）、`bk-tab-bar`（backup）等，各模块样式独立。
  3. **业务 Tab 组件**：`ReportTabGroup`（report）、`HubeiRouteTabs`（hubei）、`PurchaseTabs`（purchase）。
- **违规分析**：用户偏好"HeaderTabs 组件"，期望统一的头部 Tab 组件。当前实现功能等价（role="tablist" + aria-selected），但命名不统一、样式分散，违反"统一组件"偏好。
- **建议**：抽取统一 `HeaderTabs.vue` 组件，封装 Tab 组样式与无障碍属性，替换各模块自定义 Tab 组。
- **结论**：⚠️ 部分违规（功能等价，命名/实现不统一）。

### 6.6 进度条颜色（橙色非蓝色）⚠️ 违规

- **用户偏好**：进度条颜色不应显示蓝色，非完成状态的进度条应统一使用橙色而非蓝色。
- **违规清单**：

| 文件 | 行号 | 当前颜色 | 应改为 | 状态 |
|------|------|----------|--------|------|
| `components/ui/UiProgressBar.vue` | 25 | `variant: 'primary'`（默认蓝色 `bg-primary-500`） | `variant: 'warning'`（橙色 `bg-warning-500`） | 🔴 默认值违规 |
| `views/product/components/BomEditor.vue` | 306 | `linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600))`（蓝色渐变） | `linear-gradient(135deg, var(--color-warning-400), var(--color-warning-600))`（橙色渐变） | 🔴 蓝色渐变 |
| `views/product/components/BomCopyDialog.vue` | 191 | 同上蓝色渐变 | 同上橙色渐变 | 🔴 蓝色渐变 |
| `views/outsource/components/OutsourceOrderTab.vue` | 337 | `.oso-progress-fill--wait { background: var(--color-primary-400); }`（蓝色） | `var(--color-warning-400)`（橙色） | 🔴 wait 状态蓝色 |
| `views/outsource/composables/useOutsourceProcess.ts` | 90 | `progress === 0` 返回 `'primary'`（蓝色） | 返回 `'warning'`（橙色） | 🔴 未开始状态蓝色 |
| `views/material/components/ProgressTab.vue` | 234 | `.mr-pfill.partial { background: var(--color-primary-500, #5B8DEF); }`（蓝色） | `var(--color-warning-500, #FF9F43)`（橙色） | 🔴 partial 状态蓝色 |
| `views/material/components/MaterialDetailDialog.vue` | 120 | 同上 partial 蓝色 | 同上橙色 | 🔴 partial 状态蓝色 |
| `views/purchase-plan/components/PlanDetailCardList.vue` | 200 | `.progress-fill { background: var(--gradient-primary); }`（蓝色渐变） | `var(--gradient-warning)` 或橙色渐变 | 🔴 蓝色渐变 |

- **合规清单**：

| 文件 | 行号 | 颜色 | 状态 |
|------|------|------|------|
| `mobile/components/MProgress.vue` | 42 | 默认 `var(--m-accent-amber)`（橙色），完成 `var(--m-accent-emerald)` | ✅ 合规 |
| `views/material/components/ProgressTab.vue` | 233 | `.mr-pfill.pending` 橙色 | ✅ 合规 |
| `views/material/components/ProgressTab.vue` | 235 | `.mr-pfill.completed` 绿色 | ✅ 合规 |
| `views/outsource/components/OutsourceOrderTab.vue` | 335 | `.oso-progress-fill--done` 绿色 | ✅ 合规 |
| `views/outsource/components/OutsourceOrderTab.vue` | 336 | `.oso-progress-fill--run` 橙色 | ✅ 合规 |
| `views/purchase-plan/components/PlanDetailDialog.vue` | 225 | `.sp-modal-progress-fill` 绿色渐变（已完成状态） | ✅ 合规 |
| `views/purchase-plan/components/PlanDetailCardList.vue` | 203 | `.fill-done` 绿色渐变 | ✅ 合规 |
| `views/stock/components/<StockOutImportSection.vue` | 291 | danger 红色渐变（OCR 错误场景） | ✅ 合规 |

- **结论**：⚠️ **8 处违规**，需统一修复为橙色（非完成状态）。

---

## 七、风险等级汇总

### 7.1 风险等级分布

| 风险等级 | 模块数 | 模块 |
|----------|--------|------|
| 🔴 高 | 1 | material（模板语法错误） |
| 🟡 中 | 4 | outsource、product、production、purchase-plan（进度条颜色违规/多根元素） |
| 🟢 低 | 22 | approval、backup、batch、beile-order、case、customer、customer-order、dashboard、hubei、login、material-calculator、notifications、ocr-import、pattern-room、permission、report、settings、stock、supplier、user、settings、permission |

### 7.2 高风险问题清单

| # | 文件 | 行号 | 问题 | 建议修复 |
|---|------|------|------|-----------|
| 1 | `views/material/MaterialView.vue` | 7 | `aria-label="来料进度 0' :class='['notification-badge', a"` 模板语法错误，属性值被污染 | 改为 `aria-label="来料进度"` |

### 7.3 中风险问题清单

| # | 文件 | 行号 | 问题 | 建议修复 |
|---|------|------|------|-----------|
| 1 | `components/ui/UiProgressBar.vue` | 25 | 默认 `variant: 'primary'`（蓝色） | 改为 `variant: 'warning'`（橙色） |
| 2 | `views/product/components/BomEditor.vue` | 306 | `.pd-progress-bar` 蓝色渐变 | 改为 `var(--color-warning-400/600)` 橙色渐变 |
| 3 | `views/product/components/BomCopyDialog.vue` | 191 | `.pd-progress-bar` 蓝色渐变 | 同上 |
| 4 | `views/outsource/components/OutsourceOrderTab.vue` | 337 | `.oso-progress-fill--wait` 蓝色 | 改为 `var(--color-warning-400)` 橙色 |
| 5 | `views/outsource/composables/useOutsourceProcess.ts` | 90 | `progressVariant(0)` 返回 `'primary'` | 改为返回 `'warning'` |
| 6 | `views/material/components/ProgressTab.vue` | 234 | `.mr-pfill.partial` 蓝色 | 改为 `var(--color-warning-500)` 橙色 |
| 7 | `views/material/components/MaterialDetailDialog.vue` | 120 | `.mr-pfill.partial` 蓝色 | 同上 |
| 8 | `views/purchase-plan/components/PlanDetailCardList.vue` | 200 | `.progress-fill` 蓝色渐变 | 改为橙色渐变 |
| 9 | `views/production/ProductionView.vue` | 58 | `<UiConfirmDialog>` 在根元素之外（多根元素） | 移入 `.pr-container` 内 |

### 7.4 用户偏好违规项清单

| 偏好 | 合规性 | 违规数 | 详情 |
|------|--------|--------|------|
| camelCase 命名（前端函数） | ✅ 完全合规 | 0 | - |
| React with Hooks 风格 | ✅ 完全合规 | 0 | - |
| ECharts 按需导入 | ✅ 完全合规 | 0 | - |
| page-card 布局 | ✅ 完全合规 | 0 | - |
| HeaderTabs 组件使用 | ⚠️ 部分违规 | - | 未实现统一 HeaderTabs 组件，使用多种替代方案（功能等价） |
| 进度条颜色（橙色非蓝色） | ⚠️ 违规 | 8 | 见 7.3 中风险清单 #1-#8 |
| light/white 主题 | ✅ 合规 | 0 | CSS 变量 + 白色 fallback |
| TypeScript 前端开发 | ✅ 完全合规 | 0 | - |

### 7.5 其他低风险观察

| # | 项目 | 说明 |
|---|------|------|
| 1 | `types/index.ts` 602 行 | 略超 500 行阈值，建议按业务域拆分为 `types/user.ts`、`types/order.ts`、`types/product.ts` 等 |
| 2 | `pattern-room` 44 文件 6,788 行 | 最大模块，但 composables/components 子目录组织良好，单文件均 <340 行 |
| 3 | HeaderTabs 组件缺失 | 建议抽取统一 `HeaderTabs.vue` 组件，封装 Tab 组样式与无障碍属性 |
| 4 | `request.ts` TODO 注释 | 提及可用原生 fetch 替代 axios，当前保留合理（深度依赖 axios 特性） |

---

## 八、总体评价

### 8.1 优点

1. **TypeScript 类型安全优秀**：几乎无 any 滥用，API 层 100% 泛型标注，Props/Emits 全部类型化。
2. **Vue 组件设计规范**：全部使用 `<script setup lang="ts">` Composition API，React with Hooks 风格典型应用，容器组件 + composables + 子组件三层架构清晰。
3. **命名规范完全合规**：函数 camelCase，组件 PascalCase，API 路径 kebab-case，emit 事件 kebab-case。
4. **状态管理优秀**：Tanstack Vue Query 广泛使用（30+ 文件），缓存/失效策略明确，Pinia store 精简（仅 4 个）。
5. **API 调用规范**：camelCase 方法名 + snake_case 后端路径，统一错误处理（401/403/502/503/504），CSRF Token 三级策略，GET 去重，重试退避。
6. **UI 规范合规**：page-card 布局统一，light/white 主题，ECharts 按需导入，aria 可访问性良好（738 处 aria-*）。
7. **错误处理完善**：244 处 try-catch，错误边界 + retry 机制，toast 提示。
8. **性能优化到位**：路由全懒加载，ECharts 动态导入 + 预加载，usePerfMark 性能埋点，虚拟滚动。
9. **大文件控制良好**：仅 `types/index.ts` 602 行略超 500 行阈值，其余全部合规。
10. **移动端适配完整**：Capacitor 45 文件，PC/移动端代码分离，MProgress 进度条颜色合规（橙色默认）。

### 8.2 待改进

1. **🔴 修复 MaterialView.vue 模板语法错误**（高优先级）。
2. **🟡 统一进度条颜色为橙色**（中优先级，8 处违规）。
3. **🟡 修复 ProductionView.vue 多根元素结构**（中优先级）。
4. **🟢 抽取统一 HeaderTabs 组件**（低优先级，功能已等价实现）。
5. **🟢 拆分 types/index.ts**（低优先级，602 行略超阈值）。

### 8.3 总体评分

| 维度 | 评分 | 说明 |
|------|------|------|
| TypeScript 质量 | ⭐⭐⭐⭐⭐ | 几乎无 any，类型完整 |
| Vue 组件设计 | ⭐⭐⭐⭐⭐ | Composition API + Hooks 风格典型 |
| 命名规范 | ⭐⭐⭐⭐⭐ | 完全合规 |
| 状态管理 | ⭐⭐⭐⭐⭐ | Vue Query + Pinia 合理 |
| API 调用 | ⭐⭐⭐⭐⭐ | 规范统一，错误处理完善 |
| UI 规范 | ⭐⭐⭐⭐ | page-card 合规，进度条颜色违规 |
| 错误处理 | ⭐⭐⭐⭐⭐ | 244 处 try-catch |
| 可访问性 | ⭐⭐⭐⭐⭐ | 738 处 aria-* |
| 性能 | ⭐⭐⭐⭐⭐ | 懒加载 + 按需导入 + 性能埋点 |
| **综合** | **⭐⭐⭐⭐½** | **优秀，少量违规需修复** |

---

> 报告生成完毕。审查文件数：415，总行数：~54,780，高风险 1 项，中风险 9 项，用户偏好违规 8 项（进度条颜色）+ 1 项（HeaderTabs 缺失）。
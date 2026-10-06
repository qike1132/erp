# 迭代审核报告 —— 粘贴识别共享组件（客户订单 / 出货两页）

- 日期：2026-10-06
- 审核对象：本轮「粘贴截图识别抽成共享组件」全量改动（已 build 上线，live hash 已比对一致；未提交）
- 审核方式：基于工作区最新代码逐文件人工审核（frontend-code-review 技能清单：Code Quality / Performance / Business Logic，React 语境规则按 Vue 语义映射），全部测试证据为本机当日实跑。
- 结论：**Approve**（0 个 P0/P1；2 个 P2 建议、2 个 P3 建议，均可择期闭环）

## 一、改动范围与证据

| 项 | 内容 |
|---|---|
| 新增 | `frontend-vite/src/components/ocr/`：`OcrPasteImport.vue`(225行) / `OcrPreviewModal.vue`(372行) / `useOcrPaste.ts` / `types.ts` |
| 映射层 | `customer-order/composables/useOrderOcrStaging.ts`、`stock/composables/useStockoutOcrStaging.ts`（纯函数） |
| 删除 | `OrderOcrPaste.vue`、`OcrPreviewModal.vue`、`useOrderOcr.ts`、`useOcrImport.ts`（全仓无残留引用） |
| 后端 | `ocr_import.py` `/ocr-import/order/preview` 权限补 `stockout_manage`（仅此一行，端点不写库） |
| 测试 | 既有 2 个 OCR 测试迁移导入路径 + 新增 `stockOutOcrPaste.test.ts`(4例) |

测试证据（当日实跑）：vue-tsc 全绿；vitest 128 文件 1170 例全过；eslint 0 error；ruff 干净；后端 OCR 端点 15/15；check:api / check:routes 通过；`python scripts/quality_gate.py` 唯一新增违规为 `ProjectCardItem.vue` 393→409 行（**归因并行会话在途板房改动，非本次**，未棘轮基线）。

## 二、已核实的关键非问题（审核中专门查过）

1. **超额出货不因 OCR 路径放大**：手工路径 `addStaged` 的可出货量检查只是提前反馈；权威闸门在 `useStockOutActions.submitBatch` 的提交时分组预检（按产品+客户聚合查 `availableShipment`，超额组整组拦截）。OCR 条目与手工条目进同一 `staged` 列表，同样被拦。与旧「多文件 PDF 直接写后端暂存」行为相比无回退。
2. **权限面收敛**：`order/preview` 只读（产品/客户名匹配），`stockout_manage` 用户可见的产品目录与其页面既有权限一致；旧的多文件导入端点（`/preview`、`/upload`、`create-task`）前端已不再调用但端点保留，权限未动。
3. **文件大小门禁**：共享组件最大 372 行（<400）。
4. **并行覆写事故已闭环**：本轮期间并行会话（出货计划在途）曾用陈旧缓冲区整文件覆写 3 个共改文件、`auto-imports.d.ts` 被写满 NUL（size 不变骗过 git stat 缓存，`git checkout` 空转，需直接按字节写回）。已全部重下补丁并复验（构建 + 18 例针对性测试通过）。**下次构建前建议先跑一次标记核验**。

## 三、发现（按优先级）

### P2-1 数量常量与 genUid 双源
- 位置：`frontend-vite/src/components/ocr/useOcrPaste.ts`（`QUANTITY_MIN/MAX` 本地常量、`genUid` 本地实现）
- 现状：与 `customer-order/composables/quantityRange`（1..9,999,999）和 `useStagedItems.genUid` 语义相同但各自持有，仅有注释互相指认。共享组件不能反向 import 视图层是分层正确的，但目前是「约定一致」而非「编译期一致」。
- 建议：出现第三个消费域时再把这两个常量/工具上移到 `src/components/ocr`（或 `src/utils/quantity.ts`），视图层反向引用；当前保持现状可接受，但两处任一改动必须同步。

### P2-2 出货页粘贴热区缺小节标签
- 位置：`frontend-vite/src/views/stock/components/StockOutImportSection.vue`（`<OcrPasteImport>` 挂在「批量导入」小节之后）
- 现状：出货录入页小节均带 `so-section-label` 小标题（批量导入 / 原 OCR 识别），新粘贴热区是自成一体的蓝底虚线块，无小节标题，与页面既有节奏略不一致（客户订单页原本就是裸热区，无此问题）。
- 建议：给该页热区上方补一行 `so-section-label`（如「粘贴识别」），或在 OcrPasteImport 加可选 label prop。

### P3-1 权限契约无守卫测试
- 位置：`fastapi_app/tests/test_ocr_order_preview.py`
- 现状：本轮给 `/ocr-import/order/preview` 增加了 `stockout_manage` 权限码，但测试未断言新权限可通过，未来收缩权限不会被发现。
- 建议：按现有用例补一条 `stockout_manage` 用户 200 的断言（顺带断言无权限 403）。

### P3-2 StockOutTab 接线无集成测试
- 位置：`frontend-vite/src/views/stock/StockOutTab.vue`（`addOcrStaged`）
- 现状：映射函数与闸门均有测试，`StockOutImportSection → InputForm → Tab.addOcrStaged` 的事件链无测试覆盖（订单侧同等接线也无，属既有口径）。
- 建议：可在下一轮补一个挂载 Tab 断言 staged 增长的轻量用例；不阻断。

## 四、 verdict

**Approve。** 共享化方向、闸门一致性（弹窗按钮禁用与 confirmImport 校验同源）、删除文件的全仓零残留、测试迁移完整性均达标；P2 两项为维护性/一致性改进，建议与出货计划在途工作合流时顺手处理。

## 五、修复闭环（2026-10-06 当日，用户拍板四条全修）

| 项 | 处置 | 验证 |
|---|---|---|
| P2-1 常量双源 | 真相源上移 `src/utils/quantity.ts`（quantityRange 变再导出 shim，页内 12 处消费点零改动）+ `src/utils/uid.ts`（useStagedItems 再导出）；useOcrPaste/useOrderOcrStaging 改导入 | quantityRange 守卫测试 23 例原样通过 |
| P2-2 小节标签 | StockOutImportSection 热区上方补 `so-section-label`「粘贴识别」 | build 通过，线上 hash 已更新 |
| P3-1 权限守卫 | `test_ocr_order_preview.py` 新增 3 例：stockout_manage 200 / order_manage 仍 200 / 三码皆无 403 | 后端 11/11 通过（403 实走拦截链） |
| P3-2 接线测试 | 新增 `stockOutTabOcrWiring.test.ts`：buildStaged 回调→Section 发 ocr-staged→InputForm 转发→Tab 入列，断言 staged 增长与多批追加 | vitest 全套 129 文件 1177 例全过 |

复验：vue-tsc 全绿；eslint 0 error（+2 warning 归因并行会话在途文件）；quality_gate 除既有 ProjectCardItem(在途) 归因外无新增违规；已重新 build 并比对 3000 端口 live hash（`index-Drg9q9DA.js`）。注：全套 vitest 末尾有 `api.d.ts 与 openapi.json 不同步` 的 teardown 提示，归因并行会话的后端 API 改动未重生成类型，不在本次改动面内，留待该会话收尾时 `npm run gen:api`。

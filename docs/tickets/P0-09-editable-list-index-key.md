# P0-09　可编辑列表用 index 作 `:key` → 输入内容错位

| 字段 | 值 |
|---|---|
| 严重度 | 🔴 高（用户可感知的数据错位） |
| 类型 | 前端缺陷 · 渲染 |
| 模块 | `views/pattern-room/components/DialogRoleEditor.vue`、`views/purchase-plan/components/ManualPlanForm.vue` |
| 预估工时 | 1 h（含单测） |
| 批次 | C（前端，需 `vue-tsc -b` + build） |
| 依赖 | 无 |

## ⚠️ 范围修正（复核后收窄）

初审报告列了 3 处，逐文件复核后**其中 1 处不成立**：

| 文件 | 是否真 bug | 原因 |
|---|---|---|
| `DialogRoleEditor.vue:3` | ✅ **是** | 可编辑 `<input>` + 可删除中间行 → 输入内容错位 |
| `ManualPlanForm.vue:10` | ✅ **是** | 可编辑多字段 + 可增删 → 输入内容/焦点/下拉态错位 |
| `OutsourceProcessLedger.vue:69` | ❌ **不是** | **只读展示表**（纯文本 `<td>`，无 input、无增删、无排序），index key 不会丢状态 |

第三处降级为 **P3 可选优化**（仍建议改用 `:key="item.process_type"`，因为该字段天然唯一，
可减少不必要的 DOM patch，但**不是缺陷**）。本工单只处理前两处。

## 定位与根因

### 缺陷 1：`DialogRoleEditor.vue`

`frontend-vite/src/views/pattern-room/components/DialogRoleEditor.vue:1-27`

```vue
<div v-for="(role, idx) in modelValue" :key="idx" class="dre-role-row">
  <input v-model="modelValue[idx]" class="dre-role-input" placeholder="角色名称" maxlength="100" />
  <button v-if="modelValue.length > 1" type="button" class="dre-role-remove" title="移除"
          @click="modelValue.splice(idx, 1)">
    <FontAwesomeIcon icon="times" aria-hidden="true" />
  </button>
</div>
```

`modelValue` 是 `string[]`（`defineModel<string[]>`），**数组元素本身没有 id**，
所以最初只能用 index 当 key。

**错位是如何发生的**：Vue 用 key 决定"复用哪个 DOM"。当 `['A','B','C']` 删掉中间的 `'B'`：

```
修复前（key = index）          删除 idx=1 后
key=0 → input(A)              key=0 → input(A)     ← 复用，正确
key=1 → input(B)  ← 删除      key=1 → input(C)     ← 复用 B 的 DOM，值写 C
key=2 → input(C)  ← 删除      （原 key=2 被销毁）
```

结果是 **input(C) 复用了 input(B) 的 DOM 节点** → 焦点、光标位置、输入法候选态、`selectionStart` 全部跟着错误的 DOM 走。
用户感知："删掉中间一个，后面那个的输入框行为变得很奇怪 / 光标跳到别处"。

### 缺陷 2：`ManualPlanForm.vue`

`frontend-vite/src/views/purchase-plan/components/ManualPlanForm.vue:10-34`

```vue
<div v-for="(d, idx) in details" :key="idx" class="csd-detail-item">
  ...
  <UiSelect v-model="d.customer_id" placeholder="选择客户" :options="customerOptions" />
  <input v-model="d.product_name" @input="emit('product-input', idx)"
         @focus="emit('product-focus', idx)" @blur="emit('product-blur', idx)" />
  <div v-if="d._showSuggest && productSuggestions[idx]?.length" class="csd-suggest-list">
```

`details: DetailLine[]`，每行含 `customer_id / product_name / plan_date / quantity / _showSuggest`。
创建点（`composables/useCreateShipmentPlan.ts:39 / :53 / :82`）都是纯对象字面量，**无 id 字段**：

```ts
// useCreateShipmentPlan.ts:82
form.details.push({ customer_id: '', product_name: '', product_id: 0, barcode: '',
                    plan_date: '', quantity: null, _showSuggest: false })
```

除输入值错位外，这里还多一层：**`_showSuggest` 是子组件持有的行状态**。
删除中间行后，`_showSuggest=true` 的 DOM 被复用给下一行数据 → **下拉建议面板挂到错误的行上**，
且 `productSuggestions[idx]` 用的是新 idx → **建议列表内容与行不匹配**。

## 修复方案

### 缺陷 1：DialogRoleEditor（数组是纯字符串，需维护并行 key 列表）

```diff
--- a/frontend-vite/src/views/pattern-room/components/DialogRoleEditor.vue
+++ b/frontend-vite/src/views/pattern-room/components/DialogRoleEditor.vue
@@
-    <div v-for="(role, idx) in modelValue" :key="idx" class="dre-role-row">
+    <div v-for="(role, idx) in modelValue" :key="keys[idx]" class="dre-role-row">
@@
-        @click="modelValue.splice(idx, 1)"
+        @click="removeRole(idx)"
@@
-    <button type="button" class="dre-add-btn" aria-label="添加角色" @click="modelValue.push('')">
+    <button type="button" class="dre-add-btn" aria-label="添加角色" @click="addRole()">
@@
 <script setup lang="ts">
+import { ref, watch } from 'vue'
+
 const modelValue = defineModel<string[]>({ default: () => [''] })
+
+// modelValue 是纯字符串数组，元素本身无法承载 id，
+// 故维护一个与之等长的稳定 key 列表（仅用于 DOM 身份，不参与提交）。
+let _seq = 0
+const nextKey = (): string => `role-${++_seq}`
+
+const keys = ref<string[]>([])
+
+/** 外部整体替换 modelValue 时按长度补齐/裁剪，避免 key 与数据错位 */
+function syncKeys(length: number): void {
+  while (keys.value.length < length) keys.value.push(nextKey())
+  if (keys.value.length > length) keys.value.length = length
+}
+
+watch(() => modelValue.value.length, syncKeys, { immediate: true })
+
+/** 增删必须同时改两个数组，以保持下标一一对应 */
+function addRole(): void {
+  modelValue.value.push('')
+  keys.value.push(nextKey())
+}
+
+function removeRole(index: number): void {
+  modelValue.value.splice(index, 1)
+  keys.value.splice(index, 1)
+}
 </script>
```

> 注意 `addRole` 里同时 push 两个数组，会触发 `watch(length)` 再跑一次 `syncKeys` ——
> 此时长度已相等，是 no-op，不会重复生成 key。

### 缺陷 2：ManualPlanForm（数据是对象，直接加 `_uid` 最干净）

**第 1 步** —— 类型加字段（`useCreateShipmentPlan.ts:10`）

```diff
 export interface DetailLine {
+  /** 仅前端用于 v-for 稳定 key，提交前需剔除 */
+  _uid: string
   customer_id: ...
```

**第 2 步** —— 统一创建入口 + 三处创建点加 `_uid`

```diff
+let _lineSeq = 0
+const newDetailLine = (): DetailLine => ({
+  _uid: `line-${++_lineSeq}`,
+  customer_id: '', product_name: '', product_id: 0, barcode: '',
+  plan_date: '', quantity: null, _showSuggest: false,
+})
+
 // :39 初始 details
-    { customer_id: '', product_name: '', ... },
+    newDetailLine(),
 // :53 重置
-    form.details = [{ customer_id: '', product_name: '', ... }]
+    form.details = [newDetailLine()]
 // :82 新增行
-    form.details.push({ customer_id: '', product_name: '', ... })
+    form.details.push(newDetailLine())
```

**第 3 步** —— 模板改 key（`ManualPlanForm.vue:10`）

```diff
-    <div v-for="(d, idx) in details" :key="idx" class="csd-detail-item">
+    <div v-for="(d, idx) in details" :key="d._uid" class="csd-detail-item">
```

**第 4 步** —— 提交前剔除 `_uid`（关键，否则会污染后端请求体）

在 `useCreateShipmentPlan.ts` 组装 payload 处（`:173` 附近 `byCustomer` 构造前）过滤：

```ts
const payloadDetails = form.details.map(({ _uid, _showSuggest, ...rest }) => rest)
```

> 若不加这一步，后端 Pydantic 若设了 `extra='forbid'` 会直接 400；
> 即使不报错，也会把前端内部字段写进数据库或日志。

## 验收标准

1. **类型门禁**（含 `src/test/`）
   ```bash
   node frontend-vite/node_modules/vue-tsc/bin/vue-tsc.js -b
   ```
   期望 EXIT=0。⚠️ 注意 `--noEmit` **不检查** `src/test/`，必须用 `-b`。
2. **端到端断言（核心）**——本项目已确认无 Playwright 内核，用 Python + 系统 Edge：
   ```python
   # 角色编辑器：删中间行后，剩余行的输入值必须仍是「原数据」而非「被复用 DOM 的旧值」
   await page.goto(f'{BASE}/pattern-room')
   # ... 打开角色编辑弹窗，填 A/B/C
   await page.click('.dre-role-remove >> nth=1')       # 删中间 B
   values = await page.eval_on_selector_all('.dre-role-input', 'els => els.map(e => e.value)')
   assert values == ['A', 'C'], f'删除后内容错位: {values}'
   ```
   **修复前**该断言会失败（依赖复用导致内容/焦点错位）。
3. **手动回归**
   - 角色编辑：在 3 个角色的第 2 个输入框输入 → 删第 2 个 → 确认第 3 个（原）内容未变、光标不跳
   - 手动计划：中间行填客户+产品（触发下拉建议）→ 删除该行 → 确认下拉面板不再残留、其它行内容未串
4. **请求体纯净**——抓包确认提交 payload 中**不含** `_uid` / `_showSuggest`：
   ```bash
   # Playwright 里监听 request，断言 body 键不含 _uid
   ```

## 发布动作

前端改动 → `vue-tsc -b` 门禁 → build → 发布 dist。
⚠️ 两点项目约定务必遵守：
1. `:3000` 由 nginx 吃 `frontend-vite/dist` → **不 build 在 :3000 上看不到任何变化**
2. `build:atomic` 的 rename 交换在 **dev server 运行期间会 EPERM 失败**（vite watcher 持目录句柄）→ **发布前先停 dev server**

## 回归风险

低，但有一个**必须检查**的点：`_uid` 泄漏到请求体（见验收项 4）。
`DetailLine` 若被其它地方 `as` 断言或整体 spread 到后端调用，会一并带上 —— 建议全仓搜 `details` 的所有使用点确认。

## 后续（可选，P3）

`OutsourceProcessLedger.vue:69` 虽非缺陷，仍建议顺手改 `:key="item.process_type"`（天然唯一字段），
可减少只读表的无谓 DOM patch：

```diff
-          <tr v-for="(item, i) in remainingList" :key="i">
+          <tr v-for="item in remainingList" :key="item.process_type">
```

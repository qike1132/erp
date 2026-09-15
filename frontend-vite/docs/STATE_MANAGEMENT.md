# 状态管理边界规范

> 适用：`frontend-vite/src` 全部代码
> 目的：消除 Pinia 与 TanStack Query 的职责重叠，防止同一份数据双缓存导致的失效不同步

## 一、核心原则

**"数据从哪来"决定"状态放哪"** —— 边界不按技术栈划分，按数据来源划分。

| 数据来源 | 存放位置 | 理由 |
|---|---|---|
| 后端 API（订单、客户、产品、库存、BOM、采购…） | **TanStack Query** | 天然带缓存、失效、重试、乐观更新、请求去重 |
| 纯客户端 UI 状态（侧栏折叠、主题、当前 Tab、多步表单草稿、未提交的筛选条件） | **Pinia** | 无服务端真相，只需跨组件共享 |
| 组件内局部状态（弹窗开关、下拉展开） | **`ref()` in setup** | 不需要跨组件，不要为了"统一"塞进 store |

## 二、硬性规则

### 规则 1：API 数据禁止进 Pinia

```ts
// 错误：订单数据同时进 store
const orderStore = useOrderStore()
const { data } = useQuery({ queryKey: ['orders'], queryFn: fetchOrders })
watch(data, (v) => orderStore.setOrders(v))   // 双缓存，失效不同步

// 正确：直接用 Query，需要跨组件就直接用同一个 queryKey
const { data: orders } = useQuery({ queryKey: ['orders'], queryFn: fetchOrders })
```

**判定方法**：如果一个字段的值**来自接口返回**，它就应该在 Query 里，不在 Pinia 里。

### 规则 2：跨组件共享 API 数据 = 共享 queryKey，不是共享 store

不同组件需要同一份数据时，用**相同的 queryKey**，TanStack Query 会自动去重与共享缓存：

```ts
// A 组件
const { data } = useQuery({ queryKey: ['products', filters], queryFn: () => getProducts(filters) })
// B 组件：完全相同的 queryKey → 命中同一缓存，不会重复请求
const { data } = useQuery({ queryKey: ['products', filters], queryFn: () => getProducts(filters) })
```

**因此 queryKey 必须稳定且语义完整**：所有影响结果的参数都要进 key。

### 规则 3：写操作后靠失效，不靠手动同步

```ts
// 正确：改完让相关缓存失效，所有引用方自动刷新
const qc = useQueryClient()
const { mutate } = useMutation({
  mutationFn: updateOrder,
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['orders'] })
    qc.invalidateQueries({ queryKey: ['order', id] })
  },
})
```

**禁止**：写操作成功后手动 `store.setXxx()` 或手动改本地数组——一定会漏。

### 规则 4：Pinia 只保留"纯 UI"状态

允许放进 Pinia 的典型：

- 布局：侧边栏展开/折叠、主题、语言
- 导航：当前选中的客户/项目（仅作为"当前上下文"，不缓存其数据）
- 表单草稿：多步骤表单的中间态（未提交前无服务端真相）
- 权限：当前用户权限位（登录后一次性写入，不再变化）

## 三、审计清单

审查 `src/stores/` 下每个 store，对每个字段问：

1. 这个值是否来自接口？→ 是则迁到 TanStack Query
2. 这个值是否有多个组件需要？→ 否则降级为组件内 `ref()`
3. 这个值是否长期不变（如权限）？→ 可以留在 Pinia
4. 是否存在同名数据也在 Query 缓存里？→ **是则必须消除其中一个**

## 四、迁移方式（渐进，不破坏现有功能）

1. 选定一个 store，列出其字段并与 Query 缓存对照
2. 找出重叠字段
3. 把读方改为 `useQuery`，删除 store 中对应字段与 setter
4. 运行 `npm run test` + `vue-tsc --noEmit` 验证
5. 逐个 store 推进，不要求一次改完

## 五、常见误区

| 误区 | 纠正 |
|---|---|
| "放 store 里方便到处取" | 相同 queryKey 同样方便，且自带缓存与失效 |
| "Query 只管读，写还是走 store" | 写走 `useMutation` + `invalidateQueries` |
| "把 Query 的 data 复制到 store 做只读快照" | 这就是双缓存，直接读 Query 的 data |
| "分页数据放 store 里拼" | 用 `useInfiniteQuery`（参见 `useVirtualScrollList`） |

---

## 参考

- 借鉴 **vbenjs/vue-vben-admin**：它明确划分 TanStack Query（服务端状态）与 Pinia（应用状态），并在文档中固化该边界。
- 项目内已有范例：`src/composables/useVirtualScrollList.ts` 就是"服务端状态全交给 Query"的正确写法。

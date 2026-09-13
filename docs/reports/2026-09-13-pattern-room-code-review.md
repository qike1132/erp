# 打样间（/pattern-room）模块代码审查报告

- 审查日期：2026-09-13
- **实施状态（2026-09-13 同日）**：优先级清单 1-10 项已全部实施并通过验证（后端 py_compile + 导入冒烟 + test_integration_smoke 8/8；前端 vue-tsc 零错误 + vitest 111/111）。改动未提交、未部署。实施中的偏差：P4 采用"两段式查询"（轻量列分组分页 + 仅当前页取明细）而非完全 DB 侧窗口分页，收益接近、风险更小；P9 的版本解耦按报告建议实施——版本 chip 改为纯本地查看（所有人可用），"设为最终版本"改为行内显式旗帜按钮（仅管理者可见）。
- **复审与收尾（同日第二轮）**：按 code-review-excellence 复审判定 Approve；复审列出的三项低优先级问题已修复——`latest_map` 注解收窄为 `datetime`、删除 `_next_version` 死函数（含 `__init__` 导出）、删除 parts.py 的 `generate_customer_sampling_number` 死导入；回归 8/8 通过。勘误：复审所列"`page_ids` IN 子句理论上无上界"不成立——`page_ids` 受轻量查询 `limit(_GROUPED_LIST_MAX_PROJECTS=5000)` 约束，天然有界，无需修复。原始审查中仍有意搁置的项：G6（模型死 to_dict）、G7 其余过渡期死导入、G8（endpoint docstring 位序）、G9/G10 其余死导出、G11（PartFormDialog supplier_id 与 index key）、G12（清理函数双查询）、Q3（供应商清除三态语义）、Q6（version hook 共享竞态计数器）。
- 审查范围：`frontend-vite/src/views/pattern-room/**`（视图 + 18 组件 + 15 组合式函数）、`src/api/patternRoom.ts`、`src/stores/patternRoom.ts`，后端 `fastapi_app/api/v1/endpoints/customer_sampling.py`、`services/customer_sampling/**`、`services/pattern_maker_service.py`、`shared_models/customer_sampling.py`、`shared_models/pattern_maker.py`，约 9,500 行。
- 影响程度：🔴 高（正确性/显著性能）｜🟡 中｜💭 低

---

## 一、功能性 Bug（🔴 高）

### 1. 「创建新版本」按钮完全失效
- 位置：`components/ProjectDetailPanel.vue:25`（`@click="$emit('create-version')"`）、`PatternRoomView.vue:46-71`（ProjectDetailPanel 的事件绑定区）、`composables/usePatternRoomPartActions.ts:293-299`（`openCreateVersionDialog` 死导出）
- 问题：详情面板头部「创建新版本」按钮 emit 了 `create-version`，但 PatternRoomView 没有绑定 `@create-version`；弹窗打开函数 `openCreateVersionDialog` 与 `versionCreateVisible` 之间唯一赋值链路已断（重构搬移时丢失）。`VersionCreateDialog` 永远无法打开，`versionHook.createVersion` 亦无从触发。
- 影响：核心功能（版本快照）在 UI 上不可达；用户只能靠「复制版本」逐部位操作。
- 建议：在 PatternRoomView 的 `<ProjectDetailPanel>` 上补 `@create-version="openCreateVersionDialog"`，并把 `openCreateVersionDialog` 加入解构；顺带清理死导出。

### 2. 编辑弹窗「移除图片」不生效
- 位置：`components/ProjectFormDialog.vue:104-122,124-146`、`PatternRoomView.vue:90`（`@remove-image="pendingProjectImage = null"`）、`api/patternRoom.ts` ProjectUpdateRequest（缺 `clear_image`）
- 问题：编辑模式下移除图片只清空了 `pendingProjectImage` 与本地预览；提交的 `ProjectUpdateRequest` 不含 `clear_image`（后端 `update_project` 已支持该参数），服务端旧图保持不变，刷新详情后图片"复活"。
- 建议：编辑弹窗维护"初始图 file_id 是否被移除"状态，提交时传 `clear_image: true`；或移除时直接调上传接口的清空语义。

### 3. 备注无法清空
- 位置：`ProjectFormDialog.vue:129`（`remark: form.remark || null`）、后端 `projects.py:199`（`remark is not None` 才更新）
- 问题：空字符串被转成 `null`，后端把 `None` 解释为"不修改"，导致"清空备注"静默失效。
- 建议：前端把空备注发 `''`（后端已有 `remark != (project.remark or '')` 判断可正确处理），或统一改用字段级 patch 协议。

---

## 二、性能问题

### P1 打印一次拉全角色全版本快照，实际只用最终版本行（🔴 高）
- 位置：`composables/usePatternRoomPrint.ts:52-66`；`components/PrintDialog.vue:103-133`（`groupedParts` 只保留 `version_no === role.current_version` 的行）；后端 `version_diff.py:get_parts_by_version`
- 问题：点击打印对每个角色并行发 `GET /parts-by-version`（N 个请求），每个请求在后端加载该角色**所有版本**的部位数据 + `snapshot_data` JSONB 全量；而打印内容只取各角色最终版本一行。角色越多、版本越多浪费越大（内存、DB IO、网络传输约 (版本数/最终版本数) 倍浪费）。
- 建议：给 `get_parts_by_version` 增加 `only_final=true`（或 `version_no` 过滤参数），打印只取最终版本行；或后端新增 `GET /projects/{id}/parts/print` 一次返回全部角色最终版本。

### P2 grouped-list 全量加载 + 全量构建摘要（🟡 中）
- 位置：`services/customer_sampling/grouping.py:55-182`
- 问题：
  1. 为实现"分组级分页"，把最多 `_GROUPED_LIST_MAX_PROJECTS=5000` 条项目全量拉取（含 pattern_maker selectinload）；
  2. 对**全部**匹配项目构建 `summary_map`（`_project_to_summary`），但仅当前页分组（≤ per_page 组）会被序列化返回；
  3. `_batch_get_image_urls` 对全部 5000 个 `product_image_file_id` 做 IN 查询，同样只有当前页需要。
- 影响：数据量增长后 CPU/内存线性浪费（5000 次 dict 构建通常几十 ms，主要是 ORM 实例化 5000 行 + 5000 ID 的 IN 查询；平时 20 条/页 → 实际放大约 10-100 倍）。
- 建议：先在 DB 侧按 `pattern_maker_id` 聚合出分组及每组的 `max(updated_at)`、项目数做分组分页，再按当前页分组的 maker_id 集合二次查询项目明细（分页内项目数可控）；图片 URL 只查当前页分组的项目。

### P3 详情/版本列表拉全量 snapshot_data JSONB（🟡 中）
- 位置：`services/customer_sampling/projects.py:332-341`（`get_project_detail` selectinload fabric_versions）、`version_diff.py:52-57`（`list_versions`）
- 问题：详情页版本列表只展示 `version_no/created_at/reason` 三个字段，却把每条 `snapshot_data`（完整部位快照 JSON）+ `change_summary` 全部从 DB 读入内存并实例化 ORM。版本多、快照大时详情接口体积与延迟被无谓放大。
- 建议：改 `select(CustomerSamplingFabricVersion.id, .version_no, .created_at, .reason)` 纯列查询，或 `load_only(...)` + `defer(snapshot_data, change_summary)`。

### P4 useSamplingPart.create/update/remove 死代码但保留"全量刷新"逻辑（🟡 中，兼垃圾代码）
- 位置：`composables/useSamplingPart.ts:96-163`
- 问题：这三个函数无任何调用方（实际写路径在 `usePatternRoomPartActions` 直接调 API + 局部 patch/全量刷新）。死代码本身是负担；若未来被复用，其内部"写后必全量 fetchPartsByVersion"的策略也会抵消已有的 patch 优化。
- 建议：删除（若要保留统一入口，则改写为 patch 语义）。

### P5 每次进入/激活页面的重复加载（💭 低）
- 位置：`PatternRoomView.vue:196-210`
- 问题：`onMounted` 与 `onActivated` 在首次挂载都会触发（keep-alive 下 activated 紧随 mounted），首次进入 `loadGrouped`+`loadPatternMakers` 各发两次调用，目前仅靠 store 的并发去重兜底，属于隐性依赖。
- 建议：只保留 `onActivated`（首次激活也会触发），删除 `onMounted` 中的重复调用。

### P6 组内分页 force=true 使缓存永远不命中（💭 低）
- 位置：`composables/usePatternRoomGroupFilter.ts:22,28,36`
- 问题：状态切换/翻页/搜索一律 `force=true`，SWR 缓存（stores/patternRoom.ts 精心实现）对这三类高频操作全部失效，仅 keep-alive 激活路径受益。
- 建议：翻页可改为非 force（缓存 key 含 page）；搜索与状态切换保留 force 是合理的。

### P7 useVirtualAreaMeasure / VirtualList / v-memo（✅ 亮点）
- `useVirtualAreaMeasure`（rAF 去抖、父级 ResizeObserver、完整清理）与 `CustomerProjectArea` 的虚拟列表+组内分页+v-memo 是本模块性能上的亮点，予以保留表扬。

---

## 三、垃圾代码 / 死代码

### G1 completed-table 全链路死功能（🟡 中）
- 位置：后端 `endpoints/customer_sampling.py:110-123`、`grouping.py:210-319`（get_completed_table ~110 行）、`schemas/customer_sampling.py` CompletedTableResponse；前端 `api/patternRoom.ts:398-399`（getCompletedTable）、`CompletedTableRow/CompletedTableResponse` 类型
- 问题：全仓 grep 无任何 UI 调用。约 150 行前后端死代码，还带了 DISTINCT ON、parts 统计等精心实现。
- 建议：确认产品无此需求后整链路删除；若为规划中的"已完成表格页"，加 TODO 注明。

### G2 `_SNAPSHOT_FIELDS` 重复定义 7 份（🟡 中）
- 位置：`grouping.py:30`、`common.py:34`、`projects.py:26`、`parts.py:27`、`roles.py:28`、`upload.py:29`、`version_diff.py:33`
- 问题：同一常量复制粘贴到子包每个文件（部分文件根本不用），真正使用点只有 `version_diff.py::_compute_diff`。修改字段清单时极易漏改。
- 建议：只保留 `common.py` 一份，其余删除（`__init__.py` 的 re-export 保留一处）。

### G3 `_GROUPED_LIST_MAX_PROJECTS` 两处定义且值冲突（🟡 中）
- 位置：`grouping.py:36`（=5000，实际使用）、`common.py:182`（=2000，死常量，注释却声称是同一防护）
- 问题：同值异名常量并存且数值不一致，误导后续维护。
- 建议：删除 common.py 的副本。

### G4 子包 docstring 复制 7 份（💭 低）
- 位置：grouping/common/projects/parts/roles/upload/version_diff 每个文件头部同一段"职责拆分"说明（内容还是描述原 1619 行上帝服务的拆分史）。
- 建议：只留 `__init__.py` 的包级 docstring，各文件换成一句话模块职责。

### G5 `_next_version` 定义并导出但无调用（💭 低）
- 位置：`version_diff.py:362-365`、`__init__.py:53,73`
- 问题：`create_version` 实际用 max 推算版本号，该函数成死代码。
- 建议：删除；若留作公共工具应补调用或单测。

### G6 模型层死方法（💭 低）
- 位置：`shared_models/customer_sampling.py:156-180`（`CustomerSamplingProject.to_dict`）、`425-437`（`CustomerSamplingFabricVersion.to_dict`）
- 问题：全仓无调用；且 `to_dict` 内直接访问 `self.creator.username`，在 async 会话下若未预加载会抛 MissingGreenlet，属于"一调用就炸"的隐患代码。
- 建议：删除。

### G7 过渡期死导入（💭 低）
- 位置：`projects.py`（`_ensure_part_name_unique`、`_version_num` 未用）、`parts.py`（`generate_customer_sampling_number`、`func`、`or_`、`noload`、`datetime`、`_resolve_pattern_maker_name`、`_project_to_summary`、`_batch_get_image_urls`、`_get_product_image_urls` 未用）
- 问题：`# ruff: noqa: F401 - 拆分过渡期` 已持续一段时间，掩盖了真实死导入。
- 建议：删掉未用导入后移除 noqa（保留 crud.py Facade 的 noqa 是合理的）。

### G8 endpoint 模块 docstring 失效（💭 低）
- 位置：`endpoints/customer_sampling.py:1`（`import functools` 在文件最前，原 docstring 变成死字符串表达式，`__doc__` 为 None）
- 建议：把 import 移到 docstring 之后。

### G9 usePatternRoomProjectActions 死导出（💭 低）
- 位置：`usePatternRoomProjectActions.ts:78-88`（openEditProjectDialog）、`236-258`（confirmDeleteProject，删除项目确认流程）
- 问题：PatternRoomView 解构中无此二者——项目删除 UI 已被移除，但编排逻辑保留。
- 建议：删除，或恢复"删除项目"入口（产品决策）。

### G10 usePatternRoomPartActions 死导出 + 混用导入机制（💭 低）
- 位置：`usePatternRoomPartActions.ts:293-299,301-311`（openCreateVersionDialog / isCurrentVersion / onSwitchVersion）
- 问题：三者均未被 PatternRoomView 解构（isCurrentVersion 依赖 unplugin-auto-import 隐式提供 `computed`，而同文件第 8 行又显式 `import { ref }`——同文件两种导入机制并存，重构移文件时 auto-import 若关闭会直接报错）。
- 建议：修复 Bug 1 时一并清理；统一为显式导入。

### G11 PartFormDialog 死字段 + index key（💭 低）
- 位置：`PartFormDialog.vue:11`（`supplier_id` 永远为 null，输入的是 `supplier_name`）、`:key="index"`（第 115 行）
- 问题：supplier_id 无来源，纯死字段；行删除用 index 作 key，删除中间行时输入框组件复用可能引起焦点/原生状态错位。
- 建议：删 supplier_id；key 改用自增 id。

### G12 `_register_project_image_cleanup` 重复查询（💭 低）
- 位置：`upload.py:93-111`
- 问题：先查 storage_key，再 `db.get(FileRecord, file_id)` 取整行，同一行查两次。
- 建议：一次查询同时取 storage_key 与行对象。

---

## 四、代码质量 / 可维护性

### Q1 `resolveXxxErrorMessage` 四份近似重复（🟡 中）
- 位置：`useSamplingProject.ts:24`、`useSamplingPart.ts:30`、`useSamplingVersion.ts:24`、`useSamplingRole.ts:15`
- 建议：提取到 `views/pattern-room/composables/useSamplingErrors.ts`，角色文案差异用参数表达。

### Q2 `list_projects` 重复内联 noload 列表（💭 低）
- 位置：`projects.py:430-441` vs `grouping.py:45-52` 的 `_LIST_NOLOAD`
- 建议：复用 grouping 的常量（或上移到 common）。

### Q3 `update_part` 供应商清除语义 + 冗余判断（💭 低）
- 位置：`parts.py:169-179`
- 问题：外层已判 `supplier_id is not None`，内层 `if supplier_id is not None` 恒真（死分支）；且 `supplier_id=None` 永远走不到清除分支——"清除供应商"只能通过传 supplier_name 空串间接实现，语义易混。
- 建议：明确三态（不改/改/清）协议并简化代码。

### Q4 `validate_project_image` 进程级副作用 + 三重校验（🟡 中）
- 位置：`upload.py:67`（函数内修改 PIL 全局 `Image.MAX_IMAGE_PIXELS`）、endpoint:231-239（先 10MB/413 校验）、`upload_project_image:156-163`（再次 content_type/大小校验）
- 问题：函数体内改全局常量影响整个进程的解压炸弹防护（其他上传路径也被放宽到 2 亿像素，200MP RGB 解码≈600MB 内存）；同一上传链路三处重复校验。
- 建议：`MAX_IMAGE_PIXELS` 在模块加载时设置一次并评估数值（可考虑降到 50-80MP）；`upload_project_image` 内的重复校验删除（信任 validate_project_image）。

### Q5 CustomerGroupSearchBar 状态单向快照（🟡 中）
- 位置：`CustomerGroupSearchBar.vue:45`（`ref(props.statusFilter)`）、`CustomerGroupList.vue:4`（`status-filter="in_progress"` 写死常量）
- 问题：prop 恒为常量，子组件把 prop 复制成内部 ref 后父级 `statusFilter`（usePatternRoomGroupFilter）与 UI 选中态仅靠事件单向同步；一旦父级重置（如 keep-alive 恢复、未来加"重置筛选"），UI 与实际查询条件漂移。
- 建议：删除内部复制，直接渲染受控 prop；CustomerGroupList 把真实 `statusFilter` 传下来。

### Q6 useSamplingVersion 两条数据流共享一个竞态计数器（💭 低）
- 位置：`useSamplingVersion.ts:50`（`_requestId` 同时守卫 fetchVersions 与 fetchVersionDetail）
- 问题：列表请求在途时用户点开版本详情，会使列表响应被守卫丢弃（反之亦然），出现"列表不更新"的偶发现象。
- 建议：拆成两个计数器。

### Q7 sessionStorage 缓存失效缺口（🟡 中）
- 位置：`stores/patternRoom.ts:152-154,189-191`（invalidateGrouped/invalidateMakers 只清内存不重写 sessionStorage）
- 问题：写操作使内存缓存失效后，若用户不触发重查即 F5，恢复逻辑会把**写操作前的旧快照**当缓存用（虽然 30s 新鲜期大概率已过、会后台刷新，但存在短暂展示旧数据窗口）；另多标签页写操作互相不可见（sessionStorage 天然隔离）。
- 建议：`invalidate*` 时同步 `persist()`（写入空/删除条目）；接受多标签页限制或换 localStorage + 版本戳。

### Q8 查看历史版本被写权限门控（🟡 中，交互设计）
- 位置：`PartsVersionRowV2.vue:27`（版本 chip `:disabled="!canManage"`）→ `usePartsVersionFilter.toggleVersion`（选中即调 `onSetFinalVersion` 发 PUT）
- 问题：版本 chip 同时承担"查看该版本"与"设为最终版本"两个语义，且查看动作被 `customer_sampling_manage` 写权限禁用——只读用户完全无法查看历史版本；同时"点一下就写库+toast"容易误触改状态。
- 建议：把"查看/折叠"与"设为最终版本"拆成两个动作（chip 点击=查看，显式按钮=设最终版本），查看不再要求写权限。

### Q9 打印编号与卡片编号口径不一致（💭 低）
- 位置：`PrintDialog.vue:91-95`（`YYYYMMDD01` 固定序号）vs `useProjectGrouping.ts:39-62`（同日递增序号）
- 建议：统一编号生成规则（打印可直接复用 projectDisplayNumbers 传参）。

### Q10 杂项（💭 低）
- `useSamplingPart.create()` 全量刷新 vs `appendPart` 局部追加两套策略并存（见 P4）。
- `usePatternRoomPrint.handlePrint` 降级 `catch {}` 静默吞错，至少 console.warn。
- `onSaveEditData`（usePatternRoomPartActions.ts:242）手写 `(e as ...)?.response?.status` 取状态码，项目已有 `getErrorStatus`。
- `grouping.py:154` 分组排序 key 用格式化字符串比较时间（`YYYY-MM-DD HH:MM:SS` 字典序碰巧正确），改存 datetime 更稳。
- `parts.py:281` 函数内局部 `from ... import Supplier`，应上移。
- `pattern_maker_service.py:62` 函数内局部 import NotFoundError，应上移。
- `grouping.py:292-294` `if row.project_id not in operator_map`：DISTINCT ON 已保证每项目一行，判断冗余（无害）。
- 模型注释 vs 实际：`grouping.py:41` 注释称模型默认 `lazy='selectin'`，实际模型为 `lazy='select'`（`shared_models/customer_sampling.py:115` 等），注释过时易误导。

---

## 五、优先级优化清单（按投入产出排序）

| 优先级 | 事项 | 类型 | 预期收益 |
|---|---|---|---|
| 1 | 修复「创建新版本」按钮事件断链（Bug 1） | Bug | 恢复核心功能，改动 1 行 |
| 2 | 修复编辑弹窗移除图片/清空备注失效（Bug 2、3） | Bug | 数据一致性，改动 ~10 行 |
| 3 | 打印改用"仅最终版本"查询（P1） | 性能 | 打印网络传输与后端 IO 降低约 (平均版本数) 倍；多角色项目体感最明显 |
| 4 | grouped-list 分组下推 DB 分页 + 当前页才构建 summary/图 URL（P2） | 性能 | 大数据量下列表接口 CPU/内存放大约 10-100 倍的问题根治 |
| 5 | get_project_detail / list_versions 去除 snapshot_data 加载（P3） | 性能 | 详情接口延迟与传输随版本数线性下降，改动小收益稳定 |
| 6 | 删除 completed-table 全链路（G1）+ useSamplingPart 死方法（P4/G 系列） | 垃圾清理 | 去除约 300+ 行死代码，降低维护噪音 |
| 7 | 合并 _SNAPSHOT_FIELDS 7 份 / 删除冲突常量 / 收敛 docstring（G2-G4） | 垃圾清理 | 消除"改字段清单漏改 6 处"类隐患 |
| 8 | validate_project_image 全局副作用收敛 + 去重校验（Q4） | 质量/安全 | 恢复全站解压炸弹防护强度，删除重复逻辑 |
| 9 | SearchBar 状态受控化（Q5）+ 查看版本与设最终版本解耦（Q8） | 交互 | 消除筛选漂移与只读用户不可见历史版本的问题 |
| 10 | sessionStorage 失效同步（Q7）、错误消息合并（Q1）、杂项（Q10） | 质量 | 一致性与可维护性小步提升 |

## 六、总体评价

该模块整体质量**良好偏好**：后端拆分清晰（endpoint 薄、服务子包职责明确）、乐观锁+行锁+advisory lock 并发控制到位、审计日志完备、pg_trgm 索引意识好；前端竞态守卫（requestId/viewKey/seq）、SWR 缓存、虚拟滚动、局部 patch、图片 blur-up 与压缩等都是扎实工程。主要问题集中在：**一次重构丢失的事件绑定（创建新版本）**、**打印路径的全量数据拉取**、**分组列表的应用层全量分组**，以及拆分过渡期遗留的**成体系死代码**。前 5 项修完即可获得绝大部分收益。

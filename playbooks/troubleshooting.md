# 故障排查手册

## BUG-HTTP-405-Form-Submit | 2026-04-22
- **现象**: 供应商管理添加表单及其他多个模块编辑表单提交时返回 HTTP 405 (Method Not Allowed)
- **根因**: HTML模板使用 `<form method="POST">` 原生提交到页面路由，但页面路由仅有GET处理器
- **解决**: 添加 `onsubmit="return false;"` + JavaScript fetch() 提交到JSON API端点
- **参考**: [docs/bugs/BUG-HTTP-405-Form-Submit.md](../docs/bugs/BUG-HTTP-405-Form-Submit.md)

## BUG-customer-order-blank-page | 2026-04-22
- **现象**: "客户订单"模块"备货管理"页面空白或不显示
- **根因**: FastAPI 页面路由函数使用 `_shell_page()` 但未传递模板所需的业务数据变量（customers、orders_json等），导致 Jinja2 渲染失败或 JS 语法错误
- **解决**: 修改 `pages.py` 中 `customer_order_page`、`stockin_page`、`stockout_page` 路由函数，显式查询并传递完整模板上下文
- **参考**: [docs/bugs/BUG-customer-order-blank-page.md](../docs/bugs/BUG-customer-order-blank-page.md)

## 通用排查模式：页面空白/不显示

当任何页面出现空白或不显示时，按以下步骤排查：

1. **检查路由函数是否传递了模板所需的变量**
   - 对比模板中 `{{ variable }}` 和 `{% for x in variable %}` 的使用
   - 确认路由函数通过 `_shell_page(extra_ctx=...)` 或直接 `ctx.update({...})` 传递了所有变量

2. **检查 Jinja2 UndefinedError**
   - 模板中 `{% for x in undefined_var %}` 会导致渲染失败
   - 查看服务端日志确认是否有 500 错误

3. **检查 JS 语法错误**
   - `{{ json_var | safe }}` 若变量为空，会渲染为 `= ;` 导致 JS 错误
   - 传入默认值如 `'[]'` 或 `'{}'` 避免

4. **检查 Tab 系统**
   - 确认 `data-tab-container`、`data-tab`、`data-tab-panel` 属性正确配对
   - 默认显示的 Tab 面板需要有 `active` class

## 通用排查模式：表单提交405错误

1. **检查HTML表单提交方式**
   - `<form method="POST">` 原生提交会发送POST到当前页面URL
   - 页面路由通常只有 `@router.get()`，导致405

2. **修复方法**
   - 添加 `onsubmit="return false;"` 阻止原生提交
   - 使用JavaScript `fetch()` 提交到JSON API端点

3. **检查Flask/FastAPI兼容性**
   - `request.args` 是Flask特有属性，FastAPI/Starlette中使用 `request.query_params`

4. **检查编辑页数据加载**
   - 页面路由需查询实体数据并传递给模板，仅传ID不够
## BUG-PURCHASE-SUMMARY-500 | 2026-04-23
- **鐜拌薄**: 閲囪喘涓績姹囨€讳笅鍗?500 Internal Server Error (factory-summary + supplier-summary)
- **鏍瑰洜**: 鏈嶅姟鍑芥暟杩斿洖 list锛岀鐐圭敤 `**` 瑙ｅ寘 dict 瀵艰嚧 TypeError
- **瑙ｅ喅**: 閲嶆瀯鏈嶅姟杩斿洖 dict 缁撴瀯锛屽尮閰嶅墠绔湡鏈涚殑 groups/suppliers/fabrics 鍜?materials 鏍煎紡
- **鍙傝€?*: docs/bugs/BUG-PURCHASE-SUMMARY-500.md

## BUG-PURCHASE-SUMMARY-500 瀹℃牳杩藉姞淇 | 2026-04-23
- **鐜拌薄**: 鍒濇淇鍚庡鏍稿彂鐜?product_quantity 瀵规墍鏈?group 閲嶅绱姞鍏ㄩ儴璁㈠崟鏁伴噺
- **鏍瑰洜**: group 閬嶅巻鏃朵娇鐢ㄥ叏閲?order_ids 鑰岄潪璇?group 鍏宠仈鐨?order_ids 瀛愰泦
- **瑙ｅ喅**: 鍦ㄥ垎缁勬椂鐢?set 杩借釜姣忎釜 group 鐨?order_ids锛屾眹鎬绘椂浠呭彇瀛愰泦
- **鍙傝€?*: docs/bugs/BUG-PURCHASE-SUMMARY-500.md

## BUG-PURCHASE-ORDER-FIELDS-MISSING | 2026-04-23
- **鐜拌薄**: 閲囪喘涓績璁㈠崟鍒楄〃鐨勫鎴峰悕绉?浜у搧鍚嶇О/璁㈠崟鏁伴噺鍒椾负绌?- **鏍瑰洜**: 鏈嶅姟鍑芥暟鎵嬪姩鏋勯€犲搷搴?dict 鏃堕仐婕?product_name/quantity/order_date 瀛楁
- **瑙ｅ喅**: 琛ュ厖缂哄け瀛楁鑷?get_purchase_orders 鍜?get_purchase_order 鍝嶅簲 dict
- **鍙傝€?*: docs/bugs/BUG-PURCHASE-ORDER-FIELDS-MISSING.md

## BUG-ORDER-SYNC-TO-PURCHASE | 2026-04-23
- **鐜拌薄**: 瀹㈡埛璁㈠崟鏂板鍚庨噰璐腑蹇冩棤瀵瑰簲閲囪喘璁㈠崟
- **鏍瑰洜**: create_order 鏈Е鍙戦噰璐鍗曞悓姝ワ紝闇€鎵嬪姩涓€閿敓鎴?- **瑙ｅ喅**: 鍦ㄨ鍗曞垱寤哄悗鑷姩璋冪敤 one_click_generate_order锛宐est-effort 闅旂
- **鍙傝€?*: docs/bugs/BUG-ORDER-SYNC-TO-PURCHASE.md

## BUG-MATERIAL-CALC-UNDEFINED | 2026-04-23
- **现象**: 物料用量计算页面报错 "Cannot convert undefined or null to object"
- **根因**: 前端 JS 访问 result.result 但 API 返回扁平结构（无 result 嵌套键）；后端字段名 name/quantity_per_unit 与 to_dict() 返回的 material_name/unit_usage 不匹配
- **解决**: 参考 [docs/bugs/BUG-MATERIAL-CALC-UNDEFINED.md](../docs/bugs/BUG-MATERIAL-CALC-UNDEFINED.md)

## BUG-UI-STOP-STATE | 2026-04-23
- **现象**: 点击停止按钮后，UI 状态标签仍显示"运行中"，不更新为"已停止"
- **根因**: `_stop_mode()` 和 `stop_all()` 设置 `self._mode='none'` 后未立即调用 `_update_all_ui()`，UI 更新依赖后台 `_kill_worker` 线程完成后的异步队列消息，延迟可达数秒
- **解决**: 在 `self._mode='none'` 赋值后立即调用 `self._update_all_ui()`
- **参考**: [docs/bugs/BUG-UI-STOP-STATE.md](../docs/bugs/BUG-UI-STOP-STATE.md)

## 通用排查模式：GUI 状态不同步

当 GUI 操作后 UI 状态未更新时，按以下步骤排查：

1. **检查状态变更后是否调用了 UI 刷新方法**
   - 状态变量赋值（如 `self._mode = 'none'`）不会自动触发 UI 更新
   - 必须显式调用 `_update_all_ui()` 或等效刷新方法

2. **检查异步操作的 UI 更新时机**
   - 后台线程中的 UI 更新必须通过 `queue + root.after()` 调度到主线程
   - 主线程中可以直接调用 UI 更新方法，无需经过队列

3. **避免仅依赖异步回调刷新 UI**
   - 即使后台操作会触发 UI 刷新，主线程中也应立即刷新一次
   - 异步回调作为二次确认，而非唯一刷新途径

## BUG-sidebar-disappear | 2026-04-27
- **现象**: Dashboard 左侧导航栏在点击功能区多次后或放大缩小 UI 后消失
- **根因**: sidebar 作为 flex 子项缺少 `flex-shrink:0`，viewport 缩小时被压缩至 0 宽度；无响应式处理
- **解决**: 添加 `flex-shrink:0` + `min-width:68px` 防压缩；添加移动端 `@media` + overlay 适配
- **参考**: [docs/bugs/BUG-sidebar-disappear.md](../docs/bugs/BUG-sidebar-disappear.md)

## 通用排查模式：前端布局元素消失

当页面中某个布局元素（导航栏、侧边栏等）在缩放或操作后消失时：

1. **检查 flex 子项是否缺少 `flex-shrink: 0`**
   - flex 容器空间不足时，默认 `flex-shrink: 1` 会导致子项被压缩
   - 固定宽度元素（如 sidebar）必须设置 `flex-shrink: 0`

2. **检查是否有 `min-width` 保护**
   - 没有 `min-width` 的元素可被压缩至 0 宽度

3. **检查 `overflow: hidden` 是否裁剪了被挤压的元素**
   - 父容器 `overflow: hidden` 会使被挤出可视区的元素完全不可见

4. **检查是否有响应式适配**
   - 缩放页面会改变 CSS viewport 宽度，需要 `@media` 查询或 `resize` 监听适配

## BUG-AUTO-20260428-210353 | 2026-04-28
- **现象**: 客户订单创建后，采购中心审核订单中看不到该订单
- **根因**: 1) get_unprocessed_orders() 过滤 has_bom=False 的订单；2) _sync_order_to_purchase_center() 使用 user_id=0 违反外键约束；3) atch_create_orders() 在事务提交前调用同步
- **解决**: 移除BOM过滤、动态查找管理员用户、同步移至事务提交后、新增WebSocket实时通知
- **关键检查点**: 
  - 订单同步是否在 db.commit() 之后调用
  - 自动同步的用户ID是否在user表中真实存在
  - has_bom=False 的订单是否被正确展示（仅禁用审核按钮）
- **参考**: [docs/bugs/BUG-AUTO-20260428-210353.md](../docs/bugs/BUG-AUTO-20260428-210353.md)

## BUG-PURCHASE-UI-FIX-20260428 | 2026-04-28
- **现象**: 采购中心全选按钮不工作、一键审核/汇总下单/批量确认按钮disabled、下单时间不显示、下单完成422错误
- **根因**: 1) UiCheckbox与reka-ui API不匹配(checked vs modelValue); 2) completeOrder发id而非order_id; 3) 下单时间显示order_date而非create_time; 4) batchComplete引用过期selectedIds
- **解决**: 修改UiCheckbox内部映射、修正API字段名、更换时间字段、修复过期引用
- **关键检查点**:
  - reka-ui v2 组件使用 modelValue/update:modelValue (v-model模式)
  - 后端 OrderIdRequest 字段名是 order_id 不是 id
  - 采购订单有两个时间字段: order_date(日期) 和 create_time(日期+时分)
- **参考**: [docs/bugs/BUG-PURCHASE-UI-FIX-20260428.md](../docs/bugs/BUG-PURCHASE-UI-FIX-20260428.md)

## BUG-MATERIAL-CALC-FLICKER | 2026-04-29
- **现象**: 物料计算器页面多选SKU时结果区域出现闪屏
- **根因**: v-if/v-else 三分支导致结果DOM在calculating时被销毁重建，配合从opacity:0开始的fade-in-up动画
- **解决**: 参考 [docs/bugs/BUG-MATERIAL-CALC-FLICKER.md](docs/bugs/BUG-MATERIAL-CALC-FLICKER.md)

## BUG-permission-save-500 | 2026-04-30
- **现象**: 分配权限保存时 POST /api/v1/users/permission/{user_id} 返回 500
- **根因**: 异步 SQLAlchemy 中 db.get 未预加载关系属性，访问时触发 MissingGreenlet
- **解决**: 使用 select().options(selectinload()) 预加载关系，参考 [docs/bugs/BUG-permission-save-500.md](docs/bugs/BUG-permission-save-500.md)
- **通用规则**: 在 async SQLAlchemy 中，所有需要访问的关系属性必须在查询时 eager-load，禁止依赖懒加载

## BUG-CACHE-DUPLICATION | 2026-04-30
- **鐜拌薄**: 缂撳瓨澶辨晥閫昏緫鍦?7 涓枃浠朵腑閲嶅 18+ 娆★紝鍙傛暟椤哄簭涓嶄竴鑷达紝approval reject 閬楁紡 inventory:* 澶辨晥
- **鏍瑰洜**: 缂轰箯缁熶竴缂撳瓨澶辨晥鎶借薄锛屾瘡涓湇鍔″嚱鏁扮洿鎺ヨ皟鐢?invalidate_cache() 纭紪鐮?pattern
- **瑙ｅ喅**: 寮曞叆 CacheDomain Flag 鏋氫妇 + invalidate_related_caches() 鍑芥暟闆嗕腑绠＄悊缂撳瓨鍩熸槧灏?- **鍙傝€?*: [docs/bugs/BUG-CACHE-DUPLICATION.md](docs/bugs/BUG-CACHE-DUPLICATION.md)
- **閫氱敤瑙勫垯**: 鏂板缂撳瓨鍩熸椂鍙渶淇敼 cache.py 鐨?CacheDomain 鏋氫妇鍜?_DOMAIN_PATTERN_MAP锛屾棤闇€淇敼涓氬姟浠ｇ爜


## BUG-CACHE-CANCEL-APPROVAL | 2026-04-30
- **现象**: 取消审批或非管理员提交删除审批后，订单列表中 is_locked 字段最长 60s 内显示旧值
- **根因**: cancel_approval 和 delete_order 非管理员路径在 db.commit() 后未调用 invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)
- **解决**: 补齐缓存失效调用，与 approve/reject/update_order 保持一致
- **通用规则**: 所有修改订单/审批状态的路径，commit 后必须调用 invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)

## BUG-AUDIT-93 | 2026-05-03
- **现象**: 代码审核发现93个问题（6 P0, 19 P1, 42 P2, 13 P3），涵盖核心交易链、产品物料、报表、系统管理
- **根因**: 多类别：SQLAlchemy过滤器失效（not vs == False）、事务回滚范围错误、输入校验缺失、SQL注入风险、并发安全（缺少FOR UPDATE）
- **解决**: 实际修复37个bug，4个已存在保护，39个为架构设计建议。详见 [docs/bugs/BUG-AUDIT-93.md](../docs/bugs/BUG-AUDIT-93.md)
- **关键检查点**:
  - SQLAlchemy WHERE 中 `not Model.field` 不生成正确SQL，必须用 `Model.field == False` 或 `~Model.field`
  - 异步事务中 `db.rollback()` 回滚整个事务，用 `db.begin_nested()` 创建 savepoint
  - 库存变更前必须预检查（pre-mutation check），不能先修改再检查
  - 临时文件写入使用 `os.write(fd, content)` 避免 TOCTOU 竞态
  - 编号生成必须用 `with_for_update()` 行锁防止并发重复

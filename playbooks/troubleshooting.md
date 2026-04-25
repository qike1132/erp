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

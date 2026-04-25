# BUG-HTTP-405-Form-Submit 修复记录

- **修复时间**: 2026-04-22
- **根因分析**: 9个HTML模板使用 `<form method="POST">` 原生浏览器提交，但页面路由仅定义了 `@router.get()`，导致POST请求返回405 Method Not Allowed。同时，编辑页面路由仅传递ID而未查询实体数据，导致模板中的Jinja2变量无法渲染。
- **影响范围**: supplier.html, edit_supplier.html, edit_customer.html, edit_product.html, edit_stockin.html, edit_stockout.html, edit_order.html, edit_user.html, permission.html
- **修复方案**:
  1. 所有9个模板添加 `onsubmit="return false;"` 阻止原生表单提交，改用JavaScript `fetch()` 调用JSON API
  2. 7个编辑页面路由（pages.py）从 `_shell_page()` 改为查询数据库获取实体数据并传递给模板
  3. supplier.html 从Jinja2服务端渲染改为JS动态加载供应商列表
  4. edit_product.html 修复Flask式 `request.args` 为FastAPI兼容写法
  5. 所有编辑页面路由添加实体不存在时的重定向处理
  6. 修复edit_order_page中StockIn模型不存在order_id字段的错误
- **验证结果**: 所有页面加载200 OK，所有API表单提交正常，无405错误

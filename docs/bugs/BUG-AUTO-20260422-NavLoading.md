
# BUG-AUTO-20260422-NavLoading 修复记录

- **修复时间**: 2026-04-22 10:36:55
- **Git Commit**: 215ee3c246501153bdfaa3313b3e5a71aa03a7c1
- **根因分析**: pages.py _page_context() 使用同步 get_nav_sections()，该函数在冷启动缓存未命中时无法执行数据库查询，只能返回空 dict {}，导致导航栏显示'导航加载中...'。同时 nav_context.py 的 get_nav_sections_async() 之前使用 async_engine.connect() 而非 AsyncSession，ORM 查询返回 int 而非 Permission 对象，也是导航数据为空的原因之一。
- **影响范围**: 所有服务器重启后的首次页面访问，导航栏显示'导航加载中...'，直到调用 /api/v1/dashboard/nav-sections 异步接口填充缓存后才能正常显示
- **修复方案**:
  1. nav_context.py:97 将 `async_engine.connect()` 替换为 `_AsyncSessionLocal()` 确保 ORM 查询正确加载 Permission 对象
  2. pages.py:31 将 `await run_in_threadpool(get_nav_sections)` 替换为 `await get_nav_sections_async()` 使用异步版本直接查询数据库
- **修复文件**: `fastapi_app/core/nav_context.py`, `fastapi_app/api/v1/endpoints/pages.py`
- **验证结果**: 冷启动首次请求 17 个页面全部导航正常，Nav API 返回 5 分区 16 项数据

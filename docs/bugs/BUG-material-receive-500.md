# BUG-AUTO-20260423-收货登记500 修复记录

- **修复时间**: 2026-04-23
- **根因分析**: `receive_material` 服务使用 `db.get()` 获取 `MaterialRegistrationItem`，未 eager load `registration` 关系属性。在异步 SQLAlchemy 中，访问延迟加载的关系属性触发 `MissingGreenlet` 异常，导致 500 错误。同时端点返回空 `registration: {}` 而非实际数据。
- **影响范围**: 所有来料登记的收货登记操作（POST /api/v1/material-registrations/items/{id}/receive）
- **修复方案**:
  1. 将 `db.get(MaterialRegistrationItem, item_id)` 改为 `db.execute(select(...).options(joinedload(registration).selectinload(items)))`，一次性加载 item + registration + sibling items
  2. 端点返回 `RegistrationDetailResponse(registration=result['registration'])` 替代空 dict
  3. 更新对应单元测试的 mock 方式
- **修改文件**:
  - `fastapi_app/services/material_registration_service.py:212-241`
  - `fastapi_app/api/v1/endpoints/material_registration.py:132-138`
  - `fastapi_app/tests/test_material_registration.py:97-109`
- **验证结果**: 17/17 测试通过，bandit 安全扫描 0 高危漏洞

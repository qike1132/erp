# BUG-permission-save-500 修复记录

- **修复时间**: 2026-04-30 09:36:09
- **Git Commit**: ca097be5812c55bbe4e83ebaa5cd2c2275e28d4b
- **根因分析**: user_service.update_user_permissions 使用 db.get(User, user_id) 获取用户对象，未预加载 permissions 关系。在异步 SQLAlchemy 中，user.permissions.clear() 触发懒加载，但异步上下文不支持同步懒加载，抛出 MissingGreenlet 异常，导致 500。
- **影响范围**: 所有调用 POST /api/v1/users/permission/{user_id} 保存权限的操作均失败
- **修复方案**: 将 db.get(User, user_id) 替换为 select(User).options(selectinload(User.permissions)).where(User.id == user_id) 查询，预加载 permissions 关系
- **变更文件**:
  - astapi_app/services/user_service.py - 使用 selectinload 预加载权限
  - astapi_app/tests/test_user.py - 更新 mock 测试匹配新查询方式
  - rontend-vite/src/views/user/UserView.vue - 修复字段名 user_permission_ids vs permission_ids 不匹配
- **验证结果**: 39 tests passed, bandit 0 high/medium, health 3/3 OK

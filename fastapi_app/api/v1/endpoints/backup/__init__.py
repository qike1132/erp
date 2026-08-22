"""数据备份与恢复 API — 包入口

所有业务逻辑委托给 backup_service.py。
原单一 backup.py（约 2100 行）按功能拆分为子路由模块，URL / 请求响应 schema /
权限码与拆分前完全一致：

- records.py:    备份记录查询、状态、调度与删除（8 路由）
- export.py:     备份创建与导出（6 路由）
- restore.py:    备份导入与恢复（6 路由）
- validation.py: 验证、健康检查与统计（6 路由）
- _deps.py:      公共依赖（权限工厂、后台任务句柄、加密辅助）

主要功能：
1. 备份管理：创建、恢复、删除备份
2. 加密支持：默认启用AES-256-GCM加密，支持密码和环境变量
3. 大文件分片传输：支持Range请求头和分片下载
4. 细粒度权限控制：backup_read、backup_create、backup_restore、backup_delete、backup_manage
5. 健康检查：系统状态监控
6. 备份验证：文件完整性检查和验证缓存
7. 统计信息：备份系统运行统计

权限说明：
- backup_read: 查看备份列表和状态
- backup_create: 创建备份
- backup_restore: 恢复备份
- backup_delete: 删除备份
- backup_manage: 管理备份（所有权限）
"""
from fastapi import APIRouter

from fastapi_app.api.v1.endpoints.backup import actions, export, records, restore, settings, validation
from fastapi_app.services import backup as backup_service

router = APIRouter()
router.include_router(records.router)
router.include_router(export.router)
router.include_router(restore.router)
router.include_router(validation.router)
router.include_router(actions.router)
router.include_router(settings.router)

# 兼容常量（供 Celery 旧导入过渡期使用，后续可移除）
BACKUP_DIR = backup_service.BACKUP_DIR
BACKUP_FORMAT_VERSION = backup_service.BACKUP_FORMAT_VERSION

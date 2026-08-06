# 事务边界管理规范

> **版本**：v1.0  
> **生效日期**：2026-06-18  
> **目标**：统一全系统事务边界，消除 service 层直接提交主 session 导致的数据不一致风险

## 一、核心原则

### 1.1 两层事务模型

| 层级 | 职责 | 是否允许 commit | 典型场景 |
|---|---|---|---|
| **Endpoint / 主流程编排** | 统一控制业务事务边界 | ✅ 允许 | API 接口、后台任务入口 |
| **Service / 工具函数** | 执行业务逻辑、数据操作 | ❌ 禁止（除独立事务） | CRUD、计算、校验 |
| **独立事务工具** | 在 service 内创建新 session 处理原子操作 | ✅ 允许 | 编号生成、审计日志、访问日志 |

### 1.2 规则

1. **service 层函数接收调用方传入的 `db: AsyncSession`，不得调用 `await db.commit()`**
2. **所有写操作 endpoint 必须使用 `async with db_transaction(db):` 包裹**
3. **只有在独立 session 中才可 commit**（例如 `get_async_db_context()`、嵌套事务 `async_session.begin_nested()`）
4. **查询函数禁止调用 `db.flush()` 或 `db.commit()`**
5. **后台任务（tasks/）使用 `get_async_db_context()` 自主管理事务**

## 二、推荐写法

### 2.1 Endpoint 层

```python
from fastapi_app.core.database import get_async_db
from fastapi_app.core.exceptions import db_transaction

@router.post('/create')
async def create_item(data: ItemCreate, db: AsyncSession = Depends(get_async_db)):
    async with db_transaction(db):
        result = await item_service.create_item(db, data.model_dump())
    return ActionResponse(message='创建成功', data=result)
```

### 2.2 Service 层

```python
async def create_item(db: AsyncSession, data: dict) -> dict:
    item = Item(name=data['name'])
    db.add(item)
    await db.flush()  # 生成 ID，但不提交
    return {'id': item.id, 'name': item.name}
```

### 2.3 独立事务

```python
# 编号生成等需要独立 commit 的场景
async def generate_number(prefix: str) -> str:
    async with get_async_db_context() as db:
        # ... 查询并更新编号
        await db.commit()
        return number
```

## 三、迁移策略

### 3.1 已改造模块（P0-02）

| 模块 | 处理 commit 数量 | 状态 |
|---|---|---|
| purchase_supplier_service.py | 3 | ✅ 已完成 |
| production_plan_service.py | 5 | ✅ 已完成 |
| purchase_history_service.py | 3 | ✅ 已完成 |
| product_service.py | 3 | ✅ 已完成 |
| purchase_product_service.py | 1 | ✅ 已完成 |
| daily_production_service.py | 3 | ✅ 已完成 |
| stock_service.py | 9 | ✅ 已完成 |
| purchase_plan_crud.py | 10 | ✅ 已完成 |
| purchase_order_crud.py | 6 | ✅ 已完成 |
| staging_service.py | 11 | ✅ 已完成 |
| production_summary_service.py | 7 | ✅ 已完成 |
| backup_service.py | 4 | ✅ 已完成 |
| backup_policy_service.py | 1 | ✅ 独立事务标记 |
| backup_cleanup_service.py | 1 | ✅ 独立事务标记 |
| backup_alert_service.py | 1 | ✅ 独立事务标记 |
| batch_import_service.py | 1 | ✅ 已完成 |
| ocr_service.py | 1 | ✅ 已完成 |
| batch_pipeline.py | 1 | ✅ 已完成 |
| staging_utils.py | 1 | ✅ 已完成 |

### 3.2 已补充 endpoint 事务包裹

| 端点文件 | 包裹写操作 |
|---|---|
| api/v1/endpoints/staging_order.py | clear / import / update / delete / confirm |
| api/v1/endpoints/staging_stockin.py | import / update / clear / delete / confirm |
| api/v1/endpoints/staging_stockout.py | import / update / clear / delete / confirm |
| api/v1/endpoints/purchase_center/order_routes.py | create / update / delete / complete / batch-complete / batch-delete / save-factory-summary |
| api/v1/endpoints/ocr_import.py | upload |
| api/v1/endpoints/backup.py | import / save / restore-by-name / save-incremental / restore-incremental |

### 3.3 已知遗留/例外

| 位置 | 说明 |
|---|---|
| api/v1/endpoints/batch.py | 端点内部显式调用 `db.commit()` / `db.rollback()` 进行逐行错误恢复，未改为 `db_transaction`，属于端点层自我管理事务，暂不阻塞 P0-02。 |
| api/v1/endpoints/auth.py | 登录/注册流程涉及显式提交，需单独评估。 |

## 四、CI 检测

```bash
# 扫描 service 层非法 commit
python scripts/check_service_commit.py
```

检测规则：
- 扫描 `fastapi_app/services/` 下所有 `.py` 文件
- 排除明确允许独立事务的函数（如 `generate_*`、`log_*`）
- 发现 `await db.commit()` 或 `await session.commit()`（非 nested/short_session）则报错

## 五、验收标准

1. 所有新增 service 函数不得包含 `await db.commit()`
2. 所有写操作 endpoint 必须使用 `db_transaction`
3. `python scripts/check_service_commit.py` 通过
4. 已改造模块的相关单元测试通过

## 六、参考文件

- [fastapi_app/core/database.py](file:///d:/erp_system/fastapi_app/core/database.py)
- [fastapi_app/core/exceptions.py](file:///d:/erp_system/fastapi_app/core/exceptions.py)
- [fastapi_app/api/v1/endpoints/order.py](file:///d:/erp_system/fastapi_app/api/v1/endpoints/order.py)

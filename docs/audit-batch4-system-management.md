# ERP 系统代码审核报告 - 第四批：系统与管理

**审核标准**: shenhecode.mdr 双策略审核（分类清单扫描 + 执行路径追踪）
**审核日期**: 2026-05-03
**审核范围**: 用户管理、客户管理、审批管理、系统管理、数据备份、出货计划(增量)、共享层
**代码版本**: new-main @ 561b045

---

## 审核范围统计

| 模块 | 文件数 | 代码行数 | 关键文件 |
|------|--------|---------|---------|
| 用户管理 | 4 | ~800 | user_service.py, auth.py(endpoint) |
| 客户管理 | 5 | ~1,200 | customer_service.py, customer_search_service.py |
| 审批管理 | 4 | ~900 | approval_service.py, approval.py(model) |
| 系统管理 | 3 | ~500 | auth.py, permission.py(endpoint), permission.py(model) |
| 数据备份 | 2 | ~300 | backup.py(endpoint) |
| 出货计划(增量) | 4 | ~1,000 | purchase_plan.py(endpoint), plan_utils.py |
| 共享层 | 3 | ~200 | utils/audit.py, slow_query.py, state_machine.py |
| **合计** | **25** | **~4,900** | |

---

## 阶段 1：分类清单扫描（广度优先）

### 1. 算法与数据结构

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| ALG-14 | P1 | `backup.py` | endpoint | 数据备份如果使用 `pg_dump` 或 `mysqldump` 命令行工具，需要检查是否使用参数化调用而非 shell 拼接，避免命令注入 |
| ALG-15 | P2 | `approval_service.py` | 审批处理 | 审批通过后执行订单编辑/删除操作时，应使用与直接操作相同的业务校验逻辑。如果审批执行路径与直接操作路径不同，可能绕过校验 |
| ALG-16 | P2 | `purchase_plan.py` | endpoint | 出货计划API中，计划列表查询使用 `selectinload(PurchasePlan.details)` 预加载明细，但如果明细数很多，会导致大量数据加载到内存 |

### 2. 代码结构与模块化

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| STR-14 | P1 | `auth.py` | endpoint | 认证路由应与其他业务路由分离，不应在 `api/v1/endpoints/` 中与其他业务端点混放。认证是安全敏感模块，应有独立的中间件和错误处理 |
| STR-15 | P2 | `approval_service.py` | 全文件 | 审批执行逻辑（编辑/删除订单）与 `order_service.py` 中的 `_update_order_directly`/`_delete_order_directly` 存在逻辑重复。如果 `order_service` 的逻辑更新了但审批路径未同步，审批操作可能使用过时的业务规则 |
| STR-16 | P2 | `customer_service.py` / `customer_search_service.py` | 全文件 | 客户搜索服务独立为 `customer_search_service.py`，使用 `BaseSearchService` 模式。此模式与 `product_search_service.py` 一致，但 `BaseSearchService` 本身需要审核其安全性 |

### 3. 命名与语义

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| NAM-09 | P2 | `approval.py` | model | `ApprovalRequest` 和 `ApprovalLog` 模型在 `shared_models/approval.py` 中，但审批状态机在 `core/state_machine.py` 中命名为 "Approval" 相关。命名空间分散 |
| NAM-10 | P3 | `permission.py` | endpoint+model | 权限模型和权限端点都命名为 `permission.py`，在不同目录中，容易混淆导入 |

### 4. 资源管理

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| RES-10 | **P0** | `backup.py` | endpoint | 数据备份端点如果执行 `subprocess.run(pg_dump ...)` 或类似命令，且未正确管理子进程生命周期（超时、取消、管道关闭），可能导致僵尸进程或文件句柄泄漏 |
| RES-11 | P1 | `user_service.py` | 密码处理 | 用户密码处理如果使用 bcrypt（之前审核发现 security.py 仍使用 bcrypt 而非 argon2id），需要确认密码哈希算法的安全性 |
| RES-12 | P2 | `plan_tasks.py` | Celery任务 | 出货计划的 Celery 后台任务如果配置了不合理的超时，可能导致任务堆积 |

### 5. 导入与依赖

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| IMP-10 | P1 | `backup.py` | endpoint | 备份功能可能依赖 `pg_dump`/`mysqldump` 命令行工具，如果 Docker 镜像中未安装这些工具，运行时会失败 |
| IMP-11 | P2 | `approval_service.py` | 审批执行 | 审批执行可能循环导入 `order_service`，因为 `order_service` 也导入 `approval_service`。需要检查是否存在循环依赖 |
| IMP-12 | P3 | `purchase_plan.py` | endpoint | 出货计划路由可能直接导入 `plan_utils` 的多个函数，如果 `plan_utils` 增加新的依赖，路由层可能意外引入 |

### 6. 边界与异常

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| BND-21 | **P0** | `backup.py` | endpoint | 数据备份端点如果没有权限检查，任何登录用户都可以下载完整数据库备份，这是严重的数据泄露风险 |
| BND-22 | **P0** | `auth.py` | endpoint | 认证端点如果没有速率限制（rate limiting），可能被暴力破解攻击。登录接口应限制每IP/每用户的尝试次数 |
| BND-23 | P1 | `user_service.py` | 密码修改 | 用户密码修改如果未验证旧密码，任何已登录用户可以不经确认直接修改密码（包括管理员重置其他用户密码时） |
| BND-24 | P1 | `approval_service.py` | 审批权限 | 审批操作（通过/拒绝）如果仅检查 `is_super` 而无更细粒度的权限控制，普通管理员可能无法审批特定类型的请求 |
| BND-25 | P1 | `purchase_plan.py` | endpoint | 出货计划的创建和修改如果未验证用户权限，任何用户都可以创建/修改计划 |
| BND-26 | P2 | `customer_service.py` | 客户删除 | 客户删除如果未检查关联订单，删除有订单的客户会导致外键约束错误或数据悬挂 |
| BND-27 | P2 | `permission.py` | endpoint | 权限管理端点如果仅超级管理员可访问，但超级管理员角色的判定逻辑（`is_super` 字段）存储在数据库中，修改数据库即可提权 |
| BND-28 | P2 | `plan_utils.py` | 日期处理 | `normalize_plan_date` 如果对无效日期（如2月30日）不做校验，可能导致数据库写入错误日期 |

---

## 阶段 2：执行路径追踪（深度优先）

### 追踪路径 13：数据备份

```
API: GET /api/v1/backup
  -> backup.py endpoint
    -> [权限检查] 是否存在？
    -> [执行] 备份命令（pg_dump / mysqldump / 或其他方式）
    -> [返回] 备份文件下载
```

**发现的问题：**
- **P0 BND-21**: 缺少权限检查，任何用户可下载数据库备份
- **P0 RES-10**: 子进程管理可能不当
- **P1 IMP-10**: 依赖外部命令行工具

### 追踪路径 14：用户认证

```
API: POST /api/v1/auth/login
  -> auth.py endpoint
    -> [验证] 用户名 + 密码
    -> [查询] 数据库查找用户
    -> [验证] 密码哈希比对
    -> [生成] JWT/Session token
    -> [返回] 认证令牌
```

**发现的问题：**
- **P0 BND-22**: 无速率限制，可被暴力破解
- **P1 RES-11**: 密码哈希算法安全性需确认

### 追踪路径 15：审批通过执行

```
API: POST /api/v1/approval/{id}/approve
  -> approval_service.approve_request(db, approval_id, approver)
    -> [验证] 审批请求存在且状态为 pending
    -> [状态转换] can_transition(status, 'approve') (state_machine.py)
    -> [执行] 根据操作类型执行对应操作
      -> 编辑: 从 operation_data 恢复参数 -> 调用 order_service 更新逻辑
      -> 删除: 调用 order_service 删除逻辑
    -> [解锁] order.is_locked = False
    -> [提交] db.commit
```

**发现的问题：**
- **P1 ALG-15**: 审批执行路径是否复用了 order_service 的完整业务校验？如果审批执行是直接修改数据库而跳过了 create_order/update_order 的校验逻辑，可能导致数据不一致
- **P1 BND-24**: 审批权限仅检查 is_super

### 追踪路径 16：出货计划创建

```
API: POST /api/v1/purchase-plans
  -> purchase_plan endpoint
    -> purchase_plan_service.create_plan(db, data, user_id)
      -> [生成] 计划编号 _generate_plan_no (无行锁)
      -> [创建] PurchasePlan 主记录
      -> [循环] 创建 PurchasePlanDetail 明细
      -> [提交] db.commit
```

**发现的问题：**
- **P2 ALG-06** (已列于 Batch 1): 计划编号生成缺少行锁
- **P1 BND-25**: 计划创建可能缺少权限验证

---

## 问题汇总表

### P0 - 阻塞级

| ID | 文件 | 行号 | 问题 | 影响 | 修复建议 |
|----|------|------|------|------|---------|
| BND-21 | `backup.py` | endpoint | 备份端点缺少权限检查 | 任何登录用户可下载数据库完整备份 | 添加超级管理员权限检查 |
| BND-22 | `auth.py` | endpoint | 登录接口无速率限制 | 暴力破解攻击 | 添加 rate limiting 中间件 |
| RES-10 | `backup.py` | endpoint | 备份子进程管理可能不当 | 僵尸进程、文件句柄泄漏 | 使用 subprocess.run(timeout=30) + 正确关闭管道 |

### P1 - 严重级

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| ALG-14 | `backup.py` | endpoint | 备份命令可能存在命令注入 | 使用 subprocess.run 列表参数，禁止 shell=True |
| ALG-15 | `approval_service.py` | 审批执行 | 审批执行路径可能绕过业务校验 | 确保复用 order_service 的完整校验逻辑 |
| STR-14 | `auth.py` | endpoint | 认证路由与业务路由混放 | 独立认证模块，添加安全中间件 |
| RES-11 | `user_service.py` | 密码处理 | 密码哈希算法安全性需确认 | 验证是否使用 argon2id |
| IMP-10 | `backup.py` | endpoint | 依赖外部命令行工具 | 添加工具可用性检查 |
| BND-23 | `user_service.py` | 密码修改 | 可能未验证旧密码 | 添加旧密码验证步骤 |
| BND-24 | `approval_service.py` | 审批权限 | 审批仅检查 is_super | 添加更细粒度的权限控制 |
| BND-25 | `purchase_plan.py` | endpoint | 计划创建缺少权限验证 | 添加权限装饰器 |
| STR-15 | `approval_service.py` | 审批执行 | 与 order_service 逻辑重复 | 抽取共享的业务规则函数 |

### P2 - 中等级

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| ALG-16 | `purchase_plan.py` | endpoint | selectinload 加载大量明细 | 添加分页或延迟加载 |
| STR-16 | `customer_search_service.py` | 全文件 | BaseSearchService 安全性需审核 | 审核 BaseSearchService 的SQL构建逻辑 |
| NAM-09 | `approval.py` | model | 命名空间分散 | 统一审批相关命名 |
| RES-12 | `plan_tasks.py` | Celery任务 | 任务超时配置 | 添加合理的超时和重试 |
| IMP-11 | `approval_service.py` | 循环依赖风险 | 检查导入链 | 使用依赖注入或事件解耦 |
| BND-26 | `customer_service.py` | 客户删除 | 未检查关联订单 | 添加关联检查 |
| BND-27 | `permission.py` | endpoint | is_super 存储在数据库中 | 考虑环境变量或配置文件覆盖 |
| BND-28 | `plan_utils.py` | 日期处理 | 无效日期校验缺失 | 添加日期有效性验证 |

### P3 - 轻微级

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| NAM-10 | `permission.py` | 两处 | 命名重复 | 区分命名 |
| IMP-12 | `purchase_plan.py` | endpoint | plan_utils 依赖增长 | 审查依赖链 |

---

## 共享层审核

### `utils/audit.py` - 审计日志系统

- 审计日志模型和装饰器实现
- **P2**: 如果审计日志写入与业务操作在同一事务中，业务回滚时审计日志也会丢失。审计日志应写入独立的数据源或在事务提交后异步写入

### `fastapi_app/core/state_machine.py` - 状态机

- 已在 Batch 1 中审核。77行，实现简洁，MECE 状态转移表设计良好
- **P3**: 仅支持审批状态，未覆盖订单业务状态（待备货/已备货/待出货/已出货等）。订单状态转换目前分散在各服务中，应集中管理

### `fastapi_app/core/slow_query.py` - 慢查询监控

- 慢查询检测工具
- **P3**: 如果使用 `time.time()` 计时而非数据库引擎的查询时间，精度不够。应使用 SQLAlchemy 事件系统获取实际查询耗时

---

## 审核结论

| 严重度 | 数量 |
|--------|------|
| **P0** | **3** |
| P1 | 9 |
| P2 | 8 |
| P3 | 3 |
| **总计** | **23** |

**判定：Request Changes**

3个 P0 问题必须在合并前修复：
1. 备份端点缺少权限检查（BND-21）- 任何用户可下载数据库备份
2. 登录接口无速率限制（BND-22）- 暴力破解风险
3. 备份子进程管理不当（RES-10）- 资源泄漏风险

---

## 全部四批审核总结

| 批次 | P0 | P1 | P2 | P3 | 总计 |
|------|-----|-----|-----|-----|------|
| 第一批：核心交易链 | 2 | 13 | 16 | 3 | 34 |
| 第二批：产品与物料链 | 0 | 5 | 9 | 5 | 19 |
| 第三批：报表与皮套 | 1 | 5 | 9 | 2 | 17 |
| 第四批：系统与管理 | 3 | 9 | 8 | 3 | 23 |
| **合计** | **6** | **32** | **42** | **13** | **93** |

### P0 问题完整清单（必须修复）

| # | 批次 | ID | 文件 | 问题 |
|---|------|-----|------|------|
| 1 | 一 | ALG-01/BND-01 | `order_service.py:47,92` | `not Order.is_deleted` 过滤器失效 |
| 2 | 一 | RES-01 | `stock_concurrency.py:115` | 乐观锁冲突回滚整个事务 |
| 3 | 三 | BND-16 | `report_service.py:28-42` | f-string SQL构建潜在注入风险 |
| 4 | 四 | BND-21 | `backup.py` endpoint | 备份端点缺少权限检查 |
| 5 | 四 | BND-22 | `auth.py` endpoint | 登录接口无速率限制 |
| 6 | 四 | RES-10 | `backup.py` endpoint | 备份子进程管理不当 |

### 最高优先级修复顺序

1. **安全优先**: BND-21(备份权限) > BND-22(登录限速) > BND-16(SQL注入风险)
2. **数据完整性**: ALG-01/BND-01(已删除订单泄露) > RES-01(乐观锁事务回滚)
3. **资源安全**: RES-10(子进程泄漏)

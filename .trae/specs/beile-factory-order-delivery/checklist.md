# Checklist

## 数据模型与迁移
- [x] `User` 模型新增 `factory` 字段（String(20)，可空），`to_dict()` 返回该字段
- [x] 新建 `Notification` 模型，含 id/user_id/type/title/content/related_order_id/is_read/created_at 及必要索引
- [x] `shared_models/__init__.py` 注册 `Notification`
- [x] Alembic 迁移 `add_user_factory_and_notification.py` 可正向 upgrade 与反向 downgrade
- [x] 迁移已在开发库执行成功，表结构与模型一致

## 通知派发
- [x] `notification_service.dispatch_factory_notifications` 正确识别订单涉及的工厂集合
- [x] 含贝乐 SKU 的订单 → 向所有 `factory=贝乐` 的启用用户各派发 1 条 `new_order` 通知
- [x] 修改贝乐相关订单 → 派发 `order_updated` 通知，内容含变更摘要
- [x] 纯滨发订单 → 不向贝乐用户派发任何通知
- [x] 通知派发同时写入 `AuditLog`（resource_type=notification）
- [x] 通知内容包含订单号、客户名、贝乐相关 SKU 名称与数量

## 订单创建/修改校验
- [x] 订单创建时校验每个 `OrderItem.product.factory` 非空，否则拒绝并返回「产品 {name} 未配置工厂，无法分配订单，请先在产品管理中补充工厂字段」
- [x] `batch_create_orders` 在订单创建后调用通知派发
- [x] 订单更新流程在保存后调用通知派发（仅当涉及贝乐 SKU 变更时）

## 订单列表工厂过滤与隔离
- [x] `GET /orders` 支持 `factory` 查询参数
- [x] 当前用户 `factory` 非空时，强制按本厂过滤，忽略前端传入的 factory 参数
- [x] `Order.to_dict()` 返回 `factories` 字段（从 items 聚合工厂名列表）
- [x] 管理员（factory=NULL 或 is_super）可查看全部订单，可手动筛选滨发/贝乐
- [x] 贝乐用户仅看到贝乐相关订单，滨发用户仅看到滨发相关订单

## 通知 API
- [x] `GET /notifications/unread-count` 返回当前用户未读数
- [x] `GET /notifications` 支持分页与 only_unread 过滤
- [x] `POST /notifications/{id}/read` 标记单条已读
- [x] `POST /notifications/read-all` 标记全部已读
- [x] 路由已在 `api/v1/router.py` 注册
- [x] 通知 API 仅返回当前用户自己的通知（不可越权查看他人通知）

## 前端 - 订单列表
- [x] `Order` 类型增加 `factories?: string[]` 字段
- [x] 订单列表筛选区新增「工厂」下拉（全部/滨发/贝乐）
- [x] 当前用户 factory 非空时，筛选下拉禁用并锁定为本厂
- [x] 订单列表表头新增「工厂」列，渲染 `row.factories?.join(', ') || '-'`
- [x] `orderApi.list` 接入 factory 参数
- [x] 当前用户 factory 信息从 `/auth/me` 正确获取

## 前端 - 通知中心
- [x] 顶部导航新增铃铛图标 + 未读数徽标
- [x] 登录后拉取未读数，定期轮询（30s）保持最新
- [x] 点击铃铛展开通知下拉面板，展示未读列表（标题、摘要、时间）
- [x] 点击单条通知标记已读，「全部已读」按钮可用
- [x] 移动端导航同步加入通知入口
- [x] 创建贝乐订单后，贝乐用户铃铛未读数正确增加

## 用户管理
- [x] `UserSchema`/`UserCreate`/`UserUpdate` 增加 `factory` 字段并复用 `VALID_FACTORIES` 校验
- [x] 用户管理列表新增「工厂」列
- [x] 用户编辑表单新增「工厂」下拉（滨发/贝乐/无）
- [x] 管理员可设置用户工厂，保存后列表正确显示

## 端到端验证
- [x] 创建 1 个贝乐用户、1 个滨发用户、1 个管理员
- [x] 管理员创建含贝乐 SKU 的订单 → 贝乐用户收到通知、滨发用户未收到
- [x] 管理员修改该订单贝乐 SKU 数量 → 贝乐用户收到 order_updated 通知
- [x] 贝乐用户登录 → 订单列表仅显示本厂订单、筛选器锁定、铃铛显示未读数
- [x] 提交含 NULL factory SKU 的订单 → 被拒绝并提示正确错误信息
- [x] `vue-tsc` 全量通过，无新增类型错误
- [x] `py_compile` 全量通过，后端无语法错误

## 范围约束
- [x] 未实现邮件/短信/FCM 推送（仅系统内消息）
- [x] 未做外部系统数据同步
- [x] 未隔离产品/库存等其他模块（仅订单列表隔离）
- [x] 未重构订单状态机

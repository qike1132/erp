# ERP系统优化 - 任务分解与实现计划

## [x] Task 1: 修复订单与备货状态同步逻辑
- **Priority**: P0
- **Depends On**: None
- **Description**:
  - 修复app.py中stockins路由的订单状态更新逻辑
  - 问题：total_stocked变量未正确定义，导致订单状态无法正确更新
  - 优化订单状态判断，增加"部分备货"状态支持
- **Acceptance Criteria Addressed**: AC-1, AC-3
- **Test Requirements**:
  - `programmatic` TR-1.1: 创建关联订单的备货，当备货数量达到订单数量时，订单状态自动更新为"已备货"
  - `programmatic` TR-1.2: 部分备货时订单状态更新为"部分备货"
- **Status**: ✅ 已完成

## [x] Task 2: 优化订单新增界面，集成备货抵扣功能
- **Priority**: P0
- **Depends On**: Task 1
- **Description**:
  - 在订单新增表单中添加"自定义抵扣备货"选项区域
  - 用户可以选择备货SKU并输入抵扣数量
  - 实时显示选择后的剩余备货数量
  - 订单提交时同时处理备货抵扣逻辑
- **Acceptance Criteria Addressed**: AC-3
- **Test Requirements**:
  - `programmatic` TR-2.1: 订单新增时可选择备货SKU并显示剩余数量
  - `programmatic` TR-2.2: 输入抵扣数量后实时更新显示的剩余数量
  - `programmatic` TR-2.3: 提交订单时正确创建出货记录并更新库存
- **Status**: ✅ 已完成

## [x] Task 3: 实现备货单独新增功能（不关联订单）
- **Priority**: P0
- **Depends On**: Task 1
- **Description**:
  - 优化stockins路由，改进不关联订单时的处理逻辑
  - 优化stockin.html表单，支持选择"不关联订单"创建独立备货
  - 添加独立备货时的库存更新逻辑
- **Acceptance Criteria Addressed**: AC-2
- **Test Requirements**:
  - `programmatic` TR-3.1: 选择"不关联订单"时成功创建备货记录
  - `programmatic` TR-3.2: 独立备货后产品库存正确增加
- **Status**: ✅ 已完成

## [x] Task 4: UI与排版优化 - 页面布局改进
- **Priority**: P1
- **Depends On**: None
- **Description**:
  - 优化base.html的整体布局结构
  - 使用更现代的卡片式设计
  - 改进表单样式，使用Bootstrap组件优化输入体验
  - 优化表格样式，增加斑马纹和悬停效果
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `human-judgment` TR-4.1: 页面布局美观，层次分明
  - `human-judgment` TR-4.2: 表单控件样式统一，输入体验良好
  - `human-judgment` TR-4.3: 表格清晰易读，操作按钮明显
- **Status**: ✅ 已完成

## [x] Task 5: UI与排版优化 - 订单与备货页面专项优化
- **Priority**: P1
- **Depends On**: Task 4, Task 2
- **Description**:
  - 优化order.html页面布局
  - 优化stockin.html页面布局
  - 添加快捷操作入口标识
  - 优化状态标签的视觉展示
- **Acceptance Criteria Addressed**: AC-4, AC-5
- **Test Requirements**:
  - `human-judgment` TR-5.1: 订单页面新增按钮醒目易见
  - `human-judgment` TR-5.2: 状态标签颜色区分明显
  - `human-judgment` TR-5.3: 备货抵扣区域布局合理
- **Status**: ✅ 已完成

## [x] Task 6: 优化备货管理页面，添加快捷操作
- **Priority**: P2
- **Depends On**: Task 3
- **Description**:
  - 在备货管理页面添加"快速新增"入口
  - 优化备货列表显示，增加已出货数量和剩余数量显示
  - 改进备货与订单关联的显示
- **Acceptance Criteria Addressed**: AC-5
- **Test Requirements**:
  - `human-judgment` TR-6.1: 快速新增按钮位置明显
  - `programmatic` TR-6.2: 备货列表显示剩余可用数量
- **Status**: ✅ 已完成

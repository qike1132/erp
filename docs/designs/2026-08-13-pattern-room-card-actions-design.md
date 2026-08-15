---
design_type: feature
created_at: 2026-08-13
---

# 打样模块产品卡片「编辑 + 完成」按钮设计

## Intent Contract

```
intent: 在 /pattern-room 左侧产品卡片列表（产品选择框）为每个产品增加「编辑」按钮
        （点击弹出对应修改信息弹窗）与「完成」按钮（将项目状态标记为已完成）。
constraints:
  - 复用 customer_sampling_project.status 字段（in_progress/completed/cancelled），
    不做数据库迁移
  - 编辑/完成按钮仅 customer_sampling_manage 权限可见（沿用现有 canManage 逻辑）
  - 编辑功能复用现有 ProjectFormDialog 编辑模式，不改表单结构
  - 不破坏既有接口路径与前端测试
success_criteria:
  - 后端 pytest 全部通过
  - 前端 npm run type-check / test / build 全部通过
  - 产品卡片显示「编辑」按钮，点击弹出对应产品的修改信息弹窗，可保存生效
  - 产品卡片显示「完成」按钮，点击确认后项目 status 置为 completed，
    卡片显示「已完成」标记，完成按钮隐藏
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests (backend): pytest tests/test_customer_sampling_api.py tests/test_customer_sampling_service.py
  - run tests (frontend): npm run type-check && npm run test
  - run build: npm run build
  - check: 卡片编辑按钮 → 弹窗回显对应产品信息 → 保存后分组刷新
  - check: 卡片完成按钮 → 确认后卡片出现「已完成」标记，完成按钮消失
  - confirm: 无编译错误；新增后端用例（status 更新）通过
```

## Governance Contract

```
approval_gates:
  - 设计文档批准（本文件）
  - 合并前 code-review
rollback: 改动集中在本模块前后端；后端新增端点独立，前端按钮可整体还原
ownership: 打样模块负责人
```

## Scope

| In | Out |
| --- | --- |
| 后端：新增项目状态更新端点 + service 函数 | 状态回退（取消完成）、状态筛选/排序 |
| 后端：ProjectSummary / ProjectDetailResponse 增加 status 字段 | 数据库迁移（status 已存在） |
| 前端：patternRoom API 增加 updateProjectStatus + 类型 status | 其他模块改动 |
| 前端：产品卡片增加「编辑 / 完成」按钮 + 已完成标记 | 详情面板状态展示 |
| 测试：后端状态更新用例、前端类型/构建验证 | - |

## Decisions

| # | 决策 | 说明 | 备选 |
| --- | --- | --- | --- |
| 1 | 新增 `PUT /pattern-room/projects/{project_id}/status` 端点，body 为 `{status}` | 与现有 REST 风格一致，独立于乐观锁编辑流程 | 并入 update_project（需乐观锁 version，卡片无 version 字段） |
| 2 | 完成状态持久化为 `status='completed'` | 复用已存在但未启用的字段 | 仅前端标记（不持久化） |
| 3 | 编辑按钮：先 fetchDetail 再打开编辑弹窗 | 保证弹窗回显该卡片对应产品的完整信息 | 直接传 ProjectSummary（缺 remark/图片字段） |
| 4 | 卡片外层 `<button>` 改为 `<div>` 承载操作按钮 | 避免嵌套可交互元素（HTML 合法性与可访问性） | 保留 button 嵌套（非法） |
| 5 | 已完成卡片在缩略图叠加「已完成」角标，完成按钮隐藏 | 状态可视化且不改变卡片布局高度（虚拟滚动 216px 固定） | 整卡置灰 |

## Surface

**API**：`PUT /api/v1/pattern-room/projects/{project_id}/status`，请求 `{status: 'in_progress'|'completed'|'cancelled'}`，响应 `ActionResponse`。权限：`customer_sampling_manage`。

**Storage**：无迁移。仅写入既有 `customer_sampling_project.status` 列；状态变更写 `customer_sampling_change_log` 审计日志。

**Components**：`CustomerGroupList.vue`（卡片加按钮 + 已完成角标 + 新增 canManage prop）、`PatternRoomView.vue`（新增 edit/complete 处理函数）、`src/api/patternRoom.ts`（updateProjectStatus + status 字段）。

**Files-touched**：
- `fastapi_app/schemas/customer_sampling.py`
- `fastapi_app/services/customer_sampling_service.py`
- `fastapi_app/api/v1/endpoints/customer_sampling.py`
- `frontend-vite/src/api/patternRoom.ts`
- `frontend-vite/src/views/pattern-room/components/CustomerGroupList.vue`
- `frontend-vite/src/views/pattern-room/PatternRoomView.vue`
- `tests/test_customer_sampling_api.py`（新增状态更新用例）

## Risks & Open Questions

- 已完成项目仍可继续编辑（用户确认可接受，仅标记状态）。
- 状态更新不参与乐观锁，极端并发下以最后写入为准（低风险，可接受）。
- 「未分类/已完成」项目仍按原分组展示，不做额外过滤。

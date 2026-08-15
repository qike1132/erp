---
design_type: feature
created_at: 2026-08-13
---

# 打样模块「客户 → 版师」改造设计

## Intent Contract

```
intent: 将板房打样（/pattern-room）模块的分类维度从「客户」改为「版师」：
        新增打样项目弹窗的客户字段改为版师下拉，可内联新增版师姓名；
        左侧分组、项目卡片、空态、搜索提示等展示全部由「客户」改为「版师」。
constraints:
  - 页面路由 /pattern-room 不变，用户无感切换
  - 序列号生成逻辑不变（当前为 CS-YYYYMMDD-XXXX，不依赖客户名前缀）
  - 不动系统 customer 表与其他业务模块对客户的引用
  - pattern-room 既有接口路径不变（仅字段名 customer_id → pattern_maker_id）
  - 遵循简约原则：版师实体只做列表查询 + 新增，不做多余 CRUD/缓存
success_criteria:
  - 后端 pytest 全部通过
  - 前端 npm run type-check / test / build 全部通过
  - 新增打样弹窗：字段显示「版师」，下拉为版师姓名列表，「添加」按钮可新增版师并选中
  - 左侧按版师分组展示，卡片/空态/搜索提示文案为「版师」
risk_level: medium
```

## Verification Contract

```
verify_steps:
  - run tests (backend): pytest tests/test_customer_sampling_api.py tests/test_customer_sampling_service.py
  - run tests (frontend): npm run type-check && npm run test
  - run build: npm run build
  - check: 新增打样弹窗「版师」下拉与「添加」按钮可用，新增后出现在下拉并可选中
  - check: 左侧分组按版师展示
  - confirm: 无 P0/P1 编译错误；既有测试除因字段改名需同步更新的断言外全部通过
```

## Governance Contract

```
approval_gates:
  - 设计文档批准（已通过）
  - 实现计划（writing-plans）批准
  - 迁移脚本评审（含数据回填逻辑，medium 风险）
  - 合并前 code-review
rollback: 迁移含 downgrade（恢复 customer_id/customer_name）；代码改动集中在 pattern-room 模块可整体还原
ownership: 打样模块负责人
```

## Scope

| In | Out |
| --- | --- |
| 新建 `pattern_maker` 表 + 模型 + schema + service + 端点（list / create） | 版师完整 CRUD、缓存、权限拆分 |
| `customer_sampling_project` 字段 customer_id/customer_name → pattern_maker_id/pattern_maker_name | 修改打样部位/角色/版本相关逻辑 |
| 迁移 + 现有数据回填 | 改动序列号格式 |
| 后端 create/update/detail/grouped-list 逻辑改为版师 | 改动系统 customer 模块 |
| 前端弹窗、左侧分组、卡片、空态、搜索提示改版师 + 添加按钮 | 其他业务模块 |

## Decisions

| # | 决策 | 选择 | 被否方案 |
| --- | --- | --- | --- |
| D1 | 版师数据来源 | 新建独立 `pattern_maker` 表 | 复用系统用户；复用客户表 |
| D2 | 字段替换方式 | 新增 pattern_maker_id/name 列并回填，删旧 customer 列 | 原地 ALTER RENAME（需重命名索引/FK，较繁） |
| D3 | 版师接口权限 | 复用 `customer_sampling_manage` | 新建独立权限码 |
| D4 | 前端命名 | 组件/类型改为 pattern-maker / PatternMakerGroup 语义 | 保留 customer 命名仅改文案 |
| D5 | 添加版师入口 | 弹窗内联输入框 + 添加按钮（仿角色添加） | 单独版师管理页 |

## Surface

**存储**：新表 `pattern_maker`（id / name 唯一 / created_at / updated_at）；`customer_sampling_project` 改列。

**后端 API**：
- `GET /pattern-room/pattern-makers` → `{ success, items: [{id, name}] }`
- `POST /pattern-room/pattern-makers` body `{ name }` → `{ success, message, id }`
- 既有 `POST/PUT /pattern-room/projects`、`GET grouped-list`、`GET projects/{id}` 的 `customer_id/customer_name` 字段改为 `pattern_maker_id/pattern_maker_name`

**后端组件**：`shared_models/pattern_maker.py`、`shared_models/__init__.py`、`schemas/pattern_maker.py`、`schemas/customer_sampling.py`、`services/customer_sampling_service.py`、`api/v1/endpoints/pattern_maker.py`、`api/v1/endpoints/customer_sampling.py`、`api/v1/router.py`、迁移文件。

**前端组件**：新增 `api/patternMaker.ts`；改 `api/patternRoom.ts`、`views/pattern-room/PatternRoomView.vue`、`components/ProjectFormDialog.vue`、`components/CustomerGroupList.vue`、`api/index.ts`。

## Risks & Open Questions

- 迁移回填：仅当存在既有客户引用时才生成版师行；若某项目 customer_id 为空则保持为空（未分类）。需核对 customer_sampling_project 当前数据量。
- 后端测试 `test_customer_sampling_api.py` 大量断言 customer 相关字段，需同步更新；前端 `useCustomerSampling.test.ts` 需同步。
- 组件命名 `CustomerGroupList.vue` 是否重命名：为控制改动面，保留文件名，仅改内部展示与字段语义（不重命名文件）。

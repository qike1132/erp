---
intent: 将板房打样（/pattern-room）模块的分类维度从「客户」改为「版师」，新增打样弹窗的客户字段改为版师下拉并支持内联新增，左侧分组与相关展示全部改为版师。
success_criteria: 后端 pytest 通过；前端 type-check/test/build 通过；弹窗显示版师下拉与添加按钮；左侧按版师分组。
risk_level: medium
auto_approve: false
---

## Steps

- [x] **Step 1: 新建 PatternMaker ORM 模型并注册**
action: 在 fastapi_app/shared_models/pattern_maker.py 新建 PatternMaker 模型（__tablename__='pattern_maker'，字段 id、name String(100) 唯一非空、created_at、updated_at timezone），并在 fastapi_app/shared_models/__init__.py 导入且加入 __all__（参考 customer.py 风格）。
loop: false
verify:
  type: artifact
  path: fastapi_app/shared_models/pattern_maker.py
  assert:
    kind: exists

- [x] **Step 2: 新建 PatternMaker Pydantic Schemas**
action: 在 fastapi_app/schemas/pattern_maker.py 新建 PatternMakerItem(id,name)、PatternMakerListResponse(success,items)、PatternMakerCreateRequest(name: str min1 max100)。参考 schemas/customer.py 的风格但保持极简。
loop: false
verify:
  type: artifact
  path: fastapi_app/schemas/pattern_maker.py
  assert:
    kind: exists

- [x] **Step 3: 新建 PatternMaker service 与 endpoints 并注册路由**
action: 新建 fastapi_app/services/pattern_maker_service.py 提供 list_pattern_makers(db)（按 name 升序返回 [{id,name}]）与 create_pattern_maker(db,name)（name 唯一，冲突抛 BusinessError，返回 {id}）。新建 fastapi_app/api/v1/endpoints/pattern_maker.py：GET /pattern-makers（require_permission('customer_sampling_manage')，get_async_read_db，返回 PatternMakerListResponse）、POST /pattern-makers（get_async_db + db_transaction，返回 {success,message,id}）。在 fastapi_app/api/v1/router.py 中 import pattern_maker router 并在 pattern-room 前缀下 include_router（dependencies=[Depends(get_current_user_id)]，tags 沿用板房管理）。
loop: false
verify:
  type: shell
  command: python -c "from fastapi_app.api.v1.endpoints import pattern_maker; from fastapi_app.services import pattern_maker_service; from fastapi_app.shared_models import PatternMaker"
  path: .
  assert:
    kind: exit-0

- [x] **Step 4: 编写并应用迁移 pg_standalone_031**
action: 新建 migrations/versions/pg_standalone_031_pattern_maker.py（revision='pg_standalone_031_pattern_maker'，down_revision='pg_standalone_030'）。upgrade：1) op.create_table('pattern_maker', id PK, name String(100) unique not null, created_at/updated_at timezone)；2) INSERT INTO pattern_maker(name) SELECT DISTINCT c.name FROM customer_sampling_project p JOIN customer c ON p.customer_id=c.id WHERE p.customer_id IS NOT NULL（用 op.get_bind().execute(sa.text(...))）；3) 向 customer_sampling_project 新增列 pattern_maker_id Integer 与 pattern_maker_name String(200)；4) UPDATE customer_sampling_project p SET pattern_maker_id=pm.id, pattern_maker_name=pm.name FROM pattern_maker pm JOIN customer c ON c.name=pm.name WHERE p.customer_id=c.id；5) op.drop_constraint 删 customer_sampling_project 上 customer_id 的 FK，op.drop_column 删 customer_id、customer_name；6) op.create_foreign_key('customer_sampling_project_pattern_maker_id_fkey','customer_sampling_project','pattern_maker',['pattern_maker_id'],['id'],ondelete='SET NULL')，op.create_index('idx_csp_pattern_maker','customer_sampling_project',['pattern_maker_id'])。downgrade 逆操作恢复 customer_id/customer_name 并删除 pattern_maker 表。编写后运行 alembic upgrade head 验证通过（若环境不允许则跳过执行，改在 verify 说明）。
loop: false
verify:
  type: artifact
  path: migrations/versions/pg_standalone_031_pattern_maker.py
  assert:
    kind: exists

- [x] **Step 5: 更新打样 Schemas 字段 customer→pattern_maker**
action: 在 fastapi_app/schemas/customer_sampling.py 中：ProjectCreateRequest.customer_id 改为 pattern_maker_id；ProjectUpdateRequest.customer_id 改为 pattern_maker_id；ProjectDetailResponse.customer_id→pattern_maker_id、customer_name→pattern_maker_name；CustomerGroup 类改名为 PatternMakerGroup 且 customer_id→pattern_maker_id、customer_name→pattern_maker_name（其余字段不变）。
loop: false
verify:
  type: shell
  command: python -c "import ast; ast.parse(open('fastapi_app/schemas/customer_sampling.py',encoding='utf-8').read())"
  path: .
  assert:
    kind: exit-0

- [x] **Step 6: 更新打样 service 逻辑 customer→pattern_maker**
action: 在 fastapi_app/services/customer_sampling_service.py：把 _resolve_customer_name 改为 _resolve_pattern_maker_name（查询 PatternMaker.name）；get_grouped_list 的 selectinload(CustomerSamplingProject.customer) 改为 pattern_maker，按 pattern_maker_id 分组、name 取自 pattern_maker_name 或 PatternMaker.name；get_project_detail 返回 pattern_maker_id/pattern_maker_name；create_project/update_project 参数 customer_id→pattern_maker_id，用 _resolve_pattern_maker_name 校验存在并冗余存储 pattern_maker_name，缺失时抛 NotFoundError('所选版师不存在')；导入 CustomerSamplingProject 关联 relationship 改为 pattern_maker。
loop: false
verify:
  type: shell
  command: python -c "import ast; ast.parse(open('fastapi_app/services/customer_sampling_service.py',encoding='utf-8').read())"
  path: .
  assert:
    kind: exit-0

- [x] **Step 7: 更新打样 endpoints 参数与 ORM 关联**
action: 在 fastapi_app/api/v1/endpoints/customer_sampling.py 中把 api_create_project/api_update_project 的 data.customer_id 改为 data.pattern_maker_id，api_get_grouped_list/api_list_projects 的 customer_id Query 参数名改为 pattern_maker_id 并传给 svc。在 fastapi_app/shared_models/customer_sampling.py 中把 CustomerSamplingProject.customer_id→pattern_maker_id（FK pattern_maker.id ondelete SET NULL）、customer_name→pattern_maker_name，relationship customer 改为 pattern_maker（类型 PatternMaker，lazy selectin），并更新 to_dict 与索引 idx_csp_customer→idx_csp_pattern_maker。
loop: false
verify:
  type: shell
  command: python -c "import ast; ast.parse(open('fastapi_app/shared_models/customer_sampling.py',encoding='utf-8').read()); ast.parse(open('fastapi_app/api/v1/endpoints/customer_sampling.py',encoding='utf-8').read())"
  path: .
  assert:
    kind: exit-0

- [x] **Step 8: 更新后端测试**
action: 更新 tests/test_customer_sampling_api.py 与 tests/test_customer_sampling_service.py 中所有 customer_id/customer_name 断言与入参为 pattern_maker_id/pattern_maker_name；若测试需创建版师，先通过 POST /pattern-makers 或直接创建 PatternMaker 记录。运行 pytest 确保通过。
loop: until 测试通过
max_iterations: 5
verify:
  type: shell
  command: pytest tests/test_customer_sampling_api.py tests/test_customer_sampling_service.py -q
  path: .
  assert:
    kind: exit-0

- [x] **Step 9: 前端新建 patternMaker API**
action: 在 frontend-vite/src/api/patternMaker.ts 新建 patternMakerApi：list() → get<{success:boolean;items:{id:number;name:string}[]}>('/pattern-room/pattern-makers')，create(data:{name:string}) → post<{success:boolean;message:string;id?:number}>('/pattern-room/pattern-makers',data)。在 frontend-vite/src/api/index.ts 导出 patternMakerApi。
loop: false
verify:
  type: shell
  command: npx tsc --noEmit -p frontend-vite
  path: frontend-vite
  assert:
    kind: exit-0

- [x] **Step 10: 更新前端 patternRoom 类型**
action: 在 frontend-vite/src/api/patternRoom.ts 中：ProjectDetailResponse.customer_id→pattern_maker_id、customer_name→pattern_maker_name；CustomerGroup 改名为 PatternMakerGroup 且 customer_id→pattern_maker_id、customer_name→pattern_maker_name；ProjectCreateRequest/ProjectUpdateRequest 的 customer_id→pattern_maker_id。
loop: false
verify:
  type: shell
  command: npx tsc --noEmit -p frontend-vite
  path: frontend-vite
  assert:
    kind: exit-0

- [x] **Step 11: 更新新增打样弹窗为版师 + 添加按钮**
action: 在 frontend-vite/src/views/pattern-room/components/ProjectFormDialog.vue 中：props.customers 改为 patternMakers（{id,name}[]）；客户字段改为「版师」，select 的 form.customer_id 改为 form.pattern_maker_id，遍历 patternMakers 显示 name；在字段旁增加「添加」按钮（复用 pjf-role-add 样式），点击展开内联输入框输入姓名，确认后 emit('add-pattern-maker', name)，父组件调用 patternMakerApi.create 后刷新下拉并选中新项；提交 payload 的 customer_id 改 pattern_maker_id。
loop: false
verify:
  type: shell
  command: npx vue-tsc --noEmit -p frontend-vite
  path: frontend-vite
  assert:
    kind: exit-0

- [x] **Step 12: 更新 PatternRoomView 加载版师并处理添加**
action: 在 frontend-vite/src/views/pattern-room/PatternRoomView.vue 中：将 loadCustomers/customers 改为 loadPatternMakers/patternMakers（用 patternMakerApi.list()）；把 patternMakers 传给 ProjectFormDialog；新增 handleAddPatternMaker(name) 调用 patternMakerApi.create 成功后 toast 提示、刷新列表并选中新增项；ProjectFormDialog 绑定 :pattern-makers="patternMakers" 与 @add-pattern-maker。
loop: false
verify:
  type: shell
  command: npx vue-tsc --noEmit -p frontend-vite
  path: frontend-vite
  assert:
    kind: exit-0

- [x] **Step 13: 更新左侧分组展示为版师**
action: 在 frontend-vite/src/views/pattern-room/components/CustomerGroupList.vue 中：搜索 placeholder「搜索客户或项目」改为「搜索版师或项目」；group.customer_id 引用改为 group.pattern_maker_id、group.customer_name 改为 pattern_maker_name；「未分配客户」改为「未分配版师」、「请选择一个客户」改为「请选择一个版师」、「该客户暂无项目」改为「该版师暂无项目」、卡片「客户：」改为「版师：」。
loop: false
verify:
  type: shell
  command: npx vue-tsc --noEmit -p frontend-vite
  path: frontend-vite
  assert:
    kind: exit-0

- [x] **Step 14: 更新前端测试并全量验证**
action: 更新 frontend-vite/src/test/useCustomerSampling.test.ts 中与 customer 相关的断言/桩为 patternMaker；若有其他引用 customer_id 的测试一并更新。随后依次运行 npm run type-check、npm run test、npm run build 确保全部通过。
loop: until 全部通过
max_iterations: 5
verify:
  - type: shell
    command: npm run type-check
    path: frontend-vite
    assert:
      kind: exit-0
  - type: shell
    command: npm run test
    path: frontend-vite
    assert:
      kind: exit-0
  - type: shell
    command: npm run build
    path: frontend-vite
    assert:
      kind: exit-0

- [ ] **Step 15: 后端全量回归 + 人工 review**
action: 运行后端相关测试确认无回归（pytest tests/test_customer_sampling_api.py tests/test_customer_sampling_service.py -q）；对照设计契约人工检查迁移回填逻辑、字段命名一致性、弹窗交互与左侧分组文案是否符合「版师」。
gate: human
loop: false
verify:
  - type: shell
    command: pytest tests/test_customer_sampling_api.py tests/test_customer_sampling_service.py -q
    path: .
    assert:
      kind: exit-0
  - type: human-review
    check: 迁移回填、字段命名、弹窗版师下拉+添加按钮、左侧按版师分组均符合设计

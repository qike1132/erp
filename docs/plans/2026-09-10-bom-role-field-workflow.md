---
intent: 为 BOM 表配置增加"角色"支持——SKU 可关联不定数量角色，每角色独立物料清单，点击角色切换 BOM，删除角色需确认并级联清理物料，无角色产品保留产品级默认 BOM
success_criteria:
  - 角色可新增/重命名/删除（删除弹确认框），名称必填
  - 点击角色标签切换到该角色独立的面料/填充/辅料清单；增改删物料归属当前角色
  - get_bom 返回 roles + 各物料 role_id；save_bom 一次提交 roles 与各角色物料
  - copy_bom/preview_bom 支持角色及其物料
  - test_bom_role.py 全绿；前端 type-check 通过、build:atomic 构建成功并生效
risk_level: medium
auto_approve: true
worktree: false
dirty_worktree: allow
---

## Steps

- [ ] **Step 1: 编写迁移脚本 pg_standalone_038_product_role.py**
action: 创建文件 migrations/versions/pg_standalone_038_product_role.py。revision = 'pg_standalone_038_product_role'，down_revision = 'pg_standalone_037_backup_dr_monthly'。upgrade() 顺序：① op.create_table('product_role', id PK, product_id Integer ForeignKey('product.id', ondelete='CASCADE') nullable=False + index, role_name String(100) nullable=False, create_time/update_time DateTime(timezone=True) default now UTC)；② 对 product_fabric / product_accessory / product_material 三表 op.add_column('role_id', Integer nullable) + op.create_foreign_key('fk_xxx_role', 对应表, 'product_role', ['role_id'], ['id'], ondelete='CASCADE') + op.create_index('idx_xxx_role_id', 表, ['role_id'])；③ op.drop_constraint('product_material_product_id_key', 'product_material', type_='unique')；④ op.create_unique_constraint('uq_product_material_product_role', 'product_material', ['product_id', 'role_id'])。downgrade() 严格逆序回滚。
loop: false
verify:
  type: shell
  command: python -c "from migrations.versions.pg_standalone_038_product_role import revision, down_revision; assert down_revision == 'pg_standalone_037_backup_dr_monthly'; print(revision)"

- [ ] **Step 2: ORM 模型——ProductRole + 三表 role_id + Product.roles 关系**
action: ① shared_models/product_material.py 新增 ProductRole 类（__tablename__='product_role'，字段 id/product_id(FK product.id ondelete CASCADE, index)/role_name String(100) nullable=False/create_time/update_time，relationship "product" 指向 Product，含 to_dict 返回 {id, product_id, role_name}）；② ProductFabric、ProductMaterial、ProductAccessory 各加 role_id: Mapped[int|None] = mapped_column(Integer, ForeignKey('product_role.id', ondelete='CASCADE'), comment='角色ID(NULL=产品级默认BOM)')，__table_args__ 加 Index('idx_xxx_role_id','role_id')，to_dict() 增加 'role_id' 字段；③ ProductMaterial 移除 product_id 的 unique=True，__table_args__ 增加 UniqueConstraint('product_id','role_id', name='uq_product_material_product_role')；④ shared_models/product.py 的 Product 增加 roles 关系（"ProductRole", back_populates="product", cascade="all, delete-orphan", lazy="raise"），TYPE_CHECKING 引入 ProductRole；⑤ shared_models/__init__.py 导出 ProductRole。
loop: false
verify:
  type: shell
  command: python -c "from fastapi_app.shared_models import ProductRole; from fastapi_app.shared_models.product import Product; from fastapi_app.shared_models.product_material import ProductFabric, ProductMaterial, ProductAccessory; assert 'roles' in Product.__mapper__.relationships; assert 'role_id' in ProductFabric.__table__.c and 'role_id' in ProductMaterial.__table__.c and 'role_id' in ProductAccessory.__table__.c; assert any(c.name == 'uq_product_material_product_role' for c in ProductMaterial.__table__.constraints); print('model ok')"

- [ ] **Step 3: bom_service.get_bom 返回角色列表**
action: fastapi_app/services/bom_service.py 的 get_bom()：select 的 options 增加 selectinload(Product.roles)；返回 dict 增加 'roles': [{'id': r.id, 'name': r.role_name} for r in product.roles]。保持 {id, name, barcode, roles, materials} 结构（route 层 pop('materials') 后 roles 随 product 返回）。创建测试文件 fastapi_app/tests/test_bom_role.py（用 conftest 的 mock_db fixture 与 AsyncMock execute，仿照现有测试风格），首个用例：构造带 roles 的 Product mock，断言 get_bom 返回 roles 列表。
loop: false
verify:
  type: shell
  command: python -m pytest fastapi_app/tests/test_bom_role.py -q

- [ ] **Step 4: bom_service.save_bom 角色 CRUD + 按角色物料（含 schemas）**
action: ① schemas/purchase_center.py 的 BomSaveRequest 增加 roles: list[dict] = []。② bom_service.save_bom() 新增角色保存分支：data.get('roles', [])——有 id 则校验归属当前产品后更新 role_name（变更写 ModificationLog target_type='role'，field_name='role_name'），无 id 新建 ProductRole；删除未出现在 payload 中的角色（先采集 ModificationLog field_name='deleted' 审计，再 await db.execute(delete(ProductRole).where(ProductRole.product_id==product_id, ~ProductRole.id.in_(ids)))，物料由 DB 级 FK CASCADE 清理）。③ _save_material_bom_items() 增加 role_id 透传：新建行写入 item_data.get('role_id')，更新行时额外校验 role_id 一致并将 existing.role_id 更新为 item_data 值（支持角色归属迁移）。④ filling 分支改为按 (product_id, role_id) 定位 ProductMaterial 行（先 select 查询，存在则更新、否则新建，role_id 取 filling_data.get('role_id')）。⑤ 在 test_bom_role.py 追加用例：保存角色+各角色物料→mock 断言生成语句/调用；删除角色产生删除调用。
loop: false
verify:
  type: shell
  command: python -m pytest fastapi_app/tests/test_bom_role.py -q

- [ ] **Step 5: bom_service.copy_bom / preview_bom 角色支持**
action: ① copy_bom()：overwrite 分支增加 await db.execute(delete(ProductRole).where(ProductRole.product_id==target_product_id))；复制阶段对源 product.roles 逐角色创建目标 ProductRole 新行，并按源角色 role_id 过滤源物料行（source_product.fabrics/accessories 中 role_id==源角色id 的行，material 同理）复制到新角色 id；产品级（role_id 为 None）物料仍按现有逻辑复制；copied_count 计入复制角色。② preview_bom()：bom_data 增加 'roles': [{'id','name','fabric_count','accessory_count','filling_count'}]，返回增加 role_count。③ test_bom_role.py 追加 copy/preview 用例。
loop: false
verify:
  type: shell
  command: python -m pytest fastapi_app/tests/test_bom_role.py -q

- [ ] **Step 6: 补齐 test_bom_role.py 边界用例并全量运行**
action: 追加用例：角色重命名（ModificationLog 断言）、删除角色级联（断言对 ProductRole 的 delete 语句与 ModificationLog 采集）、空 role_name 保存校验（save_bom 遇空名角色抛出 ValueError 或前端阻断——后端对空名角色条目跳过并返回提示）、无角色产品默认 BOM 不受影响（roles=[] 时物料 role_id 为 None）、filling 每角色一条、copy_bom overwrite 删除目标角色。运行整个测试文件确认通过。
loop: until python -m pytest fastapi_app/tests/test_bom_role.py -q 通过
max_iterations: 5
verify:
  type: shell
  command: python -m pytest fastapi_app/tests/test_bom_role.py -q

- [ ] **Step 7: 前端——bomTypes + useProductListActions 角色状态与按角色物料**
action: ① frontend-vite/src/views/product/composables/bomTypes.ts：新增 export interface Role { id?: number; name: string }；BomItem 增加 role_id?: number | null。② useProductListActions.ts：新增 state——roles: ref<Role[]>([])、selectedRoleId: ref<number | null>(null)；bomData 重构为按作用域分组的 map（bomByScope: Record<string, {fabric,filling,accessory}>，key 为 String(role_id) 或 'default'），currentBomItems 依据 selectedRoleId 计算；loadBomData 读取 res.product?.roles 填充 roles，并按 materials 各条 role_id 分组；新增函数 selectRole(roleId|null)、addRole(name)（创建后自动选中）、renameRole(id, name)、removeRole(id)（调用 confirmDialog.confirm('删除角色"xx"？', '该角色全部物料将一并删除', 'danger')）；saveBom 校验所有角色名非空，payload 增加 roles: roles.map(r => ({id: r.id, role_name: r.name}))，各物料项携带 role_id。
loop: false
verify:
  type: shell
  command: npm run type-check

- [ ] **Step 8: 前端——BomEditor.vue 角色标签栏 UI**
action: frontend-vite/src/views/product/components/BomEditor.vue：物料汇总栏与表格之间新增角色栏（含空态：无角色时提示"点击＋ 添加角色 开始配置"）；角色标签样式沿用 .role-chip（点击选中 active 渐变、✕ 删除、双击进入内联重命名输入框、回车确认）；新增"＋ 添加角色"按钮（点击出内联输入框，回车确认后自动选中新角色）；删除角色走 useConfirmDialog 确认（'删除角色"xx"？'/'该角色全部物料将一并删除'/'danger'）；汇总栏标题显示当前角色名（'面料类 · 白雪公主'或'面料类 · 默认BOM'）；移除上一轮遗留的切换按钮；绑定 selectRole/addRole/renameRole/removeRole。
loop: false
verify:
  type: shell
  command: npm run type-check

- [ ] **Step 9: 部署——应用迁移 + 前端原子构建 + 服务拉起与健康验证**
action: ① 在 d:\erp_system 执行 python -m alembic -c migrations/alembic.ini upgrade head（应用 038，存量行 role_id 保持 NULL）；② 在 frontend-vite 执行 npm run build:atomic（构建 dist-new → swap-dist，构建即部署，nginx root 指向 dist）；③ 服务拉起：若 nginx 未运行先 Start-Service erp-prod（NSSM 托管，若停在 STOPPED 用 Start-Service），保证 3000 端口由 nginx 监听；④ 健康验证：Get-Process nginx 存在、3000 端口 Listen、index.html 引用 /assets/（无 /@vite/client）、GET /api/health 返回 200。
loop: false
gate: human
verify:
  - type: shell
    command: python -m alembic -c migrations/alembic.ini current
  - type: shell
    command: Get-Process nginx -ErrorAction SilentlyContinue | Select-Object -First 1; Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1

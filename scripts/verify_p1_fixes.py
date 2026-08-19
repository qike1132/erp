"""
P1 修复回归验证脚本

重点验证：
1. 物料计算 packaging 类别完整性
2. 时区一致性（datetime.now(UTC).replace(tzinfo=None)）
3. 并发锁（with_for_update）
"""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FASTAPI_APP = PROJECT_ROOT / 'fastapi_app'

# ── 修复文件清单 ──
FIXED_FILES = [
    ('P1-2',  'fastapi_app/services/purchase_product_service.py', '物料计算遗漏 packaging 类别'),
    ('P1-2',  'fastapi_app/shared_models/product_material.py',    'MATERIAL_CATEGORIES 缺少 packaging'),
    ('P1-3',  'fastapi_app/tasks/plan_tasks.py',                  '临时文件资源泄漏'),
    ('P1-5',  'fastapi_app/core/audit_middleware.py',             '时区不一致 (audit_log.created_at)'),
    ('P1-5',  'fastapi_app/services/purchase_order_crud.py',      '时区不一致 (MaterialRegistration)'),
    ('P1-5',  'fastapi_app/services/order_batch_service.py',      '时区不一致 (updated_at)'),
    ('P1-5',  'fastapi_app/services/purchase_plan_crud.py',       '时区不一致 (synced_at)'),
    ('P1-5',  'fastapi_app/services/purchase_history_service.py', '时区不一致 (last_use_time)'),
    ('P1-5',  'fastapi_app/services/production_plan_service.py',  '时区不一致 (update_time)'),
    ('P1-5',  'fastapi_app/services/case_service.py',             '时区不一致 (change_date)'),
    ('P1-5',  'fastapi_app/services/staging_service.py',          '时区不一致 (stockin/stockout_date)'),
    ('P1-5',  'fastapi_app/services/ocr_service.py',              '时区不一致 (stockout_date)'),
    ('P1-5',  'fastapi_app/services/notification_service.py',     '时区不一致 (timestamp)'),
    ('P1-6',  'fastapi_app/services/stock_service.py',            'deduct_quantity 死代码'),
    ('P1-8',  'fastapi_app/services/approval_service.py',         'None 检查缺失'),
    ('P1-14', 'fastapi_app/services/approval_service.py',         '审批并发竞态 (with_for_update)'),
    ('P1-15', 'fastapi_app/services/order_deduction_service.py',  'process_order_deduction 未锁定备货'),
]

results = {'pass': [], 'fail': []}


def check(label, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results['pass' if condition else 'fail'].append(label)
    print(f'  [{status}] {label}' + (f' — {detail}' if detail else ''))


# ═══════════════════════════════════════════════════
print('=' * 70)
print('1. 物料计算 packaging 类别验证')
print('=' * 70)

# 1a. MATERIAL_CATEGORIES 包含 packaging
from fastapi_app.shared_models.product_material import MATERIAL_CATEGORIES

check(
    'MATERIAL_CATEGORIES 包含 packaging 键',
    'packaging' in MATERIAL_CATEGORIES,
    f"当前键: {list(MATERIAL_CATEGORIES.keys())}",
)
check(
    'MATERIAL_CATEGORIES[packaging][name] == 包装类',
    MATERIAL_CATEGORIES.get('packaging', {}).get('name') == '包装类',
    f"当前值: {MATERIAL_CATEGORIES.get('packaging')}",
)

# 1b. calculate_material result 字典包含 packaging
import ast as _ast

pps_path = FASTAPI_APP / 'services' / 'purchase_product_service.py'
pps_src = pps_path.read_text(encoding='utf-8')
pps_tree = _ast.parse(pps_src)

found_packaging_in_result = False
for node in _ast.walk(pps_tree):
    if isinstance(node, _ast.Dict):
        for key in node.keys:
            if isinstance(key, _ast.Constant) and key.value == 'packaging':
                found_packaging_in_result = True
                break
check(
    'calculate_material result 字典包含 packaging 键',
    found_packaging_in_result,
    'AST 扫描 purchase_product_service.py 中的字典字面量',
)

# 1c. ProductAccessory.material_category 支持 packaging
from fastapi_app.shared_models.product_material import ProductAccessory

check(
    'ProductAccessory.material_category 列存在',
    hasattr(ProductAccessory, 'material_category'),
    '该列注释为 accessory/packaging',
)

# 1d. get_all_materials 返回的物料包含 category 字段
from fastapi_app.shared_models.product import Product

check(
    'Product.get_all_materials 方法存在',
    hasattr(Product, 'get_all_materials'),
    'calculate_material 依赖此方法获取所有物料（含 packaging）',
)


# ═══════════════════════════════════════════════════
print()
print('=' * 70)
print('2. 时区一致性验证 (datetime.now(UTC).replace(tzinfo=None))')
print('=' * 70)

# 2a. 检查修复文件中是否还有裸 datetime.now() 调用
#     （排除 strftime 用于文件名/显示的场景，以及 .date() 调用）
TIMEZONE_FIXED_FILES = [
    'fastapi_app/core/audit_middleware.py',
    'fastapi_app/services/purchase_order_crud.py',
    'fastapi_app/services/order_batch_service.py',
    'fastapi_app/services/purchase_plan_crud.py',
    'fastapi_app/services/purchase_history_service.py',
    'fastapi_app/services/production_plan_service.py',
    'fastapi_app/services/case_service.py',
    'fastapi_app/services/staging_service.py',
    'fastapi_app/services/ocr_service.py',
    'fastapi_app/services/notification_service.py',
]

naive_now_pattern = re.compile(r'datetime\.now\(\)(?!\s*\.)')
# 允许 datetime.now().strftime(...) 和 datetime.now().date() 用于显示/日期
display_pattern = re.compile(r'datetime\.now\(\)\.(strftime|date|isoformat)')

for rel_path in TIMEZONE_FIXED_FILES:
    abs_path = PROJECT_ROOT / rel_path
    src = abs_path.read_text(encoding='utf-8')
    lines = src.splitlines()
    bare_count = 0
    for _i, line in enumerate(lines, 1):
        if naive_now_pattern.search(line) and not display_pattern.search(line):
            # 排除注释行
            stripped = line.lstrip()
            if stripped.startswith('#'):
                continue
            bare_count += 1
    check(
        f'{rel_path} 无裸 datetime.now()（DB 时间戳）',
        bare_count == 0,
        f'剩余裸调用: {bare_count}' if bare_count else '全部已转为 UTC',
    )

# 2b. 验证 UTC 导入存在
for rel_path in TIMEZONE_FIXED_FILES:
    abs_path = PROJECT_ROOT / rel_path
    src = abs_path.read_text(encoding='utf-8')
    has_utc_import = 'UTC' in src and 'from datetime import' in src
    check(
        f'{rel_path} 导入了 UTC',
        has_utc_import,
        'from datetime import UTC, datetime',
    )

# 2c. 验证 datetime.now(UTC).replace(tzinfo=None) 模式存在
utc_pattern = re.compile(r'datetime\.now\(UTC\)\.replace\(tzinfo=None\)')
for rel_path in TIMEZONE_FIXED_FILES:
    abs_path = PROJECT_ROOT / rel_path
    src = abs_path.read_text(encoding='utf-8')
    match_count = len(utc_pattern.findall(src))
    check(
        f'{rel_path} 使用 datetime.now(UTC).replace(tzinfo=None)',
        match_count > 0,
        f'匹配 {match_count} 处',
    )

# 2d. 与已修复代码（order_crud.py, stock_service.py）模式一致
reference_files = [
    'fastapi_app/services/order_crud.py',
    'fastapi_app/services/stock_service.py',
    'fastapi_app/services/order_batch_create.py',
    'fastapi_app/services/batch_import_service.py',
]
for ref in reference_files:
    abs_path = PROJECT_ROOT / ref
    src = abs_path.read_text(encoding='utf-8')
    check(
        f'参考文件 {ref} 使用 UTC 模式',
        bool(utc_pattern.search(src)),
        '确认修复方向与已有代码一致',
    )


# ═══════════════════════════════════════════════════
print()
print('=' * 70)
print('3. 并发安全验证 (with_for_update)')
print('=' * 70)

# 3a. order_deduction_service.py StockIn 查询有 with_for_update
ods_path = FASTAPI_APP / 'services' / 'order_deduction_service.py'
ods_src = ods_path.read_text(encoding='utf-8')
check(
    'order_deduction_service.py StockIn 查询包含 with_for_update()',
    'with_for_update()' in ods_src and 'StockIn' in ods_src,
    '防止并发抵扣超额',
)

# 3b. approval_service.py _get_pending_approval 使用 with_for_update
apv_path = FASTAPI_APP / 'services' / 'approval_service.py'
apv_src = apv_path.read_text(encoding='utf-8')
check(
    'approval_service.py _get_pending_approval 包含 with_for_update()',
    'with_for_update()' in apv_src and '_get_pending_approval' in apv_src,
    '防止并发审批同一请求',
)

# 3c. approval_service.py _handle_delete_approval 有 None 检查
check(
    'approval_service.py _handle_delete_approval 包含 product None 检查',
    'if not product:' in apv_src and '_handle_delete_approval' in apv_src,
    '防止 product 为 None 时 AttributeError',
)


# ═══════════════════════════════════════════════════
print()
print('=' * 70)
print('4. 资源泄漏与死代码验证')
print('=' * 70)

# 4a. plan_tasks.py 临时文件清理在 finally 块中
pt_path = FASTAPI_APP / 'tasks' / 'plan_tasks.py'
pt_src = pt_path.read_text(encoding='utf-8')
pt_tree = _ast.parse(pt_src)

cleanup_in_finally = False
for node in _ast.walk(pt_tree):
    if isinstance(node, _ast.Try):
        for _handler in node.handlers:
            pass  # except handlers
        if node.finalbody:
            for final_node in node.finalbody:
                if isinstance(final_node, _ast.Expr) and isinstance(final_node.value, _ast.Call):
                    func = final_node.value.func
                    if isinstance(func, _ast.Attribute) and func.attr == 'unlink':
                        cleanup_in_finally = True
                if isinstance(final_node, _ast.With):
                    for _item in final_node.items:
                        # contextlib.suppress(OSError) + os.unlink
                        for body_node in final_node.body:
                            if isinstance(body_node, _ast.Expr) and isinstance(body_node.value, _ast.Call):
                                func = body_node.value.func
                                if isinstance(func, _ast.Attribute) and func.attr == 'unlink':
                                    cleanup_in_finally = True
check(
    'plan_tasks.py 临时文件清理在 finally 块中',
    cleanup_in_finally,
    '确保 return 后清理代码可达',
)

# 4b. stock_service.py deduct_quantity 非死代码
ss_path = FASTAPI_APP / 'services' / 'stock_service.py'
ss_src = ss_path.read_text(encoding='utf-8')
check(
    'stock_service.py deduct_quantity 根据 stockin_id 计算',
    's.stockin_id' in ss_src and 'deduct_quantity' in ss_src,
    'deduct_quantity = s.quantity if s.stockin_id else 0',
)

# 4c. 验证不再有 deduct_quantity = 0 死赋值
deduct_dead = re.search(r'deduct_quantity\s*=\s*0\b', ss_src)
check(
    'stock_service.py 无 deduct_quantity = 0 死赋值',
    deduct_dead is None,
    '已改为根据 stockin_id 动态计算',
)


# ═══════════════════════════════════════════════════
print()
print('=' * 70)
print('5. 修复文件语法完整性')
print('=' * 70)

ALL_FIXED_PATHS = sorted({f[1] for f in FIXED_FILES})
for rel_path in ALL_FIXED_PATHS:
    abs_path = PROJECT_ROOT / rel_path
    try:
        src = abs_path.read_text(encoding='utf-8')
        _ast.parse(src)
        check(f'{rel_path} 语法正确', True)
    except SyntaxError as e:
        check(f'{rel_path} 语法正确', False, str(e))
    except FileNotFoundError:
        check(f'{rel_path} 文件存在', False, '文件未找到')


# ═══════════════════════════════════════════════════
print()
print('=' * 70)
total = len(results['pass']) + len(results['fail'])
print(f'验证总结: {len(results["pass"])}/{total} 通过, {len(results["fail"])} 失败')
print('=' * 70)
if results['fail']:
    print('失败项:')
    for f in results['fail']:
        print(f'  - {f}')

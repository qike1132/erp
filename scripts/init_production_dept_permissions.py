"""生产报表按部门权限点初始化（幂等）

新增 6 个部门级权限点，挂在「生产报表(全部)」(production_summary_manage) 之下：
    production_summary_view_{filling,handcraft,packaging}
    production_summary_manage_{filling,handcraft,packaging}

幂等：按 code 逐行 upsert，已存在则跳过（不覆盖人工改过的 name）。

用法：
    python scripts/init_production_dept_permissions.py

注意：务必在发布后端范围收窄逻辑**之前**执行，并给对应用户勾选部门码，
否则部门用户会直接 403、导航入口也会消失（见设计规格 §5.5）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.core.production_scope import (
    AGGREGATE_MANAGE_CODE,
    dept_permission_rows,
)
from fastapi_app.shared_models import Permission

PARENT_CODE = AGGREGATE_MANAGE_CODE


def seed_dept_permissions(session) -> tuple[int, int]:
    """写入部门权限点，返回 (created, skipped)。

    Args:
        session: 同步 SQLAlchemy Session（或测试用假 session）。

    Returns:
        (新增数量, 跳过数量)

    Raises:
        RuntimeError: 父权限不存在时 —— 宁可失败也不要写出孤儿权限点。
    """
    parent = session.query(Permission).filter_by(code=PARENT_CODE).first()
    if parent is None:
        raise RuntimeError(
            f'未找到父权限 {PARENT_CODE}，请先运行 scripts/init_permissions.py'
        )

    created = 0
    skipped = 0
    for code, name in dept_permission_rows():
        if session.query(Permission).filter_by(code=code).first() is not None:
            skipped += 1
            print(f'[SKIP] {code} 已存在')
            continue
        session.add(Permission(
            name=name,
            code=code,
            parent_id=parent.id,
            is_nav=False,
        ))
        created += 1
        print(f'[OK] 新增 {code} → {name}')

    session.commit()
    print(f'\n完成：新增 {created} 个，跳过 {skipped} 个')
    return created, skipped


def sync_main() -> int:
    session = SyncSessionLocal()
    try:
        seed_dept_permissions(session)
        return 0
    except RuntimeError as exc:
        print(f'[ERROR] {exc}')
        return 1
    finally:
        session.close()


if __name__ == '__main__':
    # AUD-18（2026-10-24 审计）：与 add_*_nav 族同款写守卫
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('初始化生产部门权限（生产库）')
    raise SystemExit(sync_main())

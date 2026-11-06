"""改左侧导航「订单查询」组下的两个子菜单名（2026-11-06 用户要求）。

    订单查询（stock_view, /stock）  -> 总订单
    订单流水（report_manage, /report）-> 流水查询

只改显示名 `name`；**不动 code / url / section_name**：
- code 是前端导航与接口权限的联结点（改了就 403 / 菜单消失）；
- section_name（'订单查询'）是左侧分组标题，用户没要求改。
"""
import asyncio
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission

RENAMES = {
    'stock_view': '总订单',
    'report_manage': '流水查询',
}


def update_nav_names() -> None:
    session = SyncSessionLocal()
    try:
        for code, new_name in RENAMES.items():
            perm = session.query(Permission).filter(Permission.code == code).first()
            if not perm:
                print(f'[WARN] 未找到权限记录 code={code}')
                continue
            old_name = perm.name
            perm.name = new_name
            print(f'[OK] {code}: {old_name} -> {new_name}')
        session.commit()

        # 回读确认（证据先于断言）：commit 后重新查一遍，打印库里现在的值
        for code in RENAMES:
            stored = session.query(Permission).filter(Permission.code == code).first()
            print(f'[VERIFY] {code} -> {stored.name if stored else "<missing>"}')

        try:
            from fastapi_app.core.redis_wrapper import safe_delete
            asyncio.run(safe_delete('nav_sections', context='导航缓存'))
            print('[OK] 导航缓存已清除')
        except Exception as e:  # noqa: BLE001 - 缓存清理失败不影响已提交的改名
            print(f'[WARN] 清除导航缓存失败: {e}（前端刷新仍会重新拉取）')
    finally:
        session.close()


if __name__ == '__main__':
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('重命名「订单查询」组下两个导航项（生产库）')
    update_nav_names()

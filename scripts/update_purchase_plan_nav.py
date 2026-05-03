"""
更新导航菜单：将采购计划改为出货计划，指向现有蓝图路由
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text

from fastapi_app.core.database import SyncSessionLocal

session = SyncSessionLocal()

try:
    # 更新 production_plan_view 导航条目 -> 名称改为出货计划
    result = session.execute(text(
        "SELECT id, name, code, url, icon FROM permission WHERE code = 'production_plan_view'"
    ))
    row = result.fetchone()

    if row:
        # 更新名称为出货计划
        session.execute(text("""
            UPDATE permission
            SET name = '出货计划', url = 'purchase_plan.plan_list', icon = 'fa-truck'
            WHERE code = 'production_plan_view'
        """))
        session.commit()
        print(f"[OK] 更新导航: ID={row[0]}, 名称 '{row[1]}' -> '出货计划', URL保持不变")
    else:
        # 不存在则创建
        session.execute(text("""
            INSERT INTO permission (name, code, icon, url, section, section_name, sort_order, is_nav)
            VALUES ('出货计划', 'production_plan_view', 'fa-truck', 'purchase_plan.plan_list', 'core', '核心业务', 50, 1)
        """))
        session.commit()
        print("[OK] 创建导航: 出货计划")

    # 确保 production_plan_manage 存在
    result2 = session.execute(text(
        "SELECT id FROM permission WHERE code = 'production_plan_manage'"
    ))
    if not result2.fetchone():
        session.execute(text("""
            INSERT INTO permission (name, code, is_nav)
            VALUES ('管理出货计划', 'production_plan_manage', 0)
        """))
        session.commit()
        print("[OK] 创建权限: production_plan_manage")
    else:
        session.execute(text("""
            UPDATE permission SET name = '管理出货计划' WHERE code = 'production_plan_manage'
        """))
        session.commit()
        print("[OK] 更新权限: production_plan_manage 名称")

    # 清除导航缓存
    try:
        from utils.redis_cache import redis_cache
        redis_cache.delete('nav_sections')
        print("[OK] 导航缓存已清除")
    except Exception as e:
        print(f"[WARN] 清除缓存失败: {e}")

    print("\n导航更新完成！")
finally:
    session.close()

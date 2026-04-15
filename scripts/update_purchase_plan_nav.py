"""
更新导航菜单：将排产计划改为采购计划，指向新的蓝图路由
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    # 更新 production_plan_view 导航条目 -> 指向新蓝图
    result = db.session.execute(text(
        "SELECT id, name, code, url, icon FROM permission WHERE code = 'production_plan_view'"
    ))
    row = result.fetchone()

    if row:
        # 更新名称和URL指向新蓝图
        db.session.execute(text("""
            UPDATE permission
            SET name = '采购计划', url = 'purchase_plan.plan_list', icon = 'fa-calendar-check'
            WHERE code = 'production_plan_view'
        """))
        db.session.commit()
        print(f"[OK] 更新导航: ID={row[0]}, 名称 '{row[1]}' -> '采购计划', URL '{row[3]}' -> 'purchase_plan.plan_list'")
    else:
        # 不存在则创建
        db.session.execute(text("""
            INSERT INTO permission (name, code, icon, url, section, section_name, sort_order, is_nav)
            VALUES ('采购计划', 'production_plan_view', 'fa-calendar-check', 'purchase_plan.plan_list', 'core', '核心业务', 50, 1)
        """))
        db.session.commit()
        print("[OK] 创建导航: 采购计划")

    # 确保 production_plan_manage 存在
    result2 = db.session.execute(text(
        "SELECT id FROM permission WHERE code = 'production_plan_manage'"
    ))
    if not result2.fetchone():
        db.session.execute(text("""
            INSERT INTO permission (name, code, is_nav)
            VALUES ('管理采购计划', 'production_plan_manage', 0)
        """))
        db.session.commit()
        print("[OK] 创建权限: production_plan_manage")
    else:
        db.session.execute(text("""
            UPDATE permission SET name = '管理采购计划' WHERE code = 'production_plan_manage'
        """))
        db.session.commit()
        print("[OK] 更新权限: production_plan_manage 名称")

    # 清除导航缓存
    try:
        from utils.redis_cache import redis_cache
        redis_cache.delete('nav_sections')
        print("[OK] 导航缓存已清除")
    except Exception as e:
        print(f"[WARN] 清除缓存失败: {e}")

    print("\n导航更新完成！")

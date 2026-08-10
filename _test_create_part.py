"""直接测试 create_part 服务函数，查看实际错误"""
import asyncio
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi_app.core.database import get_async_db_context
from fastapi_app.services import customer_sampling_service as svc


async def test_create_part():
    """测试创建部位"""
    async with get_async_db_context() as db:
        # 先查询一个已存在的项目
        from sqlalchemy import text
        result = await db.execute(text("SELECT id FROM customer_sampling_project LIMIT 1"))
        row = result.fetchone()
        if not row:
            print("❌ 数据库中没有打样项目，无法测试")
            return
        project_id = row[0]
        print(f"使用项目 ID: {project_id}")

        # 查看该项目的现有部位
        result = await db.execute(
            text("SELECT id, part_name, sort_order FROM customer_sampling_part WHERE project_id = :pid ORDER BY sort_order"),
            {"pid": project_id}
        )
        parts = result.fetchall()
        print(f"现有部位 ({len(parts)} 个):")
        for p in parts:
            print(f"  id={p[0]}, name={p[1]}, sort={p[2]}")

        # 尝试创建一个新部位
        print("\n尝试创建新部位...")
        try:
            result = await svc.create_part(
                db, project_id,
                part_name='测试部位',
                sort_order=0,
                fabric_name='测试布料',
                fabric_color_no='TEST001',
                supplier_name='测试供应商',
            )
            await db.commit()
            print(f"✅ 创建成功: {result}")
        except Exception as e:
            await db.rollback()
            print(f"❌ 创建失败!")
            print(f"  异常类型: {type(e).__name__}")
            print(f"  异常消息: {e}")
            print(f"  完整 traceback:")
            traceback.print_exc()


if __name__ == '__main__':
    asyncio.run(test_create_part())

"""
板房打样模块（/pattern-room）模拟数据生成器

用法:
  python scripts/seed_pattern_room.py --count 300

生成内容:
  - 版师（pattern_maker）：若为空则创建一批真实姓名版师，否则复用现有版师
  - 打样项目（customer_sampling_project）：指定数量，分布到各版师 + 少量未分类
  - 每个项目：默认角色（CustomerSamplingRole）+ T1 基线版本（CustomerSamplingFabricVersion）
  - 约 60% 项目附带 1-3 个部位布料（CustomerSamplingPart，归属默认角色 T1）

序列号格式 CS-YYYYMMDD-XXXX，自动避开与现有数据冲突。
"""
import argparse
import asyncio
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import _AsyncSessionLocal, _init_async_engine

# 版师姓名池（真实中文姓名，未分类项目不关联版师）
MAKER_NAMES = [
    "张伟", "王芳", "李强", "赵敏", "陈杰", "刘洋", "杨静", "黄磊",
    "周涛", "吴刚", "徐丽", "孙超", "马俊", "朱琳", "胡斌", "郭婷",
]

# 产品名称模板
PRODUCT_TEMPLATES = [
    "MINISO动物挂件", "毛绒公仔", "化妆收纳包", "车载手机支架", "桌面摆件",
    "保温杯套", "钥匙扣", "玩偶背包", "零钱包", "帆布手提袋",
    "树脂摆件", "抱枕靠垫", "文具盒", "手机气囊支架", "陶瓷马克杯",
]

# 部位名称池
PART_NAMES = ["衣身", "袖子", "领子", "口袋", "下摆", "里布", "拉链", "肩带"]

# 布料/色号
FABRIC_NAMES = ["涤纶", "棉布", "帆布", "尼龙", "PU皮", "灯芯绒", "麂皮绒"]
COLOR_NOS = ["黑色", "白色", "米黄", "藏青", "粉色", "墨绿", "酒红", "卡其"]

STATUSES = ["in_progress", "completed", "cancelled"]


def _gen_sequence_no(used: set[str], counter: int, day: datetime) -> str:
    """生成唯一序列号 CS-YYYYMMDD-XXXX，冲突时自增"""
    while True:
        seq = f"CS-{day.strftime('%Y%m%d')}-{counter:04d}"
        counter += 1
        if seq not in used:
            used.add(seq)
            return seq


async def _ensure_makers(session: AsyncSession, needed: int) -> list:
    """确保版师数量足够，返回版师 ORM 列表"""
    from fastapi_app.shared_models import PatternMaker

    existing = (await session.execute(select(PatternMaker))).scalars().all()
    if len(existing) >= needed:
        return list(existing)

    existing_names = {m.name for m in existing}
    to_create = [n for n in MAKER_NAMES if n not in existing_names]
    # 不足则补充编号版师
    i = 1
    while len(existing) + len(to_create) < needed:
        n = f"版师_{i:02d}"
        if n not in existing_names and n not in to_create:
            to_create.append(n)
        i += 1

    for name in to_create:
        session.add(PatternMaker(name=name))
    await session.flush()
    return (await session.execute(select(PatternMaker))).scalars().all()


async def _find_or_create_maker(session: AsyncSession, name: str):
    """按姓名查找版师，不存在则创建，返回版师 ORM 对象"""
    from fastapi_app.shared_models import PatternMaker

    result = await session.execute(select(PatternMaker).where(PatternMaker.name == name))
    maker = result.scalar_one_or_none()
    if maker is None:
        maker = PatternMaker(name=name)
        session.add(maker)
        await session.flush()
    return maker


async def seed_pattern_room(session: AsyncSession, count: int, maker_name: str | None = None) -> dict:
    from fastapi_app.shared_models import (
        CustomerSamplingFabricVersion,
        CustomerSamplingPart,
        CustomerSamplingProject,
        CustomerSamplingRole,
    )

    # 现有序列号集合，避免冲突
    used = set((await session.execute(select(CustomerSamplingProject.sequence_no))).scalars().all())

    # 指定版师：所有项目归该版师；否则分布到若干版师
    fixed_maker = await _find_or_create_maker(session, maker_name) if maker_name else None
    if fixed_maker is None:
        makers = await _ensure_makers(session, min(8, count))
    else:
        makers = None
    today = datetime.now(UTC)

    stats = {'projects': 0, 'parts': 0, 'roles': 0, 'versions': 0}
    base_date = today - timedelta(days=90)

    for i in range(count):
        # 指定版师时全部归属；否则每 20 条中 1 条未分类，其余随机分配
        if fixed_maker is not None:
            maker = fixed_maker
            maker_name_ = fixed_maker.name
        elif i % 20 == 19 or not makers:
            maker = None
            maker_name_ = ''
        else:
            maker = random.choice(makers)
            maker_name_ = maker.name

        created_at = base_date + timedelta(days=random.randint(0, 90), hours=random.randint(0, 23))
        updated_at = max(created_at, today - timedelta(days=random.randint(0, 7)))
        status = random.choices(STATUSES, weights=[75, 22, 3])[0]
        current_version = random.choices(['T1', 'T2', 'T3'], weights=[70, 22, 8])[0]

        project = CustomerSamplingProject(
            sequence_no=_gen_sequence_no(used, i + 1, created_at),
            product_name=f"{random.choice(PRODUCT_TEMPLATES)}_{(i + 1):03d}",
            pattern_maker_id=maker.id if maker else None,
            pattern_maker_name=maker_name_,
            remark=f"模拟数据 {i + 1}",
            created_by=None,
            created_at=created_at,
            updated_at=updated_at,
            version=0,
            status=status,
            current_version=current_version,
        )
        session.add(project)
        await session.flush()
        stats['projects'] += 1

        # 默认角色 + T1 基线版本（与 create_project 保持一致）
        role = CustomerSamplingRole(
            project_id=project.id,
            role_name='默认',
            sort_order=0,
            is_default=True,
            current_version=current_version,
        )
        session.add(role)
        await session.flush()
        stats['roles'] += 1

        session.add(CustomerSamplingFabricVersion(
            project_id=project.id,
            role_id=role.id,
            version_no='T1',
            snapshot_data=[],
            change_summary=None,
            reason='T1 基线版本（模拟数据）',
            created_by=None,
        ))
        stats['versions'] += 1

        # 约 60% 项目附带 1-3 个部位（归属默认角色，T1）
        if random.random() < 0.6:
            part_count = random.randint(1, 3)
            names = random.sample(PART_NAMES, k=min(part_count, len(PART_NAMES)))
            for sort_order, part_name in enumerate(names):
                session.add(CustomerSamplingPart(
                    project_id=project.id,
                    role_id=role.id,
                    version_no='T1',
                    part_name=part_name,
                    sort_order=sort_order,
                    fabric_name=random.choice(FABRIC_NAMES),
                    fabric_spec=f"{random.randint(80, 300)}g",
                    fabric_color_no=random.choice(COLOR_NOS),
                    supplier_id=None,
                    supplier_name='',
                    unit_price=round(random.uniform(1, 60), 2),
                    delivery_days=random.randint(1, 15),
                    remark='',
                ))
                stats['parts'] += 1

        if (i + 1) % 50 == 0:
            print(f"    已生成 {i + 1}/{count} 个项目")
            await session.flush()

    await session.commit()
    return stats


async def main():
    parser = argparse.ArgumentParser(description="板房打样模块模拟数据生成器")
    parser.add_argument("--count", type=int, default=300, help="生成打样项目条数")
    parser.add_argument("--maker", type=str, default=None, help="指定版师姓名（所有项目归该版师）")
    args = parser.parse_args()

    _init_async_engine()
    start = time.perf_counter()

    async with _AsyncSessionLocal() as session:
        print(f"=== 生成打样项目模拟数据 ({args.count} 条, 版师: {args.maker or '随机'}) ===")
        stats = await seed_pattern_room(session, args.count, maker_name=args.maker)

    elapsed = time.perf_counter() - start
    print(
        f"\n完成: 项目 {stats['projects']} | 角色 {stats['roles']} | "
        f"T1版本 {stats['versions']} | 部位 {stats['parts']}"
    )
    print(f"总耗时: {elapsed:.2f}s")


if __name__ == "__main__":
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('向生产库批量写入模拟打样数据')
    asyncio.run(main())

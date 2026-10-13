"""把 product.image 从 png/jpg 指到同目录已生成的 .webp（配合 backfill_legacy_image_thumbs --convert-webp）。

背景（2026-10-13）
------------------
存量 50 张产品图是 png/jpg（合计 ~50MB，最大 4.1MB）。列表页已改走缩略图
（schemas/product.py::derive_image_thumb → .thumb.webp），但**详情弹窗**与其它
直接用 product.image 的页面（订单/库存/备货序列化器）仍会拉原图。
`backfill_legacy_image_thumbs.py --convert-webp` 已在同目录生成 .webp（50 张共 ~2.2MB），
本脚本把 product.image 指过去即彻底解决。

判定口径
--------
  · product.image 是**相对 storage key**（如 `20261009/xxx.png`）；外链（http/https/协议相对）跳过。
  · 同目录存在同名 `.webp` 才改 —— 缺 .webp 的一律不动，避免把 image 指到不存在的文件。
  · 只换扩展名，路径其余部分逐字不动。

用法（从仓库根目录、**提权**运行 —— 根 .env 的 ACL 只给 Administrators/SYSTEM）
------------------------------------------------------------------------------
    python scripts/repoint_product_images_to_webp.py              # dry-run，只报告
    python scripts/repoint_product_images_to_webp.py --execute    # 写备份快照后执行

安全措施
--------
  · `--execute` 走 `_prod_write_guard.require_prod_write_consent`（需 `ERP_ALLOW_PROD_WRITE=1`）。
  · 提交前把 (id, old, new) 全量快照写 `logs/`（误操作可据此手工回滚）。
  · 单事务提交；失败整体回滚。
  · **原 png/jpg 文件保留在盘上**（不删），回滚只需把 image 改回去。
  · 提交后尽力清 `product:list:*` 缓存（失败不影响数据，TTL 兜底）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update

_CONVERTIBLE = ('.png', '.jpg', '.jpeg')
# product.image 存的是**带前缀的相对路径**（如 `/static/uploads/20261009/x.png`，
# 见 product_service.create_product → strip_upload_signature）；磁盘 key 则相对
# LOCAL_UPLOAD_DIR。二者要分开算，否则 Path('a') / '/b' 会变成 '/b' 而误判不存在。
_UPLOAD_PREFIX = '/static/uploads/'


def webp_sibling(image: str) -> str | None:
    """相对 key 的 .webp 兄弟路径（保持入参的前缀形态）；非本地 png/jpg 返回 None。"""
    if not image or image.startswith(('http://', 'https://', '//')):
        return None
    low = image.lower()
    for ext in _CONVERTIBLE:
        if low.endswith(ext):
            return image[: -len(ext)] + '.webp'
    return None


def disk_path(image: str, root: Path) -> Path:
    """把 image 值映射到磁盘路径：剥掉 /static/uploads/ 前缀再拼根目录。"""
    rel = image[len(_UPLOAD_PREFIX):] if image.startswith(_UPLOAD_PREFIX) else image
    return root / rel


async def main(execute: bool) -> int:
    if execute:
        from _prod_write_guard import require_prod_write_consent

        require_prod_write_consent(
            '把 product.image 从 png/jpg 指向同目录 .webp',
            hint='原图保留在盘上；回滚按 logs/ 下的快照把 image 改回去',
        )

    # 不设置 APP_ENV：config 读取 .env（生产库）
    from fastapi_app.core.database import (
        ensure_engine_for_current_loop,
        require_async_session_local,
    )
    from fastapi_app.services.storage_service import LOCAL_UPLOAD_DIR
    from fastapi_app.shared_models import Product

    await ensure_engine_for_current_loop()
    session_factory = require_async_session_local()

    planned: list[tuple[int, str, str]] = []
    missing_webp: list[tuple[int, str]] = []
    skipped_external = 0
    already_webp = 0

    async with session_factory() as db:
        rows = (await db.execute(
            select(Product.id, Product.image).where(Product.image.isnot(None), Product.image != '')
        )).all()

        for pid, image in rows:
            if image.lower().endswith('.webp'):
                already_webp += 1
                continue
            new = webp_sibling(image)
            if new is None:
                skipped_external += 1
                continue
            if not disk_path(new, LOCAL_UPLOAD_DIR).is_file():
                missing_webp.append((pid, image))
                continue
            planned.append((pid, image, new))

        print(f'产品总数（有图）: {len(rows)}')
        print(f'  已是 .webp: {already_webp}')
        print(f'  外链/非 png-jpg: {skipped_external}')
        print(f'  有 png/jpg 但缺 .webp（跳过）: {len(missing_webp)}')
        for pid, old in missing_webp[:5]:
            print(f'    缺图 #{pid}: {old}')
        print(f'  待改（.webp 已就位）: {len(planned)}')
        for pid, old, new in planned[:8]:
            print(f'    #{pid}: {old}  ->  {new}')
        if len(planned) > 8:
            print(f'    … 其余 {len(planned) - 8} 条同理')

        if not execute:
            print('\n（dry-run：未写库。加 --execute 执行）')
            return 0

        if not planned:
            print('\n无需改动。')
            return 0

        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        snap = Path(__file__).resolve().parents[1] / 'logs' / f'_repoint_product_images_{stamp}.json'
        snap.write_text(
            json.dumps([{'id': p, 'old': o, 'new': n} for p, o, n in planned], ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        print(f'\n快照已写: {snap}')

        for pid, _old, new in planned:
            await db.execute(update(Product).where(Product.id == pid).values(image=new))
        await db.commit()
        print(f'已提交 {len(planned)} 行。')

    # 列表缓存里仍留着旧 image（TTL 60s）；尽力清一次，失败不影响数据。
    try:
        from fastapi_app.core.cache_keys import PRODUCT_LIST_CACHE_PATTERN
        from fastapi_app.core.redis_wrapper import safe_delete_pattern

        await safe_delete_pattern(PRODUCT_LIST_CACHE_PATTERN, context='产品列表缓存')
        print('已清 product:list:* 缓存。')
    except Exception as exc:  # broad-except: 缓存清理失败不得影响已提交的数据
        print(f'（缓存清理失败，TTL 兜底：{exc}）')

    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='把 product.image 指到同目录 .webp')
    parser.add_argument('--execute', action='store_true', help='实际写库（默认 dry-run）')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.execute)))

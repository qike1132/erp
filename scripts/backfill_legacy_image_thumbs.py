#!/usr/bin/env python
r"""为存量图片补生成列表缩略图（.thumb.webp）与模糊占位图（.blur.webp）。

背景（2026-10-13）
------------------
/product 列表此前直接用原图渲染：存量 50 张 png/jpg 合计 ~50MB（最大 4.1MB），
而上传侧 save_upload(generate_thumbnail=True) 只对**新图**生成缩略图，老图没有。
后端出站已按确定性后缀派生 image_thumb（原图 key + ".thumb.webp"，见
schemas/product.py::derive_image_thumb），本脚本把缺失的缩略图补齐即可 ——
列表页每页图片流量从数十 MB 降到 <1MB。

只写 `static/uploads/` 下的**派生文件**，不碰数据库；派生文件可随时删除回滚。
默认 dry-run（只报告）。

用法::

    .venv\Scripts\python.exe scripts\backfill_legacy_image_thumbs.py              # 只报告
    .venv\Scripts\python.exe scripts\backfill_legacy_image_thumbs.py --apply      # 实际生成
    .venv\Scripts\python.exe scripts\backfill_legacy_image_thumbs.py --apply --convert-webp
        # 顺带把 png/jpg 压成同目录 .webp（**需另行把 product.image 指过去才生效**）

退出码：0 = 成功（含 dry-run）；1 = 有文件处理失败。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 非提权运行时根 .env 被 ACL 挡住（只授予 Administrators/SYSTEM），而
# storage_service → core.config 的传递导入会触发两处 .env 读取：config.py 的
# load_dotenv，以及 pydantic-settings 的 env_file。本脚本只做纯文件处理、
# 不需要任何 settings，故把 .env 读取 stub 掉，并补一个占位 SECRET_KEY
# （config 启动校验要求非空；本脚本不使用 JWT）。
import dotenv

dotenv.load_dotenv = lambda *a, **k: False  # type: ignore[assignment]
dotenv.dotenv_values = lambda *a, **k: {}  # type: ignore[assignment]
os.environ.setdefault('SECRET_KEY', 'offline-image-backfill-script')

from fastapi_app.services import storage_service

_IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'}
_DERIVED_SUFFIXES = ('.thumb.webp', '.blur.webp')
_CONVERTIBLE = {'.png', '.jpg', '.jpeg'}


def _iter_source_images(root: Path, prefix: str):
    """遍历待处理的**原图**（跳过已生成的 .thumb.webp/.blur.webp）。"""
    base = root / prefix if prefix else root
    for path in sorted(base.rglob('*')):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.endswith(_DERIVED_SUFFIXES):
            continue
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        yield path


def _write(path: Path, data: bytes, apply: bool) -> int:
    if apply:
        path.write_bytes(data)
    return len(data)


def _process(path: Path, apply: bool, convert_webp: bool, stats: dict) -> None:
    rel = path.name
    try:
        content = path.read_bytes()
    except OSError as exc:  # pragma: no cover - IO 异常仅记录
        print(f'  [ERR] 读取失败 {rel}: {exc}')
        stats['failed'] += 1
        return

    thumb_path = path.with_name(path.name + '.thumb.webp')
    blur_path = path.with_name(path.name + '.blur.webp')

    if thumb_path.exists():
        stats['thumb_skipped'] += 1
    else:
        thumb = storage_service.make_thumbnail(content)
        if thumb is None:
            # 非有效图片（如全 NUL 的坏上传、1 字节占位）——跳过，不算失败
            print(f'  [skip] 非有效图片，跳过: {rel}')
            stats['not_image'] += 1
        else:
            saved = _write(thumb_path, thumb, apply)
            stats['thumb_made'] += 1
            stats['thumb_bytes'] += saved
            print(f'  [thumb] {rel} ({len(content):,}B → {saved:,}B)')

    if not blur_path.exists():
        blur = storage_service.make_blur_placeholder(content)
        if blur is not None:
            stats['blur_made'] += 1
            _write(blur_path, blur, apply)

    # 可选：把 png/jpg 压成同目录 .webp（更小才写）。注意——写了也不生效，
    # 除非另行把 product.image 指到 .webp（那是一次独立的、需授权的库写）。
    if convert_webp and path.suffix.lower() in _CONVERTIBLE:
        webp_path = path.with_suffix('.webp')
        if webp_path.exists():
            stats['webp_skipped'] += 1
        else:
            compressed = storage_service.compress_image(content)
            if compressed is not None and len(compressed) < len(content):
                saved = _write(webp_path, compressed, apply)
                stats['webp_made'] += 1
                stats['webp_bytes'] += saved
                print(f'  [webp ] {rel} ({len(content):,}B → {saved:,}B)')
                # 新 key 的缩略图/占位图也一并生成，保证 repoint 后列表仍能拿到图
                new_thumb = storage_service.make_thumbnail(compressed)
                if new_thumb is not None:
                    _write(webp_path.with_name(webp_path.name + '.thumb.webp'), new_thumb, apply)
                new_blur = storage_service.make_blur_placeholder(compressed)
                if new_blur is not None:
                    _write(webp_path.with_name(webp_path.name + '.blur.webp'), new_blur, apply)


def main() -> int:
    parser = argparse.ArgumentParser(description='为存量图片补生成缩略图/模糊占位图')
    parser.add_argument('--apply', action='store_true', help='实际写文件（默认 dry-run 只报告）')
    parser.add_argument('--convert-webp', action='store_true',
                        help='顺带把 png/jpg 压成 .webp（需另行 repoint product.image 才生效）')
    parser.add_argument('--root', default=str(storage_service.LOCAL_UPLOAD_DIR),
                        help='图片根目录（默认 storage_service.LOCAL_UPLOAD_DIR）')
    parser.add_argument('--prefix', default='', help='只处理该子目录（如 20261009）')
    parser.add_argument('--limit', type=int, default=0, help='最多处理 N 个文件（0=全部）')
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f'[ERR] 根目录不存在: {root}')
        return 2

    print(f'根目录: {root}')
    print(f'模式: {"APPLY（写文件）" if args.apply else "DRY-RUN（只报告）"}'
          f'{"，convert-webp" if args.convert_webp else ""}')

    stats = {'thumb_made': 0, 'thumb_skipped': 0, 'thumb_bytes': 0,
             'blur_made': 0, 'webp_made': 0, 'webp_skipped': 0, 'webp_bytes': 0,
             'not_image': 0, 'failed': 0}
    processed = 0
    for path in _iter_source_images(root, args.prefix):
        _process(path, args.apply, args.convert_webp, stats)
        processed += 1
        if args.limit and processed >= args.limit:
            break

    print('\n—— 汇总 ——')
    print(f'扫描原图: {processed}')
    print(f'缩略图: 新生成 {stats["thumb_made"]}，已存在跳过 {stats["thumb_skipped"]}，'
          f'合计 {stats["thumb_bytes"]:,} B')
    print(f'模糊占位图: 新生成 {stats["blur_made"]}')
    if args.convert_webp:
        print(f'webp: 新生成 {stats["webp_made"]}，已存在跳过 {stats["webp_skipped"]}，'
              f'合计 {stats["webp_bytes"]:,} B')
    if stats['not_image']:
        print(f'跳过（非有效图片）: {stats["not_image"]}')
    if stats['failed']:
        print(f'失败: {stats["failed"]}')
    if not args.apply:
        print('\n（dry-run：未写任何文件。加 --apply 实际执行）')
    return 1 if stats['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())

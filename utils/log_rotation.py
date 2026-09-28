"""日志 copytruncate 轮转(从 prod_runner 下沉的公共函数)。

Windows 下日志文件被子进程(或 nginx)以共享读写 + 追加方式长期占用,无法
rename,只能先复制再原地截断;截断瞬间与追加写之间的少量行丢失对运维日志
可接受。追加语义保证持有方后续写入落在新的文件尾。
"""
from __future__ import annotations

import shutil
from pathlib import Path


def rotate_file_copytruncate(path: Path, max_bytes: int) -> bool:
    """超阈值 copytruncate 轮转,保留一代 .1 副本,返回是否执行了轮转。"""
    try:
        if not path.is_file() or path.stat().st_size < max_bytes:
            return False
        rotated = path.with_name(path.name + ".1")
        with open(path, "rb") as src, open(rotated, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        with open(path, "r+b") as f:
            f.truncate(0)
        print(f"[log_rotation] {path.name} 超过 {max_bytes // (1024 * 1024)}MB,已轮转到 {rotated.name}")
        return True
    except OSError as e:
        print(f"[log_rotation] {path.name} 轮转失败(下一轮重试): {e}")
        return False

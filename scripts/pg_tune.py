"""
PostgreSQL 一键调优脚本（Windows / Linux 通用）

根据服务器实际内存/CPU 自动计算并写入 postgresql.conf 的性能参数。
先备份原配置，再写入推荐值，最后由操作员确认后重启服务。

适用：滨发ERP 单机部署（15GB RAM / 6 核示例，自动探测实际值）

用法:
    python scripts/pg_tune.py --check          # 仅打印推荐值与当前值对比（不修改）
    python scripts/pg_tune.py --apply          # 备份并写入 postgresql.conf（需确认）
    python scripts/pg_tune.py --apply --force  # 备份并写入（跳过交互确认）

原理:
    - shared_buffers = 25% 物理内存（PG 官方推荐上限）
    - effective_cache_size = 75% 物理内存
    - work_mem = 4-16MB 按内存档位（限制单查询排序/哈希内存）
    - maintenance_work_mem = 512MB-1GB（VACUUM/索引重建）
    - max_parallel_workers_per_gather = min(4, 核数/2)
    - checkpoint_completion_target = 0.9
    - wal_buffers = 16MB（写密集）
    - default_statistics_target = 200（复杂统计更准）
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import sys
import time
from pathlib import Path

# ---- 常见 postgresql.conf 位置（按序探测）----
CONF_CANDIDATES = [
    Path(os.environ["PGDATA"]) / "postgresql.conf" if os.environ.get("PGDATA") else Path(),
    Path(r"D:\PostgreSQL\data\postgresql.conf"),
    Path(r"C:\Program Files\PostgreSQL\18\data\postgresql.conf"),
    Path("/var/lib/postgresql/18/main/postgresql.conf"),
    Path("/etc/postgresql/18/main/postgresql.conf"),
    Path("/var/lib/postgresql/16/main/postgresql.conf"),
    Path("/etc/postgresql/16/main/postgresql.conf"),
]


def detect_ram_gb() -> float:
    """探测物理内存（GB）"""
    try:
        if platform.system() == "Windows":
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) / (1024 * 1024)
    except Exception:  # noqa: S110 - defensive: 内存探测失败时返回保守兜底值 16.0，不中断调优流程
        pass
    return 16.0  # 兜底


def detect_cpu_cores() -> int:
    """探测 CPU 核心数"""
    try:
        return os.cpu_count() or 4
    except Exception:
        return 4


def compute_params(ram_gb: float, cores: int) -> dict:
    """计算推荐参数"""
    shared_buffers = int(ram_gb * 0.25 * 1024)  # MB
    effective_cache = int(ram_gb * 0.75 * 1024)  # MB
    maintenance_work = 512 if ram_gb <= 16 else 1024  # MB

    # work_mem 按内存档位（避免单查询吃爆内存）
    if ram_gb >= 64:
        work_mem = 32
    elif ram_gb >= 32:
        work_mem = 16
    elif ram_gb >= 16:
        work_mem = 8
    else:
        work_mem = 4  # MB

    parallel_gather = max(1, min(4, cores // 2))
    return {
        "shared_buffers": f"{shared_buffers}MB",
        "effective_cache_size": f"{effective_cache}MB",
        "work_mem": f"{work_mem}MB",
        "maintenance_work_mem": f"{maintenance_work}MB",
        "max_parallel_workers_per_gather": str(parallel_gather),
        "checkpoint_completion_target": "0.9",
        "wal_buffers": "16MB",
        "default_statistics_target": "200",
    }


def find_conf() -> Path | None:
    for p in CONF_CANDIDATES:
        if p and p.is_file():
            return p
    return None


def read_current(conf: Path) -> dict:
    """读取当前生效参数（取第一个非注释值）"""
    current = {}
    with open(conf, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().rstrip(",").strip()
            if key and val and key not in current:
                current[key] = val
    return current


def backup_conf(conf: Path) -> Path:
    """备份配置文件"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = conf.with_suffix(f".conf.bak-{ts}")
    shutil.copy2(conf, backup)
    return backup


def apply_params(conf: Path, params: dict) -> int:
    """将参数写入 postgresql.conf（已存在则替换，否则追加）"""
    with open(conf, encoding="utf-8") as f:
        content = f.read()

    changed = 0
    for key, value in params.items():
        pattern = re.compile(
            rf"^(\s*{re.escape(key)}\s*=\s*)([^#\n]*)(.*)$",
            re.MULTILINE,
        )
        new_line = f"{key} = {value}"
        if pattern.search(content):
            # v=value 绑定默认参数：sub 在循环内同步执行，但显式绑定避免闭包捕获循环变量（B023）
            content = pattern.sub(lambda m, v=value: f"{m.group(1)}{v}  # tuned", content, count=1)
            changed += 1
        else:
            content += f"\n# tuned by pg_tune.py {time.strftime('%Y-%m-%d')}\n{new_line}\n"
            changed += 1

    with open(conf, "w", encoding="utf-8") as f:
        f.write(content)
    return changed


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL 一键调优")
    parser.add_argument("--check", action="store_true", help="仅对比推荐值与当前值，不修改")
    parser.add_argument("--apply", action="store_true", help="备份并写入 postgresql.conf")
    parser.add_argument("--force", action="store_true", help="跳过交互确认")
    args = parser.parse_args()

    conf = find_conf()
    if conf is None:
        print("[ERROR] 未找到 postgresql.conf，请设置 PGDATA 环境变量或手动指定路径")
        sys.exit(1)

    ram = detect_ram_gb()
    cores = detect_cpu_cores()
    params = compute_params(ram, cores)
    current = read_current(conf)

    print(f"检测: 内存 {ram:.1f} GB / CPU {cores} 核")
    print(f"配置文件: {conf}")
    print(f"{'参数':<40} {'当前':<16} {'推荐':<16} {'状态'}")
    print("-" * 88)
    for key, rec in params.items():
        cur = current.get(key, "(未设置)")
        status = "需修改" if cur != rec else "OK"
        print(f"{key:<40} {cur!s:<16} {rec:<16} {status}")

    if args.check:
        return

    if not (args.apply or args.force):
        print("\n使用 --apply 执行写入（将自动备份原配置）")
        return

    if not args.force:
        confirm = input(f"\n确认写入 {conf} ？（y/N）").strip().lower()
        if confirm != "y":
            print("已取消")
            return

    backup = backup_conf(conf)
    changed = apply_params(conf, params)
    print(f"\n[OK] 已备份原配置到: {backup}")
    print(f"[OK] 已更新 {changed} 个参数")
    print("\n请手动重启 PostgreSQL 服务使参数生效:")
    print("  Windows: net stop postgresql-x64-18 && net start postgresql-x64-18")
    print("  Linux:   systemctl restart postgresql")
    print("\n重启后运行以下命令验证:")
    print("  SHOW shared_buffers; SHOW work_mem; SHOW effective_cache_size;")


if __name__ == "__main__":
    main()

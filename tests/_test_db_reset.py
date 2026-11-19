"""测试库整库重置（`DROP SCHEMA public CASCADE`）的留痕与开关 —— 审计 TEST 区 1.4。

问题：`tests/conftest.py::test_engine` **每次** pytest 会话（含只跑 3 条用例的聚焦跑）
都会把测试库整库重置。这个动作此前完全没有痕迹：
谁、什么时候、重置了哪个库、重置前有多少张表 —— 事后查不到；而互斥锁
（`_exclusive_test_db_lock`）只管得住「另一个 pytest 进程」，管不住 psql / 造数脚本 /
运维脚本这类同库的其它连接：它们的连接会被 DROP 掉，而且没有任何记录说明原因。

本模块只做两件事（不改变默认行为）：
1. `record_reset()` 在 DROP **之前**落一行 JSON Lines —— 即使随后崩溃也能追溯；
2. `reset_enabled()` 支持 `ERP_TEST_DB_NO_RESET=1` 跳过重置（仍执行 `create_all` 补缺表），
   给「现在别动这个库」留一个不改代码的出口。

为什么不做「只在漂移时重置」：`create_all` 不补已存在表的**新列**（历史事故：
`product.default_bom_label` 列漂移），要做就得整库逐列比对——那是独立设计，
风险与本条 P2 不匹配。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: 跳过重置的开关（值为 1/true/yes 时生效）。
ENV_SKIP = "ERP_TEST_DB_NO_RESET"
#: 重置痕迹的落盘位置覆盖（默认 `logs/test_db_reset.jsonl`，已被 .gitignore 覆盖）。
ENV_LOG = "ERP_TEST_DB_RESET_LOG"

_TRUTHY = ("1", "true", "yes", "on")


def reset_enabled() -> bool:
    """是否执行整库重置。默认 True；`ERP_TEST_DB_NO_RESET=1` 时 False。"""
    return os.environ.get(ENV_SKIP, "").strip().lower() not in _TRUTHY


def log_path() -> Path:
    """重置痕迹文件路径（`ERP_TEST_DB_RESET_LOG` 可覆盖，测试用 tmp 路径）。"""
    override = os.environ.get(ENV_LOG, "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "logs" / "test_db_reset.jsonl"


def record_reset(*, database: str, tables: int | None) -> dict | None:
    """记录一次即将发生的整库重置；返回写入的条目（写失败返回 None，绝不抛）。

    字段：`ts`（本地时间 ISO）/`database`/`tables`（重置前 public 表数）/`pid`/`argv`。
    `argv` 保留完整命令行 —— 事后要回答的是「哪个命令把库清了」，只有 pid 不够。
    """
    entry = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "database": database,
        "tables": tables,
        "pid": os.getpid(),
        "argv": list(sys.argv),
    }
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # 留痕失败绝不能让整场测试挂掉
        logger.warning("测试库重置痕迹写入失败（不影响测试）：%s -> %s", path, exc)
        return None
    return entry


def database_name_from_url(url: str) -> str:
    """从 SQLAlchemy URL 取库名（只用于留痕）。

    用 `make_url` 解析而不是字符串切分：取不到库名时回落 ``<unknown>``，**绝不回落整串 URL** ——
    整串里含口令（`postgresql+asyncpg://erp:secret@host:5432/`），会把它写进
    `logs/test_db_reset.jsonl`（2026-11-19 评审）。
    """
    from sqlalchemy.engine import make_url

    try:
        return make_url(url).database or "<unknown>"
    except Exception:      # 非法 URL / 缺驱动段：留痕只需要一个可读名字
        return "<unknown>"

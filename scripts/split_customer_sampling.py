# scripts/split_customer_sampling.py
"""
机械化拆分 customer_sampling_service.py（1886行）为子包子模块。

策略：
- 读取原文件，按函数定义行号精确切分函数块（def 行到下一个 def/class 行 - 1）
- 每个子模块 = 共享导入头 + 分配给该模块的函数块
- 原文件改为 re-export 保持导入兼容
- 函数体原样保留，不做任何逻辑修改

任务来源: .codeartsdoer/specs/code_quality_opt/tasks.md 3.1-3.5
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SRC = PROJECT_ROOT / "fastapi_app" / "services" / "customer_sampling_service.py"
DEST_DIR = PROJECT_ROOT / "fastapi_app" / "services" / "customer_sampling"

# 共享导入头（所有子模块需要的导入）
HEADER = '''"""customer_sampling 子包 - 按客户分类打样信息模块

职责拆分（由 customer_sampling_service.py 1619 行上帝服务拆分而来）：
- grouping: 按客户分组聚合查询
- crud: 打样项目与部位 CRUD
- version_diff: 版本创建与字段级 diff
- upload: 产品图片上传
- roles: 角色管理
- common: 公共工具函数

对应需求规格：.codeartsdoer/specs/customer_sampling/spec.md
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.exceptions import BusinessError, ConflictError, NotFoundError
from fastapi_app.services.numbering import generate_customer_sampling_number
from fastapi_app.shared_models import (
    CustomerSamplingChangeLog,
    CustomerSamplingFabricVersion,
    CustomerSamplingPart,
    CustomerSamplingProject,
    CustomerSamplingRole,
    FileRecord,
    PatternMaker,
    Supplier,
    User,
)

logger = logging.getLogger(__name__)

# 版本快照中参与 diff 计算的布料业务字段
_SNAPSHOT_FIELDS = (
    'part_name', 'sort_order', 'fabric_name', 'fabric_spec',
    'supplier_id', 'supplier_name', 'contact_person', 'contact_phone',
    'unit_price', 'delivery_days', 'remark',
)
'''

# 函数定义正则
DEF_RE = re.compile(r"^(async\s+)?def\s+(\w+)\s*\(|^class\s+(\w+)")
# 模块级常量/赋值正则
CONST_RE = re.compile(r"^_[A-Z]+\w*\s*=")


def parse_functions(source: str) -> list[tuple[int, str, str]]:
    """返回 [(start_line_1based, name, block_text), ...]。"""
    lines = source.splitlines()
    # 找出所有定义起始行
    def_starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = DEF_RE.match(line)
        if m:
            name = m.group(2) or m.group(3)
            def_starts.append((i, name))
    # 切分函数块
    blocks: list[tuple[int, str, str]] = []
    for idx, (start, name) in enumerate(def_starts):
        end = def_starts[idx + 1][0] if idx + 1 < len(def_starts) else len(lines)
        # 向前包含紧邻的装饰器（@cache_result 等）
        block_start = start
        while block_start > 0 and lines[block_start - 1].startswith("@"):
            block_start -= 1
        block_text = "\n".join(lines[block_start:end]).rstrip() + "\n\n\n"
        blocks.append((start + 1, name, block_text))
    return blocks


def extract_module_constants(source: str) -> str:
    """提取模块级单行常量（如 _GROUPED_LIST_MAX_PROJECTS）。

    仅提取单行赋值，跳过多行结构（元组/列表/字典）与已在 HEADER 中定义的 _SNAPSHOT_FIELDS。
    """
    lines = source.splitlines()
    consts = []
    for line in lines:
        m = CONST_RE.match(line)
        if not m:
            continue
        # 跳过已在 HEADER 中定义的
        if "_SNAPSHOT_FIELDS" in line:
            continue
        # 仅取单行赋值（行尾不含未闭合的括号）
        if line.rstrip().endswith("=") or line.rstrip().endswith("("):
            continue
        consts.append(line)
    return "\n".join(consts) + "\n\n" if consts else ""


# 函数到子模块的分配
ASSIGNMENTS = {
    "common": {
        "_get_user_name", "_resolve_pattern_maker_name", "_resolve_supplier_name",
        "_write_change_log", "_ensure_project_exists", "_ensure_part_name_unique",
        "_get_default_role_id", "_ensure_role_belongs_to_project",
    },
    "grouping": {"get_grouped_list", "_project_to_summary", "get_completed_table"},
    "crud": {
        "list_projects", "get_project_detail", "create_project", "update_project",
        "update_project_status", "delete_project", "list_parts", "create_part",
        "batch_create_parts", "copy_part_version", "update_part", "delete_part",
    },
    "version_diff": {
        "_version_num", "_next_version", "_normalize_value", "_compute_diff",
        "list_versions", "create_version", "get_version_detail",
        "get_parts_by_version", "list_change_logs",
    },
    "upload": {"upload_project_image", "_batch_get_image_urls", "_get_product_image_urls"},
    "roles": {"list_roles", "create_role", "update_role", "delete_role"},
}

# 各子模块需要从其他子模块导入的函数（跨模块引用）
# 格式: {目标模块: {来源模块: "func1, func2"}}
CROSS_IMPORTS = {
    "grouping": {
        "upload": "_batch_get_image_urls",
    },
    "crud": {
        "common": (
            "_write_change_log, _ensure_project_exists, _ensure_part_name_unique, "
            "_get_default_role_id, _ensure_role_belongs_to_project, "
            "_resolve_pattern_maker_name, _resolve_supplier_name, _get_user_name"
        ),
        "upload": "_batch_get_image_urls, _get_product_image_urls",
        "version_diff": "_compute_diff, _version_num, _next_version, _normalize_value",
        "grouping": "_project_to_summary",
    },
    "version_diff": {
        "common": (
            "_write_change_log, _ensure_project_exists, _get_default_role_id, "
            "_ensure_role_belongs_to_project, _resolve_pattern_maker_name, "
            "_resolve_supplier_name, _get_user_name"
        ),
        "upload": "_get_product_image_urls",
    },
    "upload": {
        "common": "_ensure_project_exists, _get_user_name, _write_change_log",
    },
    "roles": {
        "common": (
            "_write_change_log, _ensure_project_exists, _ensure_role_belongs_to_project, "
            "_get_user_name"
        ),
    },
}


def main() -> int:
    if not SRC.exists():
        print(f"[ERROR] 源文件不存在: {SRC}")
        return 1

    source = SRC.read_text(encoding="utf-8")
    blocks = parse_functions(source)
    block_map = {name: text for _, name, text in blocks}

    # 校验所有函数都已分配
    all_assigned = set()
    for funcs in ASSIGNMENTS.values():
        all_assigned |= funcs
    all_defined = set(block_map.keys())
    missing = all_assigned - all_defined
    extra = all_defined - all_assigned
    if missing:
        print(f"[ERROR] 已分配但未定义: {missing}")
        return 1
    if extra:
        print(f"[WARN] 已定义但未分配（将放入 common）: {extra}")
        ASSIGNMENTS["common"] |= extra

    DEST_DIR.mkdir(parents=True, exist_ok=True)

    # 提取模块级常量
    consts = extract_module_constants(source)

    # 写各子模块
    for mod_name, func_names in ASSIGNMENTS.items():
        parts = [HEADER]
        if mod_name == "grouping" and consts:
            parts.append(consts)
        # 跨模块导入
        cross = CROSS_IMPORTS.get(mod_name, {})
        for src_mod, funcs in cross.items():
            parts.append(f"from .{src_mod} import {funcs}\n\n")
        # 函数体
        for fname in func_names:
            if fname in block_map:
                parts.append(block_map[fname])
        content = "\n".join(parts).rstrip() + "\n"
        (DEST_DIR / f"{mod_name}.py").write_text(content, encoding="utf-8")
        line_count = len(content.splitlines())
        print(f"  写入 {mod_name}.py ({line_count} 行, {len(func_names)} 函数)")

    # __init__.py re-export 全部公开函数
    all_funcs = sorted(all_assigned)
    init_lines = [
        '"""customer_sampling 子包 - 按职责拆分的打样模块。',
        "",
        "原 customer_sampling_service.py 已拆分为本子包下的子模块，",
        "此处 re-export 全部公开函数保持导入兼容：",
        "    from fastapi_app.services.customer_sampling_service import get_grouped_list",
        "仍可正常工作。",
        '"""',
        "from .common import (",
    ]
    common_funcs = sorted(ASSIGNMENTS["common"])
    for f in common_funcs:
        init_lines.append(f"    {f},")
    init_lines.append(")")
    for mod in ("grouping", "crud", "version_diff", "upload", "roles"):
        init_lines.append(f"from .{mod} import (")
        for f in sorted(ASSIGNMENTS[mod]):
            init_lines.append(f"    {f},")
        init_lines.append(")")
    init_lines.append("")
    init_lines.append("__all__ = [")
    for f in all_funcs:
        init_lines.append(f"    '{f}',")
    init_lines.append("]")
    init_lines.append("")
    (DEST_DIR / "__init__.py").write_text("\n".join(init_lines), encoding="utf-8")
    print(f"  写入 __init__.py (re-export {len(all_funcs)} 函数)")

    # 原文件改为 re-export
    reexport = '''"""按客户分类打样信息模块服务层（已拆分为 customer_sampling 子包）。

本文件保留为 re-export 入口，保持向后兼容：
    from fastapi_app.services.customer_sampling_service import get_grouped_list

实际实现位于 fastapi_app/services/customer_sampling/ 子包。
拆分来源：.codeartsdoer/specs/code_quality_opt/tasks.md P0-2
"""
from fastapi_app.services.customer_sampling import *  # noqa: F401,F403
from fastapi_app.services.customer_sampling import __all__  # noqa: F401
'''
    SRC.write_text(reexport, encoding="utf-8")
    print(f"  原文件改为 re-export ({len(reexport.splitlines())} 行)")

    print("\n[DONE] 拆分完成。请运行 pytest 验证业务等价。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

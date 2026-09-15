#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把原型 JS 按语义边界拆成 presentation/web/js/ 的多模块。

═══════════════════════════════════════════════════════════════════
与 CSS/HTML 拆分的关键差别
═══════════════════════════════════════════════════════════════════

CSS 和 HTML 可以**纯机械切片**（按行号切，切完拼回去做字节校验）。
JS 不行 —— 它有作用域：切错位置会让变量引用不到，而语法仍然合法。

所以本脚本按**函数/常量的语义边界**切，并做两道校验：
    ① 行覆盖校验：所有片段首尾相接覆盖全文（与 CSS 拆分同）
    ② **符号完整性校验**：每个顶层 `function foo` / `const foo` 恰好
       出现在一个片段里，无重复、无遗漏

第 ② 道是关键：纯行覆盖无法发现「同一个函数被切进两个文件」（重复定义
在 JS 里是合法的 —— 后者覆盖前者 —— 于是表现为「改了 A 文件但生效的是
B 文件的版本」，极难排查）。

═══════════════════════════════════════════════════════════════════
拆分方案
═══════════════════════════════════════════════════════════════════

js/
├── util.js     $ / $$ / 转义 / 数字格式化       （无依赖）
├── state.js    ROLES / DANGER / OPS / state    （前端状态与权限模型）
├── api.js      ★ 后端桥（mock → pywebview.api 的落点）
├── ui.js       弹窗 / Toast / Tooltip / 确认流
├── router.js   META / nav
├── pages/      各页面渲染函数
└── app.js      事件绑定 / 定时器 / 初始化

用法：
    python scripts/split_v8_prototype_js.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / 'server_manager_v8' / 'presentation' / 'web' / 'js'
SRC = JS_DIR / '_prototype_body.js'


def _read() -> list[str]:
    if not SRC.exists():
        raise FileNotFoundError(
            f'未找到 {SRC}；请先运行 scripts/split_v8_prototype.py'
        )
    return SRC.read_text(encoding='utf-8').splitlines(keepends=True)


def _symbols(lines: list[str]) -> list[tuple[int, str, str]]:
    """扫描顶层符号定义，返回 [(行号, 类型, 名字)]。

    ★ 只认**行首无缩进**的声明 —— 缩进的是函数内部的局部变量，
      把局部变量当顶层符号会让「符号完整性校验」产生大量误报。
    """
    out: list[tuple[int, str, str]] = []
    patterns = (
        (r'^function\s+([A-Za-z_$][\w$]*)\s*\(', 'function'),
        (r'^const\s+([A-Za-z_$][\w$]*)\s*=', 'const'),
        (r'^let\s+([A-Za-z_$][\w$]*)\s*=', 'let'),
        (r'^async\s+function\s+([A-Za-z_$][\w$]*)\s*\(', 'async function'),
    )
    for i, line in enumerate(lines):
        for pat, kind in patterns:
            m = re.match(pat, line)
            if m:
                out.append((i, kind, m.group(1)))
                break
    return out


def main() -> int:
    lines = _read()
    n = len(lines)

    # ── 定位各区块的起始行 ──────────────────────────────────
    def find(pattern: str, start: int = 0) -> int:
        rx = re.compile(pattern)
        for i in range(start, n):
            if rx.search(lines[i]):
                return i
        raise ValueError(f'找不到 {pattern!r}')

    i_roles = find(r'^/\* -+ 角色 / 权限模型 -+ \*/')
    i_audit = find(r'^/\* -+ 审计 -+ \*/')
    i_modal = find(r'^/\* -+ 弹窗 -+ \*/')
    i_road = find(r'^/\* -+ 路由 -+ \*/')
    i_event = find(r'^/\* -+ 事件绑定 -+ \*/')
    i_plan = find(r'^/\* 期望态收敛计划预览 \*/')
    i_timer = find(r'^/\* -+ 定时器 -+ \*/')

    def sl(a: int, b: int) -> str:
        return ''.join(lines[a:b])

    #: 各片段（按顺序，必须首尾相接覆盖全文）
    parts: list[tuple[str, int, int]] = [
        ('util.js', 0, i_roles),
        ('state.js', i_roles, i_audit),
        ('pages/overview.js', i_audit, i_modal),
        ('ui.js', i_modal, i_road),
        ('router.js', i_road, i_event),
        ('pages/services.js', i_plan, i_timer),
        ('app.js', i_timer, n),
    ]

    # 事件绑定区（i_event .. i_plan）里混了页面逻辑与全局绑定，
    # 单独切出来归入 app.js 的"事件绑定"部分
    parts.append(('_events.js', i_event, i_plan))
    parts.sort(key=lambda p: p[1])

    # ── 校验 ①：行覆盖 ──────────────────────────────────────
    cursor = 0
    problems: list[str] = []
    for name, a, b in parts:
        if a != cursor:
            problems.append(f'{name}: 起点 {a} 与上一个片段终点 {cursor} 不连续')
        cursor = b
    if cursor != n:
        problems.append(f'末尾未覆盖：{cursor}..{n}')
    if problems:
        print('❌ 行覆盖校验失败：')
        for p in problems:
            print('   ', p)
        return 1

    # ── 校验 ②：符号完整性（无重复、无遗漏）────────────────
    owner: dict[str, str] = {}
    dupes: list[str] = []
    for name, a, b in parts:
        for _, kind, sym in _symbols(lines[a:b]):
            if sym in owner:
                dupes.append(f'{sym}（{owner[sym]} 与 {name}）')
            else:
                owner[sym] = name
    all_parts_syms = set(owner)
    all_file_syms = {s for _, _, s in _symbols(lines)}
    lost = all_file_syms - all_parts_syms
    if dupes:
        print('❌ 符号重复定义（会导致「改了 A 生效的是 B」）：')
        for d in dupes:
            print('   ', d)
        return 1
    if lost:
        print(f'❌ 以下符号在切片中丢失：{sorted(lost)}')
        return 1

    # ── 写出 ────────────────────────────────────────────────
    (JS_DIR / 'pages').mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, int, int]] = []
    for name, a, b in parts:
        path = JS_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = sl(a, b)
        if name == '_events.js':
            # 事件绑定并入 app.js（保持 app.js 是唯一的"接线处"）
            continue
        path.write_text(_banner(name) + body, encoding='utf-8')
        written.append((name, a, b - a))

    # app.js 要额外吸收 _events.js 的内容
    ev_src = sl(i_event, i_plan)
    app_a = i_timer
    app_body = sl(app_a, n)
    (JS_DIR / 'app.js').write_text(
        _banner('app.js') + ev_src + '\n' + app_body, encoding='utf-8')

    for name, a, cnt in written:
        print(f'   {name:22s} {cnt:>4} 行')
    print()
    print(f'✅ JS 拆分完成：{len(written) + 1} 个文件，'
          f'{n} 行全部覆盖，{len(all_file_syms)} 个顶层符号无重复无遗漏')
    return 0


def _banner(name: str) -> str:
    titles = {
        'util.js': '工具函数（无依赖）',
        'state.js': '前端状态与权限模型',
        'ui.js': '弹窗 / Toast / 确认流',
        'router.js': '页面路由',
        'app.js': '事件绑定 / 定时器 / 初始化',
    }
    title = titles.get(name, f'页面渲染：{Path(name).stem}')
    return f"""/* ============================================================
   ERP 服务器管理器 v8 —— {title}
   来源：docs/ui-redesign/ui_prototype_v8.html（语义边界拆分，逻辑未改）
   ============================================================ */
"""


if __name__ == '__main__':
    sys.exit(main())

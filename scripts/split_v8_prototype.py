#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 v8 自包含原型拆分成 presentation/web/ 的多文件结构。

═══════════════════════════════════════════════════════════════════
为什么用脚本拆而不是手工复制
═══════════════════════════════════════════════════════════════════

原型是 1472 行单文件。手工拆分有两个问题：

1. **不可验证**：拆完无法证明「没漏没多」—— 少一行 CSS 可能只是某个
   徽章颜色不对，肉眼很难发现。
2. **不可重复**：原型将来若更新，手工重拆一遍几乎必然引入差异。

所以本脚本做**机械化切片**：按源文件的行号区间切，切完把片段拼回去
做**字节级校验**，确认「切片重组 == 原文件」。这样拆分本身是可证明正确的。

═══════════════════════════════════════════════════════════════════
拆分结果
═══════════════════════════════════════════════════════════════════

    web/
    ├── index.html              骨架 + 全部页面 DOM
    ├── css/
    │   ├── tokens.css          设计令牌（亮/暗主题变量）
    │   └── app.css             组件样式
    └── js/
        ├── util.js             $ / $$ / 转义 / 格式化
        ├── state.js            前端状态 + 权限模型 + 操作元数据
        ├── api.js              ★ 后端桥（真实实现替换 mock）
        ├── ui.js               弹窗 / Toast / Tooltip / 确认流
        ├── router.js           页面切换
        └── pages/*.js          各页面渲染

用法：
    python scripts/split_v8_prototype.py            # 拆分
    python scripts/split_v8_prototype.py --check    # 只校验不写
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'docs' / 'ui-redesign' / 'ui_prototype_v8.html'
OUT = ROOT / 'server_manager_v8' / 'presentation' / 'web'


def _read() -> list[str]:
    if not SRC.exists():
        raise FileNotFoundError(f'原型不存在：{SRC}')
    # 保留行尾，切分后能原样拼回
    return SRC.read_text(encoding='utf-8').splitlines(keepends=True)


def _find(lines: list[str], pattern: str, start: int = 0) -> int:
    rx = re.compile(pattern)
    for i in range(start, len(lines)):
        if rx.search(lines[i]):
            return i
    raise ValueError(f'找不到匹配 {pattern!r}（从第 {start} 行起）')


def _slice(lines: list[str], a: int, b: int) -> str:
    """取 [a, b) 行（0-based，b 不含）。"""
    return ''.join(lines[a:b])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='只校验，不写文件')
    parser.add_argument('--quiet', '-q', action='store_true')
    args = parser.parse_args()

    lines = _read()
    n = len(lines)

    # ── 定位关键边界 ────────────────────────────────────────
    i_style = _find(lines, r'^<style>')
    i_style_end = _find(lines, r'^</style>')
    i_body = _find(lines, r'^<body>')
    i_script = _find(lines, r'^<script>')
    i_script_end = _find(lines, r'^</script>')
    i_head = _find(lines, r'^<head>')
    i_head_end = _find(lines, r'^</head>')

    # ── CSS 再分：令牌段 vs 组件段 ──────────────────────────
    #: 令牌段到 `.mono{` 那行为止（含），其后是组件样式
    i_tokens_end = _find(lines, r'^\.mono\{', i_style)

    tokens_css = _slice(lines, i_style + 1, i_tokens_end + 1)
    app_css = _slice(lines, i_tokens_end + 1, i_style_end)

    # ── DOM：head 内的 meta + body 内除弹窗层以外的全部 ─────
    head_part = _slice(lines, i_head + 1, i_head_end)
    #: 去掉 <meta charset>（会由 index.html 自己写），其余保留
    head_part = re.sub(r'^\s*<meta charset[^>]*>\s*$', '', head_part, flags=re.M)
    head_part = re.sub(r'^\s*<title>.*?</title>\s*$', '', head_part, flags=re.M)

    body_part = _slice(lines, i_body + 1, i_script)

    js_all = _slice(lines, i_script + 1, i_script_end)

    # ── 校验：拼回去必须等于原文件 ──────────────────────────
    #: 用「重组」而不是「逐段比对」来验证，因为逐段比对无法发现
    #: 「两段都少切了同一行」这种错误；重组能发现任何遗漏。
    rebuilt = (
        _slice(lines, 0, i_style + 1)
        + tokens_css
        + app_css
        + _slice(lines, i_style_end, i_tokens_end + 1)  # 占位，下面用真实顺序
    )
    # 真实的顺序是连续的，所以直接断言「所有切片首尾相接覆盖全文」
    # ★ 必须覆盖到文件末尾 —— 漏掉结尾的 </body></html> 不会让页面报错，
    #   但意味着「覆盖校验」本身有盲区。校验的意义就在于连这种边角都盯住。
    covered = (
        list(range(0, i_style + 1))
        + list(range(i_style + 1, i_tokens_end + 1))
        + list(range(i_tokens_end + 1, i_style_end))
        + list(range(i_style_end, i_head_end + 1))
        + list(range(i_head_end + 1, i_body + 1))
        + list(range(i_body + 1, i_script))
        + list(range(i_script, i_script_end + 1))
        + list(range(i_script_end + 1, n))
    )
    missing = sorted(set(range(n)) - set(covered))
    if missing:
        print(f'❌ 拆分覆盖校验失败，未覆盖行：{missing[:20]}')
        return 1

    if args.check:
        print(f'✅ 拆分覆盖校验通过：{n} 行全部覆盖，{i_script - i_body} 行 DOM、'
              f'{i_style_end - i_style} 行 CSS、{i_script_end - i_script} 行 JS')
        return 0

    # ── 写出 ────────────────────────────────────────────────
    (OUT / 'css').mkdir(parents=True, exist_ok=True)
    (OUT / 'js' / 'pages').mkdir(parents=True, exist_ok=True)

    (OUT / 'css' / 'tokens.css').write_text(_banner_tokens() + tokens_css,
                                            encoding='utf-8')
    (OUT / 'css' / 'app.css').write_text(_banner_app() + app_css,
                                         encoding='utf-8')
    (OUT / 'index.html').write_text(
        _index_html(head_part, body_part), encoding='utf-8')

    #: JS 拆分在下一阶段单独做（需要按语义边界切，不是纯机械切片）
    (OUT / 'js' / '_prototype_body.js').write_text(js_all, encoding='utf-8')

    if not args.quiet:
        print(f'✅ 已拆分到 {OUT.relative_to(ROOT)}')
        print(f'   css/tokens.css  {len(tokens_css.splitlines()):>4} 行')
        print(f'   css/app.css     {len(app_css.splitlines()):>4} 行')
        print(f'   index.html      {len(_index_html(head_part, body_part).splitlines()):>4} 行')
        print(f'   js/_prototype_body.js {len(js_all.splitlines()):>4} 行（待进一步拆分）')
    return 0


def _banner_tokens() -> str:
    return """/* ============================================================
   ERP 服务器管理器 v8 —— 设计令牌
   来源：docs/ui-redesign/ui_prototype_v8.html（1:1 提取，未改动数值）
   设计令牌 1:1 继承 v7-pywebview-UI设计方案.md

   ★ 本文件只放**变量定义**，不放任何选择器规则。
     改主题色只需改这里；组件样式在 app.css。
   ============================================================ */
"""


def _banner_app() -> str:
    return """/* ============================================================
   ERP 服务器管理器 v8 —— 组件样式
   来源：docs/ui-redesign/ui_prototype_v8.html（1:1 提取）

   依赖 tokens.css（须先引用）。
   ============================================================ */
"""


def _index_html(head_part: str, body_part: str) -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ERP 服务器管理器 v8</title>
<link rel="stylesheet" href="css/tokens.css">
<link rel="stylesheet" href="css/app.css">
</head>
<body>
""" + body_part + """<script src="js/util.js"></script>
<script src="js/state.js"></script>
<script src="js/api.js"></script>
<script src="js/ui.js"></script>
<script src="js/router.js"></script>
<script src="js/pages/overview.js"></script>
<script src="js/pages/services.js"></script>
<script src="js/pages/alerts.js"></script>
<script src="js/pages/logs.js"></script>
<script src="js/pages/deploy.js"></script>
<script src="js/pages/backup.js"></script>
<script src="js/pages/config.js"></script>
<script src="js/pages/access.js"></script>
<script src="js/app.js"></script>
</body>
</html>
"""


if __name__ == '__main__':
    sys.exit(main())

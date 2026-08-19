"""L10 a11y 批量修复脚本。

重新扫描 frontend-vite/src 下所有 .vue 文件, 用 L10 的正则检测当前 a11y 问题,
对每个问题行应用修复:
    - <img> 缺 alt        -> 添加 alt="" (装饰性) 或描述性 alt
    - <button>/<a> 缺 aria-label -> 提取元素文本内容作为 aria-label
    - <input>/<select>/<textarea> 缺 aria-label -> 使用 placeholder/title/label 文本

约束:
    - 仅修改单行开标签 (L10 正则只匹配单行)
    - 保留原文件缩进与换行
    - 不修改 script/style 块中的内容
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC_DIR = PROJECT_ROOT / "frontend-vite" / "src"

# 与 L10 检测器保持一致的正则
_IMG_WITHOUT_ALT_RE = re.compile(r"<img(?![^>]*\balt\s*=)[^>]*>")
_INTERACTIVE_RE = re.compile(
    r"<(button|a|input|select|textarea)(?![^>]*\baria-label\s*=)[^>]*>"
)

# 提取开标签后的纯文本内容 (去标签)
_TAG_RE = re.compile(r"<[^>]+>")
# 提取属性值
_PLACEHOLDER_RE = re.compile(r"""placeholder\s*=\s*["']([^"']+)["']""")
_TITLE_RE = re.compile(r"""title\s*=\s*["']([^"']+)["']""")
_NAME_RE = re.compile(r"""name\s*=\s*["']([^"']+)["']""")
# 提取 :placeholder (动态绑定)
_DYN_PLACEHOLDER_RE = re.compile(r""":placeholder\s*=\s*["']([^"']+)["']""")

# Vue 模板中需要跳过的区块标记
_TEMPLATE_OPEN_RE = re.compile(r"<template\b")
_TEMPLATE_CLOSE_RE = re.compile(r"</template>")


def _strip_html(text: str) -> str:
    """去除 HTML/Vue 标签, 保留纯文本, 压缩空白."""
    text = _TAG_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_attr(raw: str, attr_re: re.Pattern[str]) -> str | None:
    """从开标签字符串中提取属性值."""
    m = attr_re.search(raw)
    if m:
        return m.group(1).strip()
    return None


def _find_close_tag_line(
    lines: list[str], start_idx: int, tag: str
) -> int:
    """从 start_idx 行开始查找闭合标签 </tag> 所在行索引."""
    close_re = re.compile(rf"</{tag}\s*>")
    self_close_re = re.compile(r"/>$")
    # 检查起始行是否自闭合
    if self_close_re.search(lines[start_idx]):
        return start_idx
    for idx in range(start_idx, min(start_idx + 20, len(lines))):
        if close_re.search(lines[idx]):
            return idx
    return start_idx


def _guess_button_aria_label(
    lines: list[str], idx: int, tag: str
) -> str:
    """提取 button/a 元素的文本内容作为 aria-label."""
    # 收集从当前行到闭合标签的所有文本
    end_idx = _find_close_tag_line(lines, idx, tag)
    chunk = "\n".join(lines[idx : end_idx + 1])
    # 去除开标签
    open_match = re.search(rf"<{tag}\b[^>]*>", chunk)
    if open_match:
        chunk = chunk[open_match.end() :]
    # 去除闭合标签
    chunk = re.sub(rf"</{tag}\s*>", "", chunk)
    text = _strip_html(chunk)
    # 处理 HTML 实体
    text = (
        text.replace("&times;", "关闭")
        .replace("&lsaquo;", "上一页")
        .replace("&rsaquo;", "下一页")
        .replace("&laquo;", "上一月")
        .replace("&raquo;", "下一月")
        .replace("&check;", "确认")
        .replace("✕", "删除")
        .replace("✓", "确认")
        .replace("−", "减")
        .replace("×", "关闭")
    )
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        return text[:40]
    return ""


def _guess_input_aria_label(
    line: str, tag: str, lines: list[str], idx: int
) -> str:
    """为 input/select/textarea 推断 aria-label."""
    # 1. placeholder
    ph = _extract_attr(line, _PLACEHOLDER_RE)
    if ph:
        return ph[:40]
    # 2. 动态 placeholder (取表达式末尾变量名)
    dph = _extract_attr(line, _DYN_PLACEHOLDER_RE)
    if dph:
        return dph[:40]
    # 3. title
    title = _extract_attr(line, _TITLE_RE)
    if title:
        return title[:40]
    # 4. 向上查找相邻 <label>文本</label>
    for back in range(idx - 1, max(idx - 5, -1), -1):
        prev = lines[back].strip()
        # 同行 <label>xxx</label><input ...>
        label_m = re.search(r"<label\b[^>]*>([^<]+)</label>", prev)
        if label_m:
            return label_m.group(1).strip()[:40]
        # 独立 <label>文本</label> 行
        label_m2 = re.search(r"<label\b[^>]*>\s*([^<]+?)\s*</label>", prev)
        if label_m2:
            return label_m2.group(1).strip()[:40]
    # 5. name 属性
    name = _extract_attr(line, _NAME_RE)
    if name:
        return name[:40]
    # 6. type 推断
    type_m = re.search(r"""type\s*=\s*["']([^"']+)["']""", line)
    if type_m:
        t = type_m.group(1)
        type_map = {
            "file": "上传文件",
            "checkbox": "勾选项",
            "radio": "选项",
            "number": "数值输入",
            "date": "日期选择",
            "password": "密码输入",
            "text": "文本输入",
            "email": "邮箱输入",
            "tel": "电话输入",
        }
        return type_map.get(t, f"{t}输入")
    return f"{tag}输入"


def _insert_attr_before_close(line: str, match: re.Match[str], attr: str) -> str:
    """在正则匹配的开标签 > 或 /> 前插入属性.

    Args:
        line: 当前行原文
        match: 正则匹配对象 (匹配整个开标签 <tag ...>)
        attr: 待插入的属性字符串 (如 'aria-label="xxx"')
    """
    # match.end() 指向开标签 > 之后的位置
    close_idx = match.end() - 1  # > 的位置
    if close_idx < 0 or line[close_idx] != ">":
        return line
    # 检查是否自闭合 />
    if line[close_idx - 1 : close_idx] == "/":
        insert_at = close_idx - 1
        if line[insert_at - 1 : insert_at] not in (" ", "\t"):
            return line[:insert_at] + " " + attr + " " + line[insert_at:]
        return line[:insert_at] + attr + " " + line[insert_at:]
    # 普通 >
    insert_at = close_idx
    if line[insert_at - 1 : insert_at] not in (" ", "\t"):
        return line[:insert_at] + " " + attr + line[insert_at:]
    return line[:insert_at] + attr + line[insert_at:]


def _is_in_template(lines: list[str], idx: int) -> bool:
    """判断该行是否在 <template> 块内 (而非 script/style)."""
    in_tpl = False
    for i in range(idx + 1):
        s = lines[i].strip()
        if _TEMPLATE_OPEN_RE.search(s) and not s.startswith("</"):
            in_tpl = True
        elif (re.search(r"<script\b", s) and not s.startswith("</")) or (re.search(r"<style\b", s) and not s.startswith("</")) or "</template>" in s:
            in_tpl = False
    return in_tpl


def fix_file(vue_file: Path) -> tuple[int, list[str]]:
    """修复单个 .vue 文件, 返回 (修复数, 详情列表)."""
    try:
        raw = vue_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0, []
    lines = raw.splitlines(keepends=False)
    fixes = 0
    details: list[str] = []

    for idx in range(len(lines)):
        if not _is_in_template(lines, idx):
            continue
        line = lines[idx]
        new_line = line

        # 1. img 缺 alt
        img_m = _IMG_WITHOUT_ALT_RE.search(new_line)
        if img_m:
            # 判断是否产品图片 (:src 含 image/product)
            if ":src" in line and ("image" in line or "product" in line):
                alt = 'alt="产品图片"'
            else:
                alt = 'alt=""'
            new_line = _insert_attr_before_close(new_line, img_m, alt)
            fixes += 1
            details.append(f"L{idx+1} img+alt")
            # 继续检查交互元素 (同行可能有)

        # 2. 交互元素缺 aria-label
        m = _INTERACTIVE_RE.search(new_line)
        if m:
            tag = m.group(1)
            if tag in ("button", "a"):
                label = _guess_button_aria_label(lines, idx, tag)
                if not label:
                    # 推断: title / class 关键词
                    title = _extract_attr(line, _TITLE_RE)
                    if title:
                        label = title[:40]
                    else:
                        label = "操作按钮" if tag == "button" else "链接"
            else:
                label = _guess_input_aria_label(line, tag, lines, idx)
            # 转义双引号
            label = label.replace('"', "'")
            attr = f'aria-label="{label}"'
            new_line = _insert_attr_before_close(new_line, m, attr)
            fixes += 1
            details.append(f"L{idx+1} {tag}+aria-label")

        if new_line != line:
            lines[idx] = new_line

    if fixes > 0:
        vue_file.write_text("\n".join(lines) + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
    return fixes, details


def main() -> None:
    """扫描所有 .vue 文件并修复 a11y 问题."""
    total_fixes = 0
    file_count = 0
    all_details: list[tuple[str, int, list[str]]] = []

    for vue_file in FRONTEND_SRC_DIR.rglob("*.vue"):
        if "node_modules" in vue_file.parts:
            continue
        fixes, details = fix_file(vue_file)
        if fixes > 0:
            rel = vue_file.relative_to(PROJECT_ROOT).as_posix()
            all_details.append((rel, fixes, details))
            total_fixes += fixes
            file_count += 1

    print(f"修复文件数: {file_count}")
    print(f"修复问题数: {total_fixes}")
    print("---")
    for rel, fixes, details in all_details:
        print(f"{rel}: {fixes} 处")
        for d in details:
            print(f"  {d}")


if __name__ == "__main__":
    main()

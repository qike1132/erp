"""批量迁移 fa- CSS class 图标到 FontAwesomeIcon 组件(静态模式,修复引号匹配)"""
import pathlib
import re

ROOT = pathlib.Path(r"D:\erp_system\frontend-vite\src")

# 静态: <i class="fas fa-xxx" ...> → <FontAwesomeIcon icon="xxx" ...>
# 注意 class 值结尾的 " 必须包含在匹配中
STATIC_RE = re.compile(
    r'<i\s+class="fas\s+fa-([a-z0-9-]+)"((?:\s+[^>]*?)?)\s*/?>'
)
def replace_static(m):
    icon, rest = m.group(1), m.group(2)
    return f'<FontAwesomeIcon icon="{icon}"{rest} />'

TARGETS = [
    "views/material/components/OrderPreviewDialog.vue",
    "views/pattern-room/components/DialogImageUpload.vue",
    "views/pattern-room/components/DialogMakerSelect.vue",
    "views/pattern-room/components/DialogRoleEditor.vue",
    "views/pattern-room/components/PartFormDialog.vue",
    "views/pattern-room/components/PartsVersionRowV2.vue",
    "views/pattern-room/components/PartsVersionTableV2.vue",
    "views/pattern-room/components/PatternMakerSelect.vue",
    "views/pattern-room/components/PatternRoomSplitBody.vue",
    "views/pattern-room/components/PrintDialog.vue",
    "views/pattern-room/components/ProjectCardItem.vue",
    "views/pattern-room/components/ProjectDetailPanel.vue",
    "views/pattern-room/components/ProjectImageUpload.vue",
    "views/pattern-room/components/RoleListEditor.vue",
    "views/pattern-room/components/RoleTabs.vue",
]

for rel in TARGETS:
    p = ROOT / rel
    text = p.read_text(encoding="utf-8")
    orig = text
    text, n = STATIC_RE.subn(replace_static, text)
    if text != orig:
        p.write_text(text, encoding="utf-8")
        print(f"{rel}: 替换 {n} 处")

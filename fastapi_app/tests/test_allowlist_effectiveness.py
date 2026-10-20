"""F3-3：密钥扫描 allowlist 不得只增不减——每条非通配符豁免必须仍对应真实命中。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def test_every_literal_allowlist_entry_is_still_needed():
    from scripts import scan_secrets

    patterns = scan_secrets.load_allowlist(ROOT)
    tracked = scan_secrets._tracked_files(ROOT)
    literal = [p for p in patterns if not any(ch in p for ch in '*?[')]

    assert literal, 'allowlist 不应为空'
    for pattern in literal:
        matched = [f for f in tracked if scan_secrets._is_allowed(f, [pattern])]
        assert matched, f'豁免已无匹配文件: {pattern}'
        findings = scan_secrets.scan_tracked(ROOT, allow_patterns=[], files=matched)
        assert findings, f'豁免已无命中（冗余，应删除）: {pattern}'

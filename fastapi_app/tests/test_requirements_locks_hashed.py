"""依赖锁必须带 sha256，安装点必须强制校验。

背景（2026-11-02 C4）：锁文件此前只钉版本不钉哈希，安装也不加 --require-hashes。
版本锁定能防「升到不兼容的新版」，但防不了同名同版本的包被镜像替换——
供应链完整性要求二者同时存在。

本测试锁住两条不变量，防止后续刷新锁或改安装命令时静默退化：
1. 7 个 tier 的 .lock 都带 sha256 哈希，且每个版本钉都至少有一条哈希；
2. CI 与离线包构建的 pip 安装命令都带 --require-hashes。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / 'requirements'
TIERS = ('base', 'dev', 'test', 'ocr', 's3', 'desktop', 'migration')

_PIN_RE = re.compile(r'^[A-Za-z0-9_.\-\[\]]+==[0-9]')


def _lock_text(tier: str) -> str:
    return (REQUIREMENTS / f'{tier}.lock').read_text(encoding='utf-8')


def test_every_tier_lock_has_hashes() -> None:
    missing = [t for t in TIERS if '--hash=sha256:' not in _lock_text(t)]
    assert not missing, f'以下 tier 的锁没有哈希: {missing}'


def test_every_pin_has_at_least_one_hash() -> None:
    for tier in TIERS:
        text = _lock_text(tier)
        pins = sum(1 for line in text.splitlines() if _PIN_RE.match(line))
        hashes = text.count('--hash=sha256:')
        assert pins > 0, f'{tier}.lock 没有解析到任何版本钉'
        assert hashes >= pins, (
            f'{tier}.lock: {pins} 个版本钉只有 {hashes} 条哈希，'
            '有包缺少完整性校验'
        )


def test_install_sites_require_hashes() -> None:
    """任何 `pip install -r requirements/...lock` 都必须带 --require-hashes。"""
    sources = [
        (ROOT / '.github' / 'workflows' / 'ci-cd.yml'),
        (ROOT / 'deploy' / 'build_package.ps1'),
    ]
    offenders: list[str] = []
    for path in sources:
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue  # 注释里会提到 pip install / requirements，不是可执行命令
            if 'pip install' not in line or 'requirements' not in line:
                continue
            if '--require-hashes' not in line:
                offenders.append(f'{path.name}:{lineno}')
    assert not offenders, f'安装命令缺少 --require-hashes: {offenders}'


def test_refresh_workflow_keeps_hashes() -> None:
    text = (ROOT / '.github' / 'workflows' / 'refresh-requirements-lock.yml').read_text(
        encoding='utf-8',
    )
    assert '--generate-hashes' in text, '刷新锁的工作流会用无哈希结果覆盖已入库的锁'

"""架构门禁测试：正向（现有代码全过）+ 负向（违规代码必须被抓到）。"""
from __future__ import annotations

from pathlib import Path

from server_manager_v8._guard import check_package

PKG = 'server_manager_v8'


def _make_pkg(tmp_path: Path, files: dict[str, str]) -> Path:
    """在 tmp 下构造 server_manager_v8/ 包结构并写入文件。"""
    root = tmp_path / PKG
    for rel, src in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding='utf-8')
    return root


class TestPositive:
    def test_real_package_clean(self) -> None:
        """现有包代码零违规（门禁红线自身必须先守得住）。"""
        violations = check_package()
        assert violations == [], '\n'.join(str(v) for v in violations)


class TestNegative:
    def _violations(self, tmp_path: Path, files: dict[str, str]) -> list[str]:
        return [str(v) for v in check_package(_make_pkg(tmp_path, files))]

    def test_r1_domain_cannot_import_adapters(self, tmp_path: Path) -> None:
        msgs = self._violations(tmp_path, {
            'domain/bad.py': 'from ..adapters import process_win\n',
        })
        assert any('[R1]' in m and 'adapters' in m for m in msgs)

    def test_r1_application_cannot_import_adapters(self, tmp_path: Path) -> None:
        msgs = self._violations(tmp_path, {
            'application/bad.py': 'from server_manager_v8.adapters import x\n',
        })
        assert any('[R1]' in m for m in msgs)

    def test_r1_presentation_cannot_skip_to_domain(self, tmp_path: Path) -> None:
        msgs = self._violations(tmp_path, {
            'presentation/bad.py': 'from server_manager_v8.domain.models import OpResult\n',
        })
        assert any('[R1]' in m and 'domain' in m for m in msgs)

    def test_r1_same_layer_and_allowed_deps_ok(self, tmp_path: Path) -> None:
        """合法依赖不误报：application→domain、adapters→domain、层内互引。"""
        msgs = self._violations(tmp_path, {
            'domain/a.py': 'from .models import OpResult\n',
            'application/b.py': 'from server_manager_v8.domain.models import OpResult\n',
            'adapters/c.py': 'from ..domain.models import OpResult\n',
        })
        assert not any('[R1]' in m for m in msgs)

    def test_r2_domain_bans_subprocess(self, tmp_path: Path) -> None:
        msgs = self._violations(tmp_path, {
            'domain/bad.py': 'import subprocess\n',
        })
        assert any('[R2]' in m and 'subprocess' in m for m in msgs)

    def test_r2_domain_bans_open_call(self, tmp_path: Path) -> None:
        msgs = self._violations(tmp_path, {
            'domain/bad.py': 'def f():\n    return open("x")\n',
        })
        assert any('[R2]' in m and 'open' in m for m in msgs)

    def test_r2_domain_allows_stdlib_pure(self, tmp_path: Path) -> None:
        msgs = self._violations(tmp_path, {
            'domain/ok.py': 'import hashlib\nimport json\nfrom dataclasses import dataclass\n',
        })
        assert not any('[R2]' in m for m in msgs)

    def test_r3_empty_except_pass(self, tmp_path: Path) -> None:
        msgs = self._violations(tmp_path, {
            'adapters/bad.py': 'try:\n    f()\nexcept Exception:\n    pass\n',
        })
        assert any('[R3]' in m and 'pass' in m for m in msgs)

    def test_r3_contextlib_suppress(self, tmp_path: Path) -> None:
        msgs = self._violations(tmp_path, {
            'adapters/bad.py': 'import contextlib\n'
                               'with contextlib.suppress(Exception):\n    f()\n',
        })
        assert any('[R3]' in m and 'suppress' in m for m in msgs)

    def test_r4_oversized_file(self, tmp_path: Path) -> None:
        body = '\n'.join(f'x{i} = {i}' for i in range(801))
        msgs = self._violations(tmp_path, {'adapters/big.py': body + '\n'})
        assert any('[R4]' in m and '800' in m for m in msgs)

    def test_r4_oversized_function(self, tmp_path: Path) -> None:
        lines = ['def big():'] + ['    X = 1'] * 85 + ['']
        msgs = self._violations(tmp_path, {'adapters/big_fn.py': '\n'.join(lines)})
        assert any('[R4]' in m and 'big' in m for m in msgs)

    def test_r4_god_class(self, tmp_path: Path) -> None:
        """21 个方法即违规（v6 上帝类 96 个方法的教训）。"""
        lines = ['class God:'] + [f'    def m{i}(self):\n        return {i}' for i in range(21)]
        msgs = self._violations(tmp_path, {'adapters/god.py': '\n'.join(lines) + '\n'})
        assert any('[R4]' in m and 'God' in m for m in msgs)

    def test_r5_mutable_module_global(self, tmp_path: Path) -> None:
        msgs = self._violations(tmp_path, {
            'adapters/bad.py': 'cache = {}\n',
        })
        assert any('[R5]' in m and 'cache' in m for m in msgs)

    def test_r5_constants_and_dunder_allowed(self, tmp_path: Path) -> None:
        msgs = self._violations(tmp_path, {
            'adapters/ok.py': 'MAX = 3\n_PRIVATE = 4\n__all__ = ["MAX"]\n',
        })
        assert not any('[R5]' in m for m in msgs)

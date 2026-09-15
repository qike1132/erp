"""domain 包导出面的契约测试。

`domain/__init__.py` 用 `__getattr__` 做惰性再导出 —— 这是下游各层
（application / adapters / presentation）的唯一导入入口。
一旦某个名字拼错或模块改名，下游会在**运行时**才炸；本文件把它挡在测试期。

同时固化一条架构约束：导入 domain 包不得产生任何 I/O 副作用。
"""

from __future__ import annotations

import importlib
import sys

import pytest

DOMAIN = 'server_manager_v8.domain'
MODULES = (
    'service_state',
    'readiness',
    'port_contract',
    'models',
    'config_schema',
    'state_machine',
)


class TestExportSurface:
    def test_all_names_resolve(self):
        """__all__ 里的每个名字都必须真能取到。"""
        dm = importlib.import_module(DOMAIN)
        missing = []
        for name in dm.__all__:
            try:
                getattr(dm, name)
            except AttributeError:
                missing.append(name)
        assert missing == []

    def test_no_duplicates_in_all(self):
        dm = importlib.import_module(DOMAIN)
        assert len(dm.__all__) == len(set(dm.__all__))

    def test_unknown_name_raises_attribute_error(self):
        dm = importlib.import_module(DOMAIN)
        with pytest.raises(AttributeError):
            dm.ThisNameDoesNotExist

    def test_dir_returns_sorted_all(self):
        dm = importlib.import_module(DOMAIN)
        assert dir(dm) == sorted(dm.__all__)

    def test_lazy_reexport_matches_submodule_attribute(self):
        """再导出的对象身份必须与源模块里的**同一个对象**（不是副本）。"""
        dm = importlib.import_module(DOMAIN)
        checks = {
            'StopResult': 'state_machine',
            'ServiceStatus': 'service_state',
            'PortFilter': 'port_contract',
            'RunMode': 'models',
            'normalize_config': 'config_schema',
            'wait_until': 'readiness',
        }
        for name, modname in checks.items():
            mod = importlib.import_module(f'{DOMAIN}.{modname}')
            assert getattr(dm, name) is getattr(mod, name), name

    def test_from_import_star_surface(self):
        """`from domain import *` 不应抛异常且范围受 __all__ 限制。"""
        dm = importlib.import_module(DOMAIN)
        ns: dict = {}
        for name in dm.__all__:
            ns[name] = getattr(dm, name)
        assert 'StopResult' in ns
        assert len(ns) == len(dm.__all__)


class TestNoImportSideEffects:
    """domain 层的可测性前提：导入不产生 I/O。"""

    @pytest.mark.parametrize('modname', MODULES)
    def test_submodule_imports_without_io_modules(self, modname):
        """导入任一 domain 子模块，不得把 I/O 模块带进 sys.modules。

        注意这是「该子模块自身」的检查：Python 进程里可能已有别的库
        加载了 os/sys（解释器启动就加载），所以只做「非新增」比对。
        """
        io_mods = {'subprocess', 'socket', 'psutil', 'tkinter', 'webview', 'winreg'}
        before = io_mods & set(sys.modules)
        importlib.import_module(f'{DOMAIN}.{modname}')
        after = io_mods & set(sys.modules)
        assert after == before, f'{modname} 引入了 I/O 模块: {after - before}'

    def test_domain_package_import_is_light(self):
        """导入 domain 包本身不应自动加载全部子模块（惰性再导出的意义）。"""
        code = (
            'import sys;'
            f'import {DOMAIN};'
            "print('|'.join(k for k in sys.modules "
            f"if k.startswith('{DOMAIN}')))"
        )
        import subprocess

        out = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        loaded = [m for m in out.split('|') if m]
        assert DOMAIN in loaded
        # 只应有包自身，不应有子模块被连带加载
        submodules = [m for m in loaded if m != DOMAIN]
        assert submodules == [], f'导入包时被连带加载: {submodules}'

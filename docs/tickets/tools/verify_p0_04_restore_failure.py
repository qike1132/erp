"""P0-04 验收脚本：证明「恢复失败必须返回失败」

⚠️ 本脚本 **完全不接触数据库**：
   subprocess.run / get_db_config / backup_postgresql 全部被替换为打桩实现，
   因此不会执行任何 psql、更不会 DROP DATABASE。

覆盖 4 个场景：
  A  恢复前备份失败      -> 必须中止，且不得执行 DROP DATABASE
  B  dump 是坏 SQL       -> psql 退出码 3       -> 必须返回 False
  C  dump 是空的         -> 退出码 0 但表数 0   -> 必须返回 False
  D  正常 dump           -> 退出码 0 且表数 >0  -> 必须返回 True

运行：
  C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe \
    docs/tickets/tools/verify_p0_04_restore_failure.py
"""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TARGET = REPO / 'scripts' / 'database' / 'db_manager.py'


def load_module():
    spec = importlib.util.spec_from_file_location('_p0_04_db_manager', TARGET)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeRun:
    """伪装 subprocess.run：按命令内容分流，绝不真正执行。"""

    def __init__(self, restore_returncode: int, restore_stderr: bytes, table_count: int):
        self.restore_returncode = restore_returncode
        self.restore_stderr = restore_stderr
        self.table_count = table_count
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        joined = ' '.join(str(c) for c in cmd)

        if '-tAc' in cmd:                       # 恢复后表数校验
            return subprocess.CompletedProcess(
                cmd, 0, stdout=f'{self.table_count}\n'.encode(), stderr=b''
            )
        if 'pg_terminate_backend' in joined or 'DROP DATABASE' in joined \
                or 'CREATE DATABASE' in joined:
            return subprocess.CompletedProcess(cmd, 0, stdout=b'', stderr=b'')

        # 真正的恢复调用
        return subprocess.CompletedProcess(
            cmd, self.restore_returncode, stdout=b'', stderr=self.restore_stderr
        )

    @property
    def dropped_database(self) -> bool:
        return any('DROP DATABASE' in ' '.join(c) for c in self.calls)


def make_manager(mod, *, backup_ok: bool, fake_run: FakeRun):
    dm = mod.DatabaseManager()
    dm.log = lambda msg, level='INFO': None          # 不写真实日志文件
    dm.get_db_config = lambda: {
        'host': 'stub-host', 'port': '5432',
        'user': 'stub-user', 'password': 'stub-pw',
        'database': 'stub-db',
    }
    dm.backup_postgresql = lambda *a, **k: (
        (True, 'stub backup ok', None) if backup_ok else (False, 'pg_dump 失败: 模拟', None)
    )
    dm._fake_run = fake_run
    return dm


def run_case(mod, name, *, backup_ok, returncode, stderr, table_count, expect_ok):
    fake = FakeRun(returncode, stderr, table_count)
    dm = make_manager(mod, backup_ok=backup_ok, fake_run=fake)

    # db_manager 顶层是 `import subprocess`，因此替换的是同一个模块对象的属性
    original = subprocess.run
    subprocess.run = fake
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.sql', delete=False) as f:
            f.write('DUMMY')
            dump = Path(f.name)
        try:
            ok, msg = dm.restore_postgresql(dump)
        finally:
            dump.unlink(missing_ok=True)
    finally:
        subprocess.run = original

    status = 'PASS' if ok is expect_ok else 'FAIL'
    print(f'[{status}] {name}')
    print(f'        返回 ok={ok}  msg={msg}')
    print(f'        是否执行过 DROP DATABASE: {fake.dropped_database}')
    return status == 'PASS'


def main() -> int:
    mod = load_module()
    print(f'目标模块: {TARGET}')
    print('=' * 72)

    results = []
    results.append(run_case(
        mod, 'A 恢复前备份失败 → 必须中止且不 DROP 库',
        backup_ok=False, returncode=0, stderr=b'', table_count=0,
        expect_ok=False,
    ))
    results.append(run_case(
        mod, 'B 坏 SQL dump（psql 退出码 3）→ 必须 False',
        backup_ok=True, returncode=3,
        stderr=b'psql:<stdin>:1: ERROR:  syntax error at or near "THIS"',
        table_count=0, expect_ok=False,
    ))
    results.append(run_case(
        mod, 'C 空 dump（退出码 0 但零表）→ 必须 False',
        backup_ok=True, returncode=0, stderr=b'', table_count=0,
        expect_ok=False,
    ))
    results.append(run_case(
        mod, 'D 正常 dump（退出码 0 且 42 张表）→ 必须 True',
        backup_ok=True, returncode=0, stderr=b'', table_count=42,
        expect_ok=True,
    ))

    print('=' * 72)
    passed = sum(1 for r in results if r)
    print(f'结果: {passed}/{len(results)} 通过')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())

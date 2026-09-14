"""批次 A 复核中发现的 2 个「作用域内名字未绑定」缺陷 —— 修复后回归守卫

发现 1  fastapi_app/api/v1/endpoints/backup/export.py
        F823 `BackupChunkResponse` referenced before assignment
        → export_backup_chunk 内有一处冗余的局部 import，使该名字变成函数局部变量，
          导致函数前半段（缓存快路径）读取它时抛 UnboundLocalError。
发现 2  fastapi_app/services/backup/orchestration/recovery_test_service.py
        F821 Undefined name `os`
        → _psql_import 的局部 import 里没有 os，但函数体内用了 os.environ.copy()。

两者与已修的 P0-01（health.py 的 `_os`）属同一类缺陷。

本脚本断言「修复后不再复现」：
  · 发现 1：函数局部变量表中不应再有 BackupChunkResponse
  · 发现 2：调用 _psql_import 不应再抛 NameError

运行：
  C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe \
    docs/tickets/tools/verify_batch_a_new_findings.py
"""
import asyncio
import gzip
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


def check_finding_1() -> bool:
    from fastapi_app.api.v1.endpoints.backup import export as export_mod

    func = export_mod.export_backup_chunk
    code = func.__code__
    is_local = 'BackupChunkResponse' in code.co_varnames

    print('发现 1 · export.py 分片下载快路径')
    print(f'  export_backup_chunk 局部变量表含 BackupChunkResponse: {is_local}')
    if is_local:
        print('  FAIL ── 仍是局部名，快路径的 return 会在运行期抛 UnboundLocalError')
        return False

    # 名字解析到模块级导入即为正确
    has_module_level = hasattr(export_mod, 'BackupChunkResponse')
    print(f'  模块级导入可用: {has_module_level}')
    print(f'  结论: {"PASS —— 名字只在模块级绑定，快路径可正常返回" if has_module_level else "FAIL"}')
    return has_module_level


async def check_finding_2() -> bool:
    from fastapi_app.services.backup.orchestration.recovery_test_service import recovery_test_service

    func = recovery_test_service._psql_import
    print()
    print('发现 2 · recovery_test_service.py 的 psql 演练导入')

    test_env = {
        'test_db_host': '127.0.0.1',
        'test_db_port': 1,             # 必然连不上的端口，psql 立即失败
        'test_db_user': 'nobody',
        'test_db_name': 'nodb',
        'test_db_password': 'x',
    }
    with tempfile.TemporaryDirectory() as td:
        gz_path = Path(td) / 'dump.sql.gz'
        with gzip.open(gz_path, 'wb') as f:
            f.write(b'SELECT 1;\n')
        try:
            result = await func(test_env, gz_path)
            print(f'  未抛 NameError，返回: {result}')
        except NameError as e:
            print(f'  FAIL ── 仍抛 NameError: {e}')
            return False
        except Exception as e:  # noqa: BLE001
            # 连不上库 / 找不到 psql 都属预期，关键是已越过 os.environ.copy()
            print(f'  已越过 os.environ.copy()，随后按预期失败: {type(e).__name__}: {str(e)[:120]}')

    print('  结论: PASS —— os 已在作用域内绑定，不再 NameError')
    return True


def main() -> int:
    r1 = check_finding_1()
    r2 = asyncio.run(check_finding_2())
    print()
    print('=' * 68)
    print(f'回归结果: 发现1={"通过" if r1 else "失败"}  发现2={"通过" if r2 else "失败"}')
    return 0 if (r1 and r2) else 1


if __name__ == '__main__':
    raise SystemExit(main())

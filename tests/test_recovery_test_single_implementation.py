"""恢复演练（recovery drill）只能有一份实现（审计 Z05-R4，主报告 F1 族：双实现）。

`BackupHealthCheckService` 里曾平行存在一个 `perform_recovery_test`，只验「ZIP 能否
解压」就报 success —— 语义远弱于 `DisasterRecoveryTestService` 的真演练（实际还原），
而它的 docstring 自称「唯一调用方 cleanup/service.py」，grep 证实零生产调用方。
两条入口并存时，维护者会以为演练有两条路径，弱实现还会把「解得开」当成「恢复得了」。

本测试防复发：
  1. 全后端 `perform_recovery_test` 的定义必须恰好一处，且在 orchestration 侧；
  2. 健康检查服务不再带这个属性；
  3. ARQ 定时任务的调用点仍指向 orchestration 那份（防止「删了活的、留下死的」）。
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / 'fastapi_app'
LIVE_MODULE = 'fastapi_app/services/backup/orchestration/recovery_test_service.py'
METHOD = 'perform_recovery_test'


def _definitions() -> list[str]:
    """返回后端里定义 `perform_recovery_test` 的文件（仓库相对路径）。"""
    hits: list[str] = []
    for path in sorted(BACKEND.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == METHOD
               for n in ast.walk(tree)):
            hits.append(path.relative_to(ROOT).as_posix())
    return hits


def test_recovery_drill_has_exactly_one_implementation():
    hits = _definitions()
    assert hits == [LIVE_MODULE], (
        f'{METHOD} 应只在 {LIVE_MODULE} 有一份实现，实际: {hits} —— '
        '平行副本的「测试通过」语义不同，删掉弱的那份，别复制它'
    )


def test_health_check_service_no_longer_claims_a_recovery_test():
    """健康检查侧不得再挂同名方法：它的存在本身就是「演练有两条入口」的误导源。"""
    from fastapi_app.services.backup.verify.health_check_service import BackupHealthCheckService

    assert not hasattr(BackupHealthCheckService(), METHOD)


def test_scheduled_drill_still_targets_the_live_service():
    """ARQ 定时演练必须 import orchestration 那份 —— 收口不能把活实现删掉。"""
    src = (BACKEND / 'tasks/backup_tasks.py').read_text(encoding='utf-8')
    call = src[src.index(f'await recovery_test_service.{METHOD}()') - 400:
               src.index(f'await recovery_test_service.{METHOD}()')]
    assert 'backup.orchestration.recovery_test_service' in call, (
        f'定时演练调用点不再指向活实现:\n{call}'
    )

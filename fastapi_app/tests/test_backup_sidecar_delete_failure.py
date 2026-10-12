"""P1-residual 备份残留小修回归（F-05 / F-07 / F-09）。

对应 docs/p0-review-2026-10-01.md（t11 评审 t8 备份/还原）留下的三条 low 残留：

F-05  fastapi_app/services/backup/records.py::_delete_backup_sidecars 删除伴随文件
      （.meta / .record）失败时只记 logger.warning，调用方（records/_execute_cleanup）
      的返回值里看不到 —— 伴随文件残留成了「静默部分失败」。修复后：ERROR 级日志，
      并在调用方传入 errors 聚合列表时把失败项并入清理结果；返回值仍为成功删除的
      伴随文件名列表（不传聚合器的既有调用方语义不变）。
F-07  fastapi_app/services/backup/orchestration/policy_service.py::_should_keep_backup
      的 time 策略兜底默认硬编码 30，改为引用 _constants.RETENTION_DAYS_DEFAULT，
      让「env 真源 BACKUP_RETENTION_DAYS 的默认值」只有一处定义。
F-09  config/nssm-services.json 自述字段声称「随加密备份包分发」，而真实打包行为是
      明文包也会带上它（它不在敏感闸门里）。选择改自述而非改行为：该文件不含凭据、
      灾备还原路径需要它，从明文包排除只会削弱 DR 且无安全收益。
"""

from __future__ import annotations

import importlib
import inspect
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi_app.services.backup import _constants, records, should_exclude_file
from fastapi_app.services.backup.orchestration.policy_service import BackupPolicyService

# 注意：不能写 from ...orchestration import policy_service —— 该子包 __init__ 用
# star-import 把模块级单例 policy_service（BackupPolicyService 实例）覆盖到了包属性上，
# 那样拿到的不是模块。这里按类的定义模块精确取回模块对象。
policy_service_module = importlib.import_module(BackupPolicyService.__module__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKUP_NAME = 'erp_backup_20261001_020000.zip'
NSSM_ARCHIVE_NAME = 'config/nssm-services.json'


def _make_expired_backup(backup_dir: Path, name: str = BACKUP_NAME, age_days: int = 20) -> Path:
    """建一个「已过期」备份：主文件 + .meta（带 created_at，保留期判定正是读它）+ .record。"""
    path = backup_dir / name
    path.write_bytes(b'fake-zip-body')
    created_at = datetime.now() - timedelta(days=age_days)
    (backup_dir / (name + '.meta')).write_text(
        json.dumps({'created_at': created_at.strftime('%Y-%m-%d %H:%M:%S')}),
        encoding='utf-8',
    )
    (backup_dir / (name + '.record')).write_text('{}', encoding='utf-8')
    return path


def _fail_unlink_for(monkeypatch, suffix: str) -> None:
    """让 pathlib 的 unlink 对指定伴随后缀抛 OSError（模拟伴随文件被占用）。"""
    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name.endswith(suffix):
            raise OSError(f'模拟占用: {self.name}')
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', flaky_unlink)


def test_sidecar_errors_sink_is_optional_and_return_shape_unchanged(tmp_path, monkeypatch):
    """F-05：errors 聚合器为可选参数；不传时返回值仍是「成功删除名列表」（旧语义）。"""
    path = _make_expired_backup(tmp_path)
    _fail_unlink_for(monkeypatch, '.meta')

    sink: list[str] = []
    removed = records._delete_backup_sidecars(path, sink)
    assert removed == [BACKUP_NAME + '.record'], removed
    assert len(sink) == 1, sink
    assert BACKUP_NAME + '.meta' in sink[0]
    assert '模拟占用' in sink[0]

    # 不传聚合器：不抛异常，且返回类型/语义与旧版一致
    assert records._delete_backup_sidecars(path) == []


def test_time_strategy_fallback_comes_from_constants_single_source(monkeypatch):
    """F-07：time 策略兜底天数取自 _constants.RETENTION_DAYS_DEFAULT，而非字面量 30。"""
    service = BackupPolicyService.__new__(BackupPolicyService)  # 绕过 __init__（它读 .env 策略文件）
    assert policy_service_module.RETENTION_DAYS_DEFAULT == _constants.RETENTION_DAYS_DEFAULT

    def record(age_days: int) -> SimpleNamespace:
        return SimpleNamespace(
            trigger_type='auto',
            status='success',
            created_at=datetime.now() - timedelta(days=age_days),
        )

    default_days = _constants.RETENTION_DAYS_DEFAULT
    assert service._should_keep_backup(record(default_days - 1), 'time', {}, False, False) is True
    assert service._should_keep_backup(record(default_days + 1), 'time', {}, False, False) is False

    # 兜底不再写死：常量一变，判定边界跟着变（证明取值真的来自常量而非字面量）
    monkeypatch.setattr(policy_service_module, 'RETENTION_DAYS_DEFAULT', 3)
    assert service._should_keep_backup(record(2), 'time', {}, False, False) is True
    assert service._should_keep_backup(record(4), 'time', {}, False, False) is False

    # retention 显式给键时仍以 retention 为准（兜底只在缺键时生效）
    assert service._should_keep_backup(record(4), 'time', {'retention_days': 10}, False, False) is True
    assert service._should_keep_backup(record(11), 'time', {'retention_days': 10}, False, False) is False

    # 源码级守卫：兜底必须引用常量，禁止退回字面量 30
    source_lines = inspect.getsource(service._should_keep_backup).splitlines()
    code = ' '.join(
        line.strip() for line in source_lines if line.strip() and not line.strip().startswith('#')
    )
    assert "retention.get('retention_days', RETENTION_DAYS_DEFAULT)" in code
    assert "retention.get('retention_days', 30)" not in code


def test_nssm_services_self_description_matches_packaging_behaviour():
    """F-09：自述与真实打包行为一致（明文包与加密包都带 config/nssm-services.json）。"""
    nssm_path = PROJECT_ROOT / 'config' / 'nssm-services.json'
    payload = json.loads(nssm_path.read_text(encoding='utf-8'))
    assert payload['schema'] == 'erp-nssm-services/1'

    description = payload['description']
    assert '随加密备份包分发' not in description, '旧自述（仅加密包）残留，与打包行为不符'
    assert '明文包' in description and '加密包' in description, description

    archives = [archive for _source, archive in _constants.config_files_to_package()]
    assert NSSM_ARCHIVE_NAME in archives, archives

    # 真正的闸门：明文备份（include_sensitive=False）并不排除它 —— 与自述一致
    assert should_exclude_file(nssm_path, NSSM_ARCHIVE_NAME, False) is False

    raw = nssm_path.read_text(encoding='utf-8').lower()
    for keyword in ('password', 'secret', 'token'):
        assert keyword not in raw, keyword + ' 不应出现在灾备服务定义里'

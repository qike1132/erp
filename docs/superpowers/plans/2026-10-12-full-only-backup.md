# 备份只保留全量 + 7 天保留 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/backup` 备份模型收敛为「单一全量 + 每天一次 + 超 7 天自动删」，并彻底移除增量备份的全部代码与生产残留。

**Architecture:** 保留现有清理基础设施（ARQ `backup_cleanup_task` → `cleanup_service.smart_cleanup()`，由 `backup_schedule` 的 `cleanup` 行 `0 4 * * *` 驱动），把 `smart_cleanup` 重写为单规则（全量文件年龄 > `BACKUP_RETENTION_DAYS` 即删，至少留最新 1 个）；其余为机械删除（后端服务/任务/调度/端点、前端入口、配置、测试）+ 一条数据迁移 + 一次生产数据清理。

**Tech Stack:** FastAPI · SQLAlchemy(async) · ARQ · Alembic · Vue 3 + TS · pytest · vitest

**Spec:** `docs/superpowers/specs/2026-10-12-full-only-backup-design.md`

## Global Constraints

- **生产即运维主机**（AGENTS.md §0）：改动小步、可回滚；运行期操作见 §6.1。
- **不改已应用迁移**（036/056/057）；迁移**不得**对生产库 `alembic revision --autogenerate`；保持**单一 head**。
- **测试必须提权跑**（根 `.env` ACL）：`powershell -File logs/_run_pytest_elevated.ps1`；全量 pytest **独占单实例**。
- **前端 `vite.config.js` 优先于 `.ts`**，改完先 `vue-tsc -b`（本计划不改 vite 配置）。
- **临时文件任务结束必须清理**（`logs/` 下自建脚本/输出）。
- **只提交自己的路径**：本仓常有并发会话写工作区，`git status` 见陌生改动先问、别 stash。
- **保留策略唯一真源**：`_constants.retention_days()`（env `BACKUP_RETENTION_DAYS`，默认改为 **7**）。
- **保留的共享 helper（勿删）**：`normalize_backup_ts`（注：已于 2026-10-23 P2-26 删除，生产零调用）、`_delete_backup_sidecars`、`quote_table`、`ensure_backup_dir`。

## Review Focus

以下是 spec 隐含、但任何任务测试都不会自然覆盖、最容易被人踩到的地方——每条都要有测试钉住：

1. **删除全部备份**：若目录里所有全量都超 7 天（长时间停机后），清理必须**至少留最新 1 个**，不能清空。
2. **正在写入的备份**：备份任务写大 zip 需数十秒，清理撞上未写完的文件不得误判删除（120 秒宽限）。
3. **增量文件残留**：目录里若仍有 `erp_incremental_*`，新清理**不扫、不动**（既不删也不当全量）。
4. **伴生文件**：删主文件必须同时删 `.meta` / `.record`（含 `.zip.enc.meta`），否则残留被当成一份备份。
5. **`backup_settings` 死列**：`retention_days/max_count` 无消费、UI 不显示——本次**不动**，但不得因删除而破坏 `/backup/settings` 接口返回。

---

### Task 1: 保留天数默认值改为 7

**Files:**
- Modify: `fastapi_app/services/backup/_constants.py:190`（`RETENTION_DAYS_DEFAULT = 30` → `7`）
- Test: `fastapi_app/tests/test_backup_retention_policy.py:74-81`

**Interfaces:**
- Produces: `retention_days()` 缺省返回 `7`（供 Task 3 的清理服务消费）。

- [ ] **Step 1: 改测试断言（先红）**

`fastapi_app/tests/test_backup_retention_policy.py` 的 `test_retention_defaults_match_documented_values` 改为：

```python
def test_retention_defaults_match_documented_values(monkeypatch):
    """缺省保留天数 7（2026-10-12 起全量-only 策略；原为 30）。"""
    monkeypatch.delenv(RETENTION_DAYS_ENV, raising=False)
    assert RETENTION_DAYS_DEFAULT == 7
    assert retention_days() == 7
```

（同时删去该测试里对 `RETENTION_COUNT_DEFAULT / retention_count` 的断言——份数上限在 Task 4 移除。本步先只改天数断言，保留 count 断言到 Task 4 再删。）

- [ ] **Step 2: 跑测试确认红**

Run: `powershell -File logs/_run_pytest_elevated.ps1`（args 文件 `logs/_pytest_args.txt` 写 `fastapi_app/tests/test_backup_retention_policy.py::test_retention_defaults_match_documented_values -q`）
Expected: FAIL（`assert 30 == 7`）

- [ ] **Step 3: 改代码**

`fastapi_app/services/backup/_constants.py`：

```python
RETENTION_DAYS_DEFAULT = 7
```

同时把该常量上方注释里的「默认 30」改为「默认 7（2026-10-12 全量-only 策略）」。

- [ ] **Step 4: 跑测试确认绿**

Run: 同 Step 2。
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/services/backup/_constants.py fastapi_app/tests/test_backup_retention_policy.py
git commit -m "feat(backup): 保留天数默认值改 7（全量-only 策略）"
```

---

### Task 2: 全量-only 保留回归测试（先红）

**Files:**
- Create: `fastapi_app/tests/test_backup_full_only_retention.py`
- 依赖：Task 3 实现后转绿（本任务只写测试并看它红）

**Interfaces:**
- Consumes: `cleanup_service.BackupCleanupService.smart_cleanup() -> dict`（返回含 `summary.deleted_files` / `summary.kept_files` / `success`）；`cleanup_service.BACKUP_DIR`。
- Produces: 覆盖 Review Focus 1–4 的回归测试。

- [ ] **Step 1: 写测试文件**

```python
"""全量-only 保留策略回归（2026-10-12）。

覆盖：超天数删、天数内留、至少留 1 个、正在写入跳过、增量文件不扫、伴生文件同删。
"""
import json
import os
from datetime import datetime

import pytest

from fastapi_app.services.backup.cleanup import service as cleanup_service
from fastapi_app.services.backup._constants import RETENTION_DAYS_ENV


def _make(directory, name, *, age_days=0.0, size=8):
    p = directory / name
    p.write_bytes(b'x' * size)
    stamp = datetime.now().timestamp() - age_days * 86400
    os.utime(p, (stamp, stamp))
    return p


def _sidecars(p):
    for s in ('.meta', '.record'):
        (p.parent / (p.name + s)).write_text(
            json.dumps({'created_at': None}), encoding='utf-8')


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    """把清理目标重定向到 tmp_path，并短路 DB 记录删除。"""
    monkeypatch.setattr(cleanup_service, 'BACKUP_DIR', tmp_path)

    async def _no_db(self, deleted_files):
        return len(deleted_files), False

    monkeypatch.setattr(cleanup_service.BackupCleanupService, '_delete_backup_records', _no_db)
    return cleanup_service.BackupCleanupService()


async def test_deletes_full_older_than_retention_days(svc, tmp_path, monkeypatch):
    """20 天前的自动全量 + 保留 7 天 ⇒ 删。"""
    _make(tmp_path, 'erp_auto_daily_20260901_000000.zip', age_days=20)
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert result['success'] is True, result
    assert result['summary']['deleted_files'] == 1, result


async def test_manual_and_auto_are_treated_alike(svc, tmp_path, monkeypatch):
    """手动 erp_backup_ 与自动 erp_auto_daily_ 一视同仁：超期都删。"""
    _make(tmp_path, 'erp_backup_20260901_000000.zip', age_days=20)
    _make(tmp_path, 'erp_auto_daily_20260901_000000.zip', age_days=20)
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert result['summary']['deleted_files'] == 2, result


async def test_keeps_full_within_retention_days(svc, tmp_path, monkeypatch):
    """3 天前的全量 + 保留 7 天 ⇒ 留。"""
    _make(tmp_path, 'erp_auto_daily_20261009_000000.zip', age_days=3)
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert result['summary']['deleted_files'] == 0, result
    assert result['summary']['kept_files'] == 1, result


async def test_never_deletes_all_backups(svc, tmp_path, monkeypatch):
    """全部超期时至少留最新 1 个（Review Focus 1）。"""
    _make(tmp_path, 'erp_auto_daily_20260901_000000.zip', age_days=40)
    _make(tmp_path, 'erp_auto_daily_20260902_000000.zip', age_days=39)
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert result['summary']['kept_files'] >= 1, result
    assert (tmp_path / 'erp_auto_daily_20260902_000000.zip').exists()


async def test_skips_file_being_written(svc, tmp_path, monkeypatch):
    """120 秒内仍在写入的全量不处理（Review Focus 2）。"""
    _make(tmp_path, 'erp_auto_daily_20260901_000000.zip', age_days=20)  # 超期
    fresh = _make(tmp_path, 'erp_auto_daily_20261012_000000.zip', age_days=0)  # 刚写
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    result = await svc.smart_cleanup()
    assert fresh.exists(), '刚写的备份不得被删'
    assert 'erp_auto_daily_20261012_000000.zip' not in result['cleanup_result']['deleted_files']


async def test_incremental_files_are_not_scanned(svc, tmp_path, monkeypatch):
    """残留的 erp_incremental_* 不扫、不动（Review Focus 3）。"""
    inc = _make(tmp_path, 'erp_incremental_20260901_000000.zip', age_days=40)
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    await svc.smart_cleanup()
    assert inc.exists(), '增量文件不在扫描范围内，不应被删'


async def test_sidecars_removed_with_main_file(svc, tmp_path, monkeypatch):
    """删主文件同步删 .meta/.record（Review Focus 4）。"""
    p = _make(tmp_path, 'erp_auto_daily_20260901_000000.zip.enc', age_days=20)
    _sidecars(p)
    monkeypatch.setenv(RETENTION_DAYS_ENV, '7')
    await svc.smart_cleanup()
    assert not p.exists()
    assert not (tmp_path / 'erp_auto_daily_20260901_000000.zip.enc.meta').exists()
    assert not (tmp_path / 'erp_auto_daily_20260901_000000.zip.enc.record').exists()
```

- [ ] **Step 2: 跑测试确认红**

Run: `logs/_pytest_args.txt` 写 `fastapi_app/tests/test_backup_full_only_retention.py -q`，提权跑。
Expected: FAIL（当前 `smart_cleanup` 仍按份数/评分逻辑，且扫描含增量前缀）

- [ ] **Step 3: 提交（红测试）**

```bash
git add fastapi_app/tests/test_backup_full_only_retention.py
git commit -m "test(backup): 全量-only 保留策略回归测试（先红）"
```

---

### Task 3: 重写 `smart_cleanup` 为全量-only 单规则

**Files:**
- Modify: `fastapi_app/services/backup/cleanup/service.py`（重写主体）
- Test: `fastapi_app/tests/test_backup_full_only_retention.py`（Task 2，转绿）

**Interfaces:**
- Consumes: `_constants.retention_days()`；`records._delete_backup_sidecars`。
- Produces: `BackupCleanupService.smart_cleanup() -> dict`；`_enforce_keep_floor`；`_execute_cleanup`（返回结构不变）。

- [ ] **Step 1: 重写 service.py**

整文件替换为（保留 `_execute_cleanup`/`_delete_backup_records`/`_enforce_keep_floor`/`_save_cleanup_report`/`_cleanup_old_reports`/`get_cleanup_history` 的既有语义，删增量链/评分/份数/恢复测试分支）：

```python
"""备份清理服务 —— 全量-only，按天数保留。

规则（唯一）：扫描 BACKUP_DIR 下全量文件（erp_backup_ 手动 / erp_auto_ 自动，
后缀 .zip/.zip.enc），年龄（.meta.created_at，缺则 mtime）> BACKUP_RETENTION_DAYS
天即删；手动与自动一视同仁；任何情况下至少保留最新 1 个。
"""
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psutil
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.core.database import get_async_db_context
from fastapi_app.services.backup._constants import BACKUP_DIR, retention_days
from fastapi_app.services.backup.metrics.alert_service import alert_service
from fastapi_app.services.backup.records import _delete_backup_sidecars
from fastapi_app.shared_models.backup_record import BackupRecord

logger = logging.getLogger(__name__)

_FULL_PREFIXES = ('erp_backup_', 'erp_auto_')
_FULL_SUFFIXES = ('.zip', '.zip.enc')
_WRITE_GRACE_SECONDS = 120


def ensure_backup_dir() -> None:  # log-context: internal helper 无请求上下文
    """确保备份目录存在。**必须定义在本模块**（用本模块 BACKUP_DIR），
    否则从 records 导入会让测试的 monkeypatch(BACKUP_DIR) 失效、在真实目录建目录。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _backup_created_time(f: Path) -> datetime:  # log-context: internal helper 无请求上下文
    """备份文件真实创建时间：优先 .meta.created_at，缺则 mtime。"""
    meta_path = f.parent / (f.name + '.meta')
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            created_at = meta.get('created_at')
            if created_at:
                return datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    return datetime.fromtimestamp(f.stat().st_mtime)


class BackupCleanupService:
    """备份清理服务：全量-only、按天数保留。"""

    def _retention_days(self) -> int:
        """保留天数：env 单一真源（BACKUP_RETENTION_DAYS，默认 7），运行时求值。"""
        return retention_days()

    async def smart_cleanup(self) -> dict[str, Any]:
        logger.info('开始备份清理（全量-only，保留 %d 天）...', self._retention_days())
        try:
            disk_info = await self._check_disk_space()
            backup_files = await self._get_backup_files_info()
            if not backup_files:
                return {'success': True, 'message': '没有找到备份文件',
                        'cleaned_files': [], 'kept_files': [], 'disk_info': disk_info}

            cutoff = datetime.now() - timedelta(days=self._retention_days())
            files_to_keep = {f['name'] for f in backup_files if f['mtime'] >= cutoff}
            files_to_delete = {f['name'] for f in backup_files if f['name'] not in files_to_keep}
            files_to_delete = self._enforce_keep_floor(backup_files, files_to_delete)
            files_to_keep = {f['name'] for f in backup_files} - files_to_delete

            cleanup_result = await self._execute_cleanup(files_to_delete)
            report = await self._generate_cleanup_report(
                backup_files, files_to_keep, files_to_delete, cleanup_result, disk_info)
            if cleanup_result['deleted_count'] > 0:
                await self._send_cleanup_notification(report)
            logger.info('备份清理完成: 删除 %d，保留 %d',
                        cleanup_result['deleted_count'], len(files_to_keep))
            return report
        except Exception as e:  # defensive: cleanup task must report failure but not crash
            logger.error('备份清理失败: %s', e)
            await alert_service.send_alert(task_name='smart_cleanup',
                                           error=f'备份清理失败: {e!s}',
                                           task_type='cleanup', severity='error')
            return {'success': False, 'error': str(e), 'message': '备份清理失败'}

    async def _check_disk_space(self) -> dict[str, Any]:
        """磁盘信息（仅用于报告，不再驱动删除）。"""
        try:
            ensure_backup_dir()
            backup_path = BACKUP_DIR.resolve()
            u = psutil.disk_usage(str(backup_path))
            free_gb = u.free / (1024 ** 3)
            return {'path': str(backup_path), 'total_gb': round(u.total / 1024**3, 2),
                    'used_gb': round(u.used / 1024**3, 2), 'free_gb': round(free_gb, 2),
                    'used_percent': round(u.percent, 2),
                    'free_percent': round(100 - u.percent, 2)}
        except OSError as e:
            logger.error('检查磁盘空间失败: %s', e)
            return {'error': str(e)}

    async def _get_backup_files_info(self) -> list[dict[str, Any]]:
        """扫描全量备份文件（不含增量）。"""
        try:
            ensure_backup_dir()
            out: list[dict[str, Any]] = []
            for fp in BACKUP_DIR.iterdir():
                if not fp.is_file():
                    continue
                if not (fp.name.startswith(_FULL_PREFIXES) and fp.name.endswith(_FULL_SUFFIXES)):
                    continue
                try:
                    if time.time() - fp.stat().st_mtime < _WRITE_GRACE_SECONDS:
                        logger.debug('跳过仍在写入的备份文件: %s', fp.name)
                        continue
                except OSError:
                    continue
                out.append({'path': fp, 'name': fp.name,
                            'size_bytes': fp.stat().st_size,
                            'size_mb': round(fp.stat().st_size / 1024**2, 2),
                            'mtime': _backup_created_time(fp)})
            out.sort(key=lambda x: x['mtime'], reverse=True)
            return out
        except OSError as e:
            logger.error('获取备份文件信息失败: %s', e)
            return []

    def _enforce_keep_floor(self, backup_files: list[dict[str, Any]],
                            files_to_delete: set[str]) -> set[str]:
        """兜底：任何情况下至少留一个可还原的全量备份（列表按 mtime 倒序，首个即最新）。"""
        if any(f['name'] not in files_to_delete for f in backup_files):
            return files_to_delete
        if not backup_files:
            return files_to_delete
        survivor = backup_files[0]['name']
        files_to_delete.discard(survivor)
        logger.warning('本次清理会删光全部 %d 个备份，已强制保留 %s', len(backup_files), survivor)
        return files_to_delete

    # _execute_cleanup / _delete_backup_records / _save_cleanup_report /
    # _cleanup_old_reports / _send_cleanup_notification / get_cleanup_history
    # —— 保持现有实现不变（见当前文件），仅 _generate_cleanup_report 见下。

    async def _generate_cleanup_report(self, backup_files, files_to_keep,
                                       files_to_delete, cleanup_result, disk_info) -> dict[str, Any]:
        try:
            total_mb = sum(f['size_mb'] for f in backup_files)
            deleted_mb = sum(f['size_mb'] for f in backup_files if f['name'] in files_to_delete)
            kept_mb = sum(f['size_mb'] for f in backup_files if f['name'] in files_to_keep)
            report = {
                'timestamp': datetime.now().isoformat(),
                'success': cleanup_result['success'],
                'disk_info': disk_info,
                'retention_days': self._retention_days(),
                'summary': {
                    'total_files': len(backup_files), 'kept_files': len(files_to_keep),
                    'deleted_files': len(files_to_delete),
                    'total_size_mb': round(total_mb, 2), 'kept_size_mb': round(kept_mb, 2),
                    'deleted_size_mb': round(deleted_mb, 2),
                },
                'cleanup_result': cleanup_result,
            }
            await self._save_cleanup_report(report)
            return report
        except Exception as e:  # defensive: report generation must not abort cleanup
            logger.error('生成清理报告失败: %s', e)
            return {'timestamp': datetime.now().isoformat(), 'success': False, 'error': str(e)}


cleanup_service = BackupCleanupService()
```

**注意**：`_execute_cleanup` 返回结构必须保持 `{deleted_count, deleted_files, deleted_records, error_count, errors, success}`（Task 2 与既有测试断言依赖）。

- [ ] **Step 2: 跑新回归测试确认绿**

Run: 提权跑 `fastapi_app/tests/test_backup_full_only_retention.py -q`
Expected: PASS（7 项全绿）

- [ ] **Step 3: 跑既有清理相关测试**

Run: 提权跑 `fastapi_app/tests/test_backup_retention_policy.py -q -k "execute_cleanup or sidecars or cleanup_service_reads"`
Expected: PASS（`_execute_cleanup` 语义未变）

- [ ] **Step 4: 变异检查**

把 `_enforce_keep_floor` 的 `files_to_delete.discard(survivor)` 临时注释掉 → `test_never_deletes_all_backups` 必须**红**；改回。

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/services/backup/cleanup/service.py
git commit -m "refactor(backup): 清理服务重写为全量-only 单规则（超天数删、至少留 1 个）"
```

---

### Task 4: 删除第二套清理 `records.cleanup_old_backups`

**Files:**
- Modify: `fastapi_app/services/backup/records.py`（删 `cleanup_old_backups`、`_retention_thresholds`、`_BackupRecord` TypedDict 若仅此处用）
- Modify: `fastapi_app/services/backup/__init__.py`（删 `cleanup_old_backups` 导出，`:227`）
- Test: `fastapi_app/tests/test_backup_retention_policy.py`（删相关用例）、`fastapi_app/tests/test_backup.py`（`:273-434` 段）

**Interfaces:**
- 保留：`_delete_backup_sidecars`、`_backup_created_time`、`normalize_backup_ts`（注：已于 2026-10-23 P2-26 删除，生产零调用）、`sync_backup_records`、`write_backup_record`。

- [ ] **Step 1: 删代码**

- 删 `records.py` 的 `cleanup_old_backups()`（约 `:644-754`）与 `_retention_thresholds()`（约 `:639-641`）。
- 删 `records.py` 中对 `retention_days/retention_count` 的 import（`:23` 附近），若不再使用。
- 删 `__init__.py:227` 的 `"cleanup_old_backups"` 导出。
- 确认 `_BackupRecord` TypedDict（`:45`）是否仅 `cleanup_old_backups` 用——是则一并删。

- [ ] **Step 2: 删/改测试**

- `test_backup_retention_policy.py`：删 `test_cleanup_deletes_backup_older_than_env_days`、`test_cleanup_keeps_backup_within_env_days`、`test_cleanup_count_threshold_follows_env_not_hardcoded_50`、`test_expired_encrypted_backup_removes_meta_and_record`、`test_kept_backup_sidecars_are_untouched`、`test_meta_created_at_drives_age_instead_of_mtime`、`test_sidecar_delete_failure_does_not_break_main_delete`（这些直接调 `records.cleanup_old_backups`）；其覆盖的行为已由 Task 2 新测试承担。
- 该文件的 `test_retention_consumers_do_not_read_env_directly` 参数化列表去掉 `'fastapi_app.services.backup.records'`（records 已无保留逻辑）。
- 该文件的 `test_cleanup_service_reads_the_same_env_keys` 改为只断言天数（删 count 断言）：

```python
def test_cleanup_service_reads_the_same_env_keys(monkeypatch):
    from fastapi_app.services.backup.cleanup.service import BackupCleanupService
    monkeypatch.setenv(RETENTION_DAYS_ENV, '13')
    assert BackupCleanupService()._retention_days() == 13 == retention_days()
```

- `test_backup.py:273-434` 段内调 `cleanup_old_backups()` 的用例：整段删除（对应行为由 Task 2 覆盖）。

- [ ] **Step 3: 跑测试**

Run: 提权跑 `fastapi_app/tests/test_backup_retention_policy.py fastapi_app/tests/test_backup.py -q`
Expected: PASS（无 `AttributeError: cleanup_old_backups`）

- [ ] **Step 4: 提交**

```bash
git add fastapi_app/services/backup/records.py fastapi_app/services/backup/__init__.py fastapi_app/tests/test_backup_retention_policy.py fastapi_app/tests/test_backup.py
git commit -m "refactor(backup): 删除 records.cleanup_old_backups 第二套清理实现"
```

---

### Task 5: 删除增量服务层

**Files:**
- Delete: `fastapi_app/services/backup/incremental.py`
- Modify: `fastapi_app/services/backup/__init__.py`（star import + `__all__`）
- Modify: `fastapi_app/services/backup/verify/core.py`（删 `find_last_backup_timestamp`，`:163`）

**Interfaces:**
- 保留：`query_table_rows`（仍被 `verify`/`recovery_test` 用？——执行前 `grep -rn "query_table_rows" fastapi_app/ | grep -v tests` 复核；若仅增量用则一并删，否则保留）。

- [ ] **Step 1: 复核调用点**

```bash
grep -rn "find_last_backup_timestamp\|query_table_rows" fastapi_app/ --include=*.py | grep -v "/tests/"
```
Expected: `find_last_backup_timestamp` 仅 `incremental.py` 引用（可删）；`query_table_rows` 记录其全部引用方（决定删或留）。

- [ ] **Step 2: 删代码**

- `git rm fastapi_app/services/backup/incremental.py`
- `__init__.py`：删 star import 行（`:105` 附近）与 `__all__` 中 `create_incremental_backup` / `restore_incremental` / `find_last_backup_timestamp`（`:237-239, 246, 276`）。
- `verify/core.py`：删 `find_last_backup_timestamp`（`:163-…`）；若 Step 1 显示 `query_table_rows` 无其它调用方，一并删。

- [ ] **Step 3: 导入自检**

Run: `.venv/Scripts/python.exe -c "import fastapi_app.services.backup as b; print('ok')"`
Expected: 打印 `ok`（无 ImportError / 无 `__all__` 悬挂）

- [ ] **Step 4: 提交**

```bash
git add -A fastapi_app/services/backup/
git commit -m "refactor(backup): 删除增量备份服务层（incremental.py 及导出）"
```

---

### Task 6: 删除增量任务、调度与模型默认

**Files:**
- Modify: `fastapi_app/tasks/backup_tasks.py`（删两个增量任务 + `_do_auto_backup` 的 else 分支）
- Modify: `fastapi_app/core/arq_app.py`（import + functions 注册）
- Modify: `fastapi_app/services/backup/schedule_service.py`（`TASK_TYPE_TO_FUNC`）
- Modify: `fastapi_app/shared_models/backup_schedule.py:22`（默认 `'incremental'` → `'full'`）

**Interfaces:**
- 保留：`_do_auto_backup` 收敛为只处理 `'daily'`；`auto_daily_backup_task` 与 `_do_auto_backup_with_metrics` 不动。

- [ ] **Step 1: 改 `_do_auto_backup`（先看共享函数）**

`backup_tasks.py` 的 `_do_auto_backup(backup_type)`：删 `else` 分支（`:725-746`），使其仅接受 `'daily'`；函数签名保持 `backup_type: str`，非 `'daily'` 时 `raise ValueError`。

- [ ] **Step 2: 删任务函数**

删 `manual_incremental_backup_task`（`:173-246`）、`auto_incremental_backup_task`（`:481-538`）。

- [ ] **Step 3: 删注册与映射**

- `arq_app.py`：删 import（`:217, 224`）与 functions 列表项（`:371, 373`）。
- `schedule_service.py:25`：删 `'incremental': 'auto_incremental_backup_task',`。
- `shared_models/backup_schedule.py:22`：`default='incremental'` → `default='full'`。

- [ ] **Step 4: 导入自检 + 相关测试**

Run: `.venv/Scripts/python.exe -c "import fastapi_app.core.arq_app; print('ok')"`
Expected: `ok`

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/tasks/backup_tasks.py fastapi_app/core/arq_app.py fastapi_app/services/backup/schedule_service.py fastapi_app/shared_models/backup_schedule.py
git commit -m "refactor(backup): 删除增量备份任务、调度映射与模型默认值"
```

---

### Task 7: `policy_service` 重写为 full + retention

**Files:**
- Modify: `fastapi_app/services/backup/orchestration/policy_service.py`
- Test: `fastapi_app/tests/services/test_backup_policy_service.py`（约 20 处增量断言）

**Interfaces:**
- Produces: `BackupPolicyService._get_default_policy()` 返回的 `retention` 只含 `retention_days`（无 `retention_count`/`keep_manual_backups`/`keep_failed_backups`）；`required_fields` 不再要求 `incremental_backup`。

- [ ] **Step 1: 删增量引用**

按 spec §4.1，处理 `policy_service.py` 的：`:58 incremental_backup_cron`、`:122-124` 默认策略块、**`:218 required_fields`（去掉 `'incremental_backup'`）**、`:226` 校验、`:346-348` update、`:392` 禁用判断、`:488`、`:669-672`（`type=='incremental'` 查询）、`:691-693` compliance 报告键。

**关键**：`_validate_policy` 的 `required_fields` 由 `['policy_name','full_backup','incremental_backup','retention']` 改为 `['policy_name','full_backup','retention']`——否则存量策略 JSON 判非法。

- [ ] **Step 2: 跑策略测试**

Run: 提权跑 `fastapi_app/tests/services/test_backup_policy_service.py -q`
Expected: 先红（断言增量），逐个改为 full-only 后 PASS。

- [ ] **Step 3: 提交**

```bash
git add fastapi_app/services/backup/orchestration/policy_service.py fastapi_app/tests/services/test_backup_policy_service.py
git commit -m "refactor(backup): policy_service 收敛为 full + retention"
```

---

### Task 8: 删除增量端点与 schema

**Files:**
- Modify: `fastapi_app/api/v1/endpoints/backup/restore.py`（删 `POST /restore-incremental/{filename}`，`:377-420`）
- Modify: `fastapi_app/api/v1/endpoints/backup/export.py`（增量创建分支，`:353`）
- Modify: `fastapi_app/api/v1/endpoints/backup/actions.py`（手动增量触发，`:174, 187`）
- Modify: `fastapi_app/api/v1/endpoints/backup/_deps.py`（`:50, 55, 65` 增量权限映射）
- Modify: `fastapi_app/schemas/backup.py`（`IncrementalBackupResponse:211`、`IncrementalRestoreResponse:224`、`BackupIncrementalRequest:359`）

- [ ] **Step 1: 删端点与 schema**

按上列 file:line 删除。`restore.py` 顶部 docstring 的路由清单同步删 `POST /restore-incremental`。

- [ ] **Step 2: 导入自检**

Run: `.venv/Scripts/python.exe -c "import fastapi_app.main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 提交**

```bash
git add fastapi_app/api/v1/endpoints/backup/ fastapi_app/schemas/backup.py
git commit -m "refactor(backup): 删除增量备份端点与 schema"
```

---

### Task 9: 配置三处同批删除（env_drift 门禁）

**Files:**
- Modify: `.env.example:263`、`fastapi_app/core/config.py:254`、`fastapi_app/services/backup/orchestration/policy_service.py:58`

- [ ] **Step 1: 三处同删**

删 `BACKUP_INCREMENTAL_CRON`：`.env.example` 条目、`config.py` 的 strict-check 告警清单项、`policy_service.py` 的 `os.environ.get('BACKUP_INCREMENTAL_CRON', ...)`。

- [ ] **Step 2: 跑 env_drift 门禁**

Run: `.venv/Scripts/python.exe scripts/ops/check_env_drift.py`
Expected: PASS（无新增漂移；若报 `BACKUP_INCREMENTAL_CRON` 残留，说明漏删某处）

- [ ] **Step 3: 提交**

```bash
git add .env.example fastapi_app/core/config.py fastapi_app/services/backup/orchestration/policy_service.py
git commit -m "chore(backup): 删除 BACKUP_INCREMENTAL_CRON（三处同批，避免 env 漂移门禁红）"
```

---

### Task 10: 前端删除增量入口

**Files:**
- Modify: `frontend-vite/src/components/backup/ScheduleConfig.vue`（`:10` option、`:64` 默认值、`:68` 标签）
- Modify: `frontend-vite/src/views/backup/BackupView.vue`（`:213-225` triggerIncremental、`:246-253` triggerScheduleNow 回退）
- Modify: `frontend-vite/src/api/backup.ts`（`:114-117, 139-141`）
- Modify: `frontend-vite/src/components/backup/BackupActions.vue`（`:8` 按钮）
- Modify: `frontend-vite/src/components/backup/BackupRecordTable.vue`（`:5, 22, 99` 增量类型分支）

- [ ] **Step 1: 改 ScheduleConfig**

删 `<option value="incremental">增量备份</option>`（`:10`）与 `TASK_TYPE_LABELS` 的 `incremental` 项（`:68`）；`const taskType = ref('incremental')`（`:64`）→ `ref('full')`。

- [ ] **Step 2: 改 BackupView**

删 `triggerIncremental()`；`triggerScheduleNow()` 改为：

```ts
async function triggerScheduleNow() {
  const first = schedules.value.find((s) => s.enabled)
  if (!first?.name) {
    toast.info('当前没有启用的定时任务')
    return
  }
  await backupApi.triggerSchedule(first.name)
}
```

- [ ] **Step 3: 改 api/backup.ts 与其余组件**

删 `saveIncremental`、`restoreIncremental`、`triggerIncremental`、`last_incremental`；删 `BackupActions.vue` 增量按钮；删 `BackupRecordTable.vue` 增量类型分支。

- [ ] **Step 4: 前端门禁**

Run: `cd frontend-vite && npm run type-check && npm run lint`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/
git commit -m "refactor(backup): 前端删除增量备份入口"
```

---

### Task 11: openapi 重导 + 生成类型 + 前端测试夹具

**Files:**
- Regenerate: `frontend-vite/openapi.json`、`frontend-vite/src/types/api.d.ts`
- Modify: `frontend-vite/src/test/backupRecordTablePaging.test.ts:56-58`

- [ ] **Step 1: 重导 openapi 快照**

Run: `.venv/Scripts/python.exe scripts/check_openapi_frontend_alignment.py --export frontend-vite/openapi.json`
（需提权：`import fastapi_app.main` 会读根 `.env`）

- [ ] **Step 2: 重生成 TS 类型**

Run: `cd frontend-vite && npm run gen:api`

- [ ] **Step 3: 改前端测试夹具**

`backupRecordTablePaging.test.ts:56-58` 的 `type: 'incremental'` 行改用 `'full'`（或删该筛选用例）。

- [ ] **Step 4: 跑前端门禁**

Run: `cd frontend-vite && npm run type-check && npm test -- backupRecordTablePaging && npm run check:api && npm run check:types`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/openapi.json frontend-vite/src/types/api.d.ts frontend-vite/src/test/backupRecordTablePaging.test.ts
git commit -m "chore(backup): 重导 openapi 快照与前端类型，修前端测试夹具"
```

---

### Task 12: 后端测试盘点与收尾

**Files:**
- 后端：`fastapi_app/tests/`（14 文件）+ 根 `tests/`（5 文件）含 `incremental` 引用

- [ ] **Step 1: 全量盘点**

```bash
grep -rln "incremental" fastapi_app/tests/ tests/ --include=*.py
```
逐个甄别：纯增量用例删；共享夹具改；`tests/test_migration_056/057/058*.py` **不动**。

- [ ] **Step 2: 跑备份域测试**

Run: 提权跑 `fastapi_app/tests/test_backup*.py fastapi_app/tests/services/test_backup*.py fastapi_app/tests/test_arq_worker_health.py -q`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add fastapi_app/tests/ tests/
git commit -m "test(backup): 清理增量相关测试与夹具"
```

---

### Task 13: 迁移 092（删增量调度行与历史记录）

**Files:**
- Create: `migrations/versions/pg_standalone_092_drop_incremental_backup.py`

- [ ] **Step 1: 写迁移**

```python
"""删除增量备份残留：backup_schedule 的 incremental 行 + backup_record 的增量历史

背景：/backup 收敛为全量-only（见 docs/superpowers/specs/2026-10-12-full-only-backup-design.md）。
036/056 曾种下 incremental 调度行，本迁移幂等删除；历史增量记录一并清理。
DELETE 不触发 destructive DDL 扫描。

Revision ID: pg_standalone_092_drop_incremental_backup
Revises: pg_standalone_091_report_row_action_per_tab
"""
from alembic import op

revision = 'pg_standalone_092_drop_incremental_backup'
down_revision = 'pg_standalone_091_report_row_action_per_tab'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM backup_schedule WHERE task_type = 'incremental'")
    op.execute("DELETE FROM backup_record WHERE type = 'incremental'")


def downgrade() -> None:
    # 数据删除不可逆；回滚仅恢复调度行（enabled=FALSE，与 056 口径一致）
    op.execute(
        "INSERT INTO backup_schedule (name, task_type, cron_expr, enabled) "
        "SELECT '每日增量备份', 'incremental', '0 6,10,14,18,22 * * *', FALSE "
        "WHERE NOT EXISTS (SELECT 1 FROM backup_schedule WHERE task_type = 'incremental')"
    )
```

- [ ] **Step 2: 空库验证（不得对生产 autogenerate）**

在**临时空库** `alembic upgrade head` 后 `alembic check`（口径同 CI）。

- [ ] **Step 3: 单一 head 检查**

Run: `.venv/Scripts/python.exe -c "from alembic.config import Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config('alembic.ini')).get_heads())"`
Expected: `['pg_standalone_092_drop_incremental_backup']`（单元素）

- [ ] **Step 4: 提交**

```bash
git add migrations/versions/pg_standalone_092_drop_incremental_backup.py
git commit -m "feat(backup): 迁移 092 删除增量调度行与历史记录"
```

---

### Task 14: 生产数据清理（提权 + 护栏）

**Files:** 生产库 `backup_record` / `backup_schedule`；磁盘 `backups/server/erp_incremental_*`

**⚠️ 顺序敏感**：先删磁盘文件，再删 DB 记录（否则启动 `sync_backup_records` 会补录残留文件）。

- [ ] **Step 1: 备份现状快照（只读）**

提权查：`SELECT id, filename FROM backup_record WHERE type='incremental'` 与 `SELECT id, name, task_type, enabled FROM backup_schedule`，落盘留证。

- [ ] **Step 2: 删磁盘增量文件**

提权删 `backups/server/erp_incremental_*.zip` 及其 `.meta`（现存 `erp_incremental_20261012_022000.zip` + `.meta`）。

- [ ] **Step 3: 应用迁移 092 到生产**

提权 `alembic upgrade head`（删除 `backup_schedule` 增量行 + `backup_record` 增量记录）。**不得** autogenerate。

- [ ] **Step 4: 验证**

提权查：`SELECT count(*) FROM backup_schedule WHERE task_type='incremental'`（=0）、`SELECT count(*) FROM backup_record WHERE type='incremental'`（=0）；`ls backups/server/` 无 `erp_incremental_*`。

---

### Task 15: 全量门禁 + 生产验证

- [ ] **Step 1: 后端门禁**

Run: `ruff check .` / `mypy` / `python scripts/quality_gate.py` / `python scripts/check_orphan_modules.py` / `python scripts/scan_secrets.py --verbose`

- [ ] **Step 2: 前端门禁**

Run: `cd frontend-vite && npm run type-check && npm test && npm run lint && npm run check:api && npm run check:api:pc && npm run check:routes && npm run check:dto && npm run check:types`

- [ ] **Step 3: 全量 pytest（提权、独占）**

Run: `powershell -File logs/_run_pytest_elevated.ps1`

- [ ] **Step 4: 生产验证**

- `/backup` 页面无「增量备份」选项/按钮/还原入口；调度列表无 incremental。
- 提权跑一次清理（`backup_schedule` cleanup 行触发或手动触发），确认只按 7 天删、增量文件/记录不再出现。
- 全仓 `grep -rn "incremental" fastapi_app/ --include=*.py | grep -v /tests/` 仅剩注释/历史兼容分支。

- [ ] **Step 5: 清理临时文件**

删 `logs/` 下本次自建的脚本与输出。

---

## 自检记录（spec 覆盖）

- §3 保留策略 → Task 1/2/3；§4.1 后端删除 → Task 5/6/7/8；§4.2 前端 → Task 10；§4.3 配置 → Task 9；§4.4 测试 → Task 12；§4.5 门禁 → Task 11/15；§5 生产数据 → Task 14；§6 迁移 → Task 13；§7 风险 → 各任务处置；§8 验证 → Task 2/3/15。
- Review Focus 1–5 → 分别由 Task 2 的 `test_never_deletes_all_backups` / `test_skips_file_being_written` / `test_incremental_files_are_not_scanned` / `test_sidecars_removed_with_main_file` 覆盖；Focus 5（`backup_settings` 死列）由 Task 8 的 `/backup/settings` 接口保持 + Task 15 前端门禁覆盖。

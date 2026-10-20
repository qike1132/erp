"""备份导入与恢复路由。

从原 backup.py 拆分，URL / schema / 权限码保持不变：
- POST /import                       一键恢复：从上传文件恢复
- POST /restore-by-name/{filename}   从服务器默认路径恢复指定备份
- GET  /progress/{task_id}           查询异步任务进度
- POST /async-import                 异步恢复：从上传文件恢复
- POST /async-restore-by-name/{name} 异步恢复：从服务器文件恢复
"""
import asyncio
import gzip
import io
import json
import logging
import os
import zlib
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.backup._deps import (
    _background_tasks,
    _get_encryption_password,
    require_backup_permission,
)
from fastapi_app.core.backup_progress import _sanitize_error
from fastapi_app.core.database import get_async_db
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.response import success_response
from fastapi_app.schemas.backup import (
    AsyncTaskResponse,
    BackupImportResponse,
    BackupProgressOut,
    BackupRestorePlanOut,
    BackupRestorePlanRequest,
)
from fastapi_app.services import backup as backup_service
from fastapi_app.services.backup import (
    BackupError,
)
from fastapi_app.services.backup import restore_plan as restore_plan_service
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


async def _redis_unavailable() -> bool:
    """探测 Redis 是否可用（用于区分 409 锁被占与 503 锁服务故障）。

    委托 core.backup_progress.is_redis_available 统一实现。
    """
    try:
        from fastapi_app.core.backup_progress import is_redis_available
        return not await is_redis_available()
    except Exception:  # broad-except: 探测失败按不可用处理（fail-closed）
        return True


async def _acquire_sync_restore_lock(purpose: str) -> str:
    """同步还原路径统一获取 Redis 还原锁（P0-5 锁统一），返回本次持锁的 owner token。

    - 与异步任务路径共用同一把锁（erp:restore_lock），消除旧实现"同步走 PG
      advisory、异步走 Redis，可各持一种锁并发还原"的窗口；
    - fail-closed：Redis 不可用时 503 拒绝还原。

    token **每次请求唯一**（purpose 仅作可读前缀）：释放走 Lua 比对 value，
    若沿用固定字符串，则锁过期后新请求取到的 value 与旧请求相同，旧请求迟到的
    `finally` 会误删新请求的锁。调用方必须把返回值原样交给 `release_restore_lock`。
    """
    owner = f'{purpose}:{uuid4().hex}'
    if not await backup_service.acquire_restore_lock(owner):
        if await _redis_unavailable():
            logger.error('Redis 不可用，拒绝执行恢复操作（fail-closed）')
            raise HTTPException(status_code=503, detail='恢复锁服务暂时不可用，请稍后重试')
        raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')
    return owner


async def fail_progress_quietly(task_id: str) -> None:
    """锁获取失败时把进度键标记为失败（避免前端轮询假死 1 小时）。"""
    try:
        from fastapi_app.core.backup_progress import fail_progress
        await fail_progress(task_id, '获取恢复锁失败，任务未启动')
    except Exception as e:  # broad-except: 进度上报失败不影响主流程
        logger.warning(f'标记进度失败（{task_id}）: {e}')


async def _sniff_server_backup_format(content: bytes, safe_name: str, decrypt_password: str | None) -> tuple[bytes, bool]:
    """从服务器恢复：识别（必要时先解密）备份格式，返回 (明文内容, is_zip)。

    2026-10-18 OCR 评审（AUD-07 只改了一半）：`.json.enc` 的解密此前只加在
    **上传**路径 `_read_backup_file`，「从服务器恢复」的两个端点
    （`/restore-by-name`、`/async-restore-by-name`）仍是裸 `json.loads(content)`
    —— 加密 JSON 备份从服务器还原时必定 400「格式无效」，且报错指向 JSON 而
    非加密，排查时完全看不出是漏了解密。

    这里与上传路径保持同一套判定顺序（zip → json → gz → .enc 解密后再判），
    避免两条路径对同一格式给出不同答案。解压也在此收口（上传路径同样会解），
    故调用方拿到的 content 已是可直接 `json.loads` 的明文。
    """
    is_zip = safe_name.endswith('.zip') or safe_name.endswith('.zip.enc') or content[:4] == b'PK\x03\x04'
    is_json = safe_name.endswith('.json') or (content[:1] == b'{' and content.strip().endswith(b'}'))
    is_gz = safe_name.endswith('.gz') or (content[:2] == b'\x1f\x8b')
    if not is_zip and not is_json and not is_gz and safe_name.endswith('.enc'):
        # 加密的非 ZIP 备份（.json.enc 等）：先解密再识别格式
        if not decrypt_password:
            raise HTTPException(
                status_code=400,
                detail='该备份已加密，请通过请求体 password 或 X-Backup-Password 请求头提供解密密码',
            )
        try:
            from fastapi_app.core.backup_encryption import BackupFileError, decrypt_backup_auto

            def _decrypt_server(data: bytes, pwd: str) -> bytes:
                plaintext, _meta = decrypt_backup_auto(data, pwd)
                return plaintext

            content = await asyncio.to_thread(_decrypt_server, content, decrypt_password)
        except (BackupFileError, ValueError, OSError) as e:
            raise HTTPException(
                status_code=400, detail=_sanitize_error(f'加密备份解密失败: {e}'),
            ) from e
        is_zip = content[:4] == b'PK\x03\x04'
        is_json = content[:1] == b'{' and content.strip().endswith(b'}')
        is_gz = content[:2] == b'\x1f\x8b'
    if not is_zip and not is_json and not is_gz:
        raise HTTPException(status_code=400, detail='无法识别的备份文件格式')
    if is_gz:
        try:
            # 解压是 CPU/IO 阻塞操作，与上传路径一致移入线程池，避免卡住事件循环
            content = await asyncio.to_thread(
                _decompress_gzip_bounded, content, backup_service.MAX_BACKUP_FILE_SIZE,
            )
        except (OSError, EOFError, ValueError, zlib.error) as e:
            # BadGzipFile 是 OSError 子类；截断的 gz 抛 EOFError；坏块抛 zlib.error
            raise HTTPException(status_code=400, detail=_sanitize_error(f'gzip 备份文件无法解压: {e}')) from e
        is_json = True
    return content, is_zip


async def _read_backup_file(
    file: UploadFile, decrypt_password: str | None = None,
) -> tuple[bytes, bool, str]:
    """读取并校验备份上传文件，返回 (content, is_zip, filename)。

    校验扩展名、文件大小上限、空内容与格式识别，不合法直接抛 HTTPException。
    从 import_backup / async_import_backup 中提取的公共逻辑。

    2026-10-17 审计 AUD-07：`.enc` 白名单此前自相矛盾——格式识别只认明文
    特征（PK/{/gz），而 `/export?format=json&encrypt=true` 产出的 `.json.enc`
    首字节是 meta 长度前缀，三探针全不匹配 → 上传即 400，加密 JSON 导出
    永远无法导入。现在对「.enc 且非 zip」先解密再识别。
    """
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz', '.enc'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .zip.enc / .json / .gz')
    try:
        content = await file.read()
        if len(content) > backup_service.MAX_BACKUP_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)')
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=_sanitize_error(f'读取文件失败: {e}')) from e
    if not content:
        raise HTTPException(status_code=400, detail='备份文件内容为空')
    is_zip = filename.endswith('.zip') or filename.endswith('.zip.enc') or content[:4] == b'PK\x03\x04'
    is_json = filename.endswith('.json') or (content[:1] == b'{' and content.strip().endswith(b'}'))
    is_gz = filename.endswith('.gz') or (content[:2] == b'\x1f\x8b')
    if not is_zip and not is_json and not is_gz and ext == '.enc':
        # 加密的非 ZIP 备份（如 .json.enc）：先解密再做格式识别
        if not decrypt_password:
            raise HTTPException(
                status_code=400,
                detail='该备份已加密，请通过 X-Backup-Password 请求头提供解密密码',
            )
        try:
            from fastapi_app.core.backup_encryption import BackupFileError, decrypt_backup_auto

            def _decrypt_upload(data: bytes, pwd: str) -> bytes:
                plaintext, _meta = decrypt_backup_auto(data, pwd)
                return plaintext

            content = await asyncio.to_thread(_decrypt_upload, content, decrypt_password)
        except (BackupFileError, ValueError, OSError) as e:
            raise HTTPException(
                status_code=400, detail=_sanitize_error(f'加密备份解密失败: {e}'),
            ) from e
        is_zip = content[:4] == b'PK\x03\x04'
        is_json = content[:1] == b'{' and content.strip().endswith(b'}')
        is_gz = content[:2] == b'\x1f\x8b'
    if not is_zip and not is_json and not is_gz:
        raise HTTPException(status_code=400, detail='无法识别的备份文件格式')
    if is_gz:
        try:
            content = await asyncio.to_thread(
                _decompress_gzip_bounded, content, backup_service.MAX_BACKUP_FILE_SIZE,
            )
        except (OSError, EOFError, ValueError, zlib.error) as e:
            # BadGzipFile 是 OSError 子类；截断的 gz 抛 EOFError；坏块抛 zlib.error
            raise HTTPException(status_code=400, detail=_sanitize_error(f'gzip 备份文件无法解压: {e}')) from e
        is_json = True
    return content, is_zip, filename


async def _pre_restore_info_or_fail(
    db: AsyncSession, allowed: bool, *, skip_restore_check: bool = False,
) -> dict:
    """落一份还原前安全备份，并过闸门；不成功且未显式放行时抛 428。

    三个还原端点（同步 /import、同步 /restore-by-name、异步任务）共用，
    避免各自复制 try/except 与闸门调用 —— 漏掉一处就是一条无回滚点的还原路径。
    """
    try:
        info = await backup_service.create_pre_restore_backup(db, skip_restore_check=skip_restore_check)
    except (BackupError, OSError):
        info = {'success': False, 'error': '创建安全备份失败'}
    _require_pre_restore_backup(info, allowed)
    return info


def _decompress_gzip_bounded(content: bytes, limit: int) -> bytes:
    """有上限地解压 gzip，超限即拒绝 —— 防「压缩炸弹」。

    `gzip.decompress` 会一次性解出全部内容：500MB 的上传上限**拦不住**炸弹
    （gzip 压缩比可达 ~1000:1，即 500MB 密文能解出 500GB，直接 OOM 打挂进程）。
    `GzipFile.read(n)` 最多只取 n 字节，因此这里读 limit+1 字节即可判定是否超限，
    多余的一个字节专门用来区分「正好等于上限」与「超过上限」。
    """
    with gzip.GzipFile(fileobj=io.BytesIO(content)) as gz:
        data = gz.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'解压后超过大小限制({limit // 1024 // 1024}MB)，疑似压缩炸弹')
    return data


def _restore_error_to_http(exc: Exception) -> HTTPException:
    """恢复失败统一映射为 500，并保留原因。

    与 zip 分支 `BackupError → HTTPException(500, str(e))` 的既有约定一致；
    覆盖 db_transaction 对 ValueError 的默认 400 转换，保持 JSON 路径原有状态码不变
    （恢复失败是服务端问题，不应报 400 让客户端以为是自己传错了备份）。
    """
    logger.exception('备份恢复失败')
    return HTTPException(status_code=500, detail=_sanitize_error(str(exc)) or '备份恢复失败')


def _require_pre_restore_backup(pre_info: dict, allowed: bool) -> None:
    """安全备份失败时**默认拒绝**破坏性还原；显式开关可放行。

    `create_pre_restore_backup` 的注释写着「不阻塞恢复」，但那使运维在**不知情**的
    状态下覆盖整库：失败只写进 `pre_restore_info`，此前**没有任何界面读取它**
    （向导只渲染 result.error/status）—— 于是"有回滚点"是错觉。

    这里不做价值判断，只把静默风险变成**知情选择**：
    默认 fail-closed 拒绝（与还原锁同一取向），确认无回滚点也要继续时，
    调用方显式传 `allow_missing_pre_restore_backup=true`。
    """
    if pre_info.get('success') is True or allowed:
        return
    raise HTTPException(
        status_code=428,
        detail=(
            f"未能创建还原前安全备份（{pre_info.get('error') or '未知原因'}）。"
            '本次还原会覆盖整库且**没有回滚点**；磁盘满时还原本身也很可能中途失败。'
            '确认要在无安全备份的情况下继续，请传 allow_missing_pre_restore_backup=true。'
        ),
    )


# ---------------------------------------------------------------------------
# POST /import
# ---------------------------------------------------------------------------
@router.post('/import', response_model=BackupImportResponse)
async def import_backup(
    file: UploadFile = File(...),
    confirm: bool = False,
    confirm_sensitive: bool = Query(False, description='确认同时还原敏感配置文件（.env.production / jwt 密钥），默认跳过'),
    allow_missing_pre_restore_backup: bool = Query(
        False, description='安全备份失败时仍继续还原（无回滚点，慎用）',
    ),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('import_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """一键恢复：从备份文件恢复全部数据

    解密密码仅通过 X-Backup-Password 请求头或环境变量提供（H3：multipart 端点
    无法安全混合 JSON body，且密码不进 URL query 避免落入访问日志/浏览器历史）。
    """
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    content, is_zip, _ = await _read_backup_file(file, _get_encryption_password(None, x_backup_password))
    decrypt_password = _get_encryption_password(None, x_backup_password)

    # P0-5: 同步路径统一 Redis 还原锁（fail-closed），与异步任务共用。
    # P1-9：安全备份必须放在**取锁成功之后**——并发恢复时先 409，避免
    # create_pre_restore_backup 的 BackupLockError 被吞成「无回滚点」428
    # 诱导用户带 allow_missing 跳过回滚点。
    lock_owner = await _acquire_sync_restore_lock('sync_import')
    try:
        pre_restore_info = await _pre_restore_info_or_fail(db, allow_missing_pre_restore_backup)
        if is_zip:
            # zip 路径的提交点在策略层（strategies.py `await db.commit()`，已按
            # TRANSACTION_BOUNDARY_GUIDE §2.2 标注豁免）；端点层不重复提交。
            # 捕获 `BackupError` 而非仅 `RestoreError`：JSON 分支映射的是整个家族，
            # 若此处只认 RestoreError，则 BackupFileError/BackupLockError 等兄弟异常
            # 会越过本 handler 落到全局兜底，detail 丢失、与 JSON 分支行为分叉。
            try:
                result = await backup_service.restore_from_zip(
                    content, db,
                    decrypt_password=decrypt_password,
                    confirm_sensitive=confirm_sensitive,
                )
            except BackupError as e:
                raise HTTPException(status_code=500, detail=_sanitize_error(str(e))) from e
            result['pre_restore_backup'] = pre_restore_info
            total_rows = sum(td.get('rows', 0) for td in result.get('_manifest_tables', {}).values())
            result.pop('_manifest_tables', None)
            verification_ok = result.get('verification', {}).get('overall_pass', True)
            return {
                'success': verification_ok, 'format': 'zip', 'results': result,
                'total_inserted': total_rows,
                'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
        # JSON path
        try:
            backup_data = await asyncio.to_thread(json.loads, content)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail='备份文件格式无效（非 ZIP 亦非有效 JSON）') from None
        if 'tables' not in backup_data:
            raise HTTPException(status_code=400, detail='JSON 备份文件缺少 tables 字段')

        # 事务边界（docs/TRANSACTION_BOUNDARY_GUIDE.md §2.3）：端点层不再出现 raw commit/rollback。
        # 恢复路径仍要求「响应前提交」——提交失败必须让客户端拿到 500，而不是先收到成功再静默丢失，
        # 故用 db_transaction 而非依赖 get_async_db 的响应后提交。
        async with db_transaction(db, error_map={
            BackupError: _restore_error_to_http,
            ValueError: _restore_error_to_http,
        }):
            result = await backup_service.restore_legacy_json(backup_data, db)
        verification_ok = result.get('verification', {}).get('overall_pass', True)
        return {
            'success': verification_ok, 'format': 'json',
            'total_inserted': result['total_inserted'], 'results': result['results'],
            'errors': result['errors'], 'pre_restore_backup': pre_restore_info,
            'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    finally:
        await backup_service.release_restore_lock(lock_owner)


# ---------------------------------------------------------------------------
# POST /restore-by-name/{filename}
# ---------------------------------------------------------------------------
@router.post('/restore-by-name/{filename}', response_model=BackupImportResponse)
async def restore_server_backup(
    filename: str,
    confirm: bool = Query(False),
    confirm_sensitive: bool = Query(False, description='确认同时还原敏感配置文件（.env.production / jwt 密钥），默认跳过'),
    allow_missing_pre_restore_backup: bool = Query(
        False, description='安全备份失败时仍继续还原（无回滚点，慎用）',
    ),
    password: str | None = Body(None, embed=True, description='加密备份解密密码（H3：经 body 传递，避免进入访问日志/浏览器历史；为空时依次使用请求头/环境变量）'),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('restore_server_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """从服务器默认路径恢复指定备份文件"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = backup_service.BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    # P0-5: 与上传路径一致的大小上限，防超大文件整体读入内存
    try:
        if filepath.stat().st_size > backup_service.MAX_BACKUP_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)，请使用分片或异步方式',
            )
        # H5: 大文件读取为阻塞 IO，移入线程池避免卡住事件循环
        content = await asyncio.to_thread(filepath.read_bytes)
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=_sanitize_error(f'读取备份文件失败: {e}')) from e

    decrypt_password = _get_encryption_password(password, x_backup_password)

    # 2026-10-18 OCR 复评：格式识别必须在落安全备份与取恢复锁**之前**。
    # 旧顺序下坏文件/错密码会先触发一次全量安全备份再 400，且锁已拿到要占满 TTL。
    # sniff 解密后的 is_zip 必须用于分支——`.enc` 文件里也可能是 ZIP，
    # 继续走 json.loads 会把解密出的 ZIP 当 JSON 解析而 400。
    content, is_zip = await _sniff_server_backup_format(content, safe_name, decrypt_password)

    if is_zip:
        # P0-5: Redis 还原锁（旧实现此路径没有）
        zip_lock_owner = await _acquire_sync_restore_lock('sync_restore_by_name')
        try:
            # P0-5 + P1-9：两条路径都落安全备份，且移到取锁之后（并发时先 409）
            pre_restore_info = await _pre_restore_info_or_fail(db, allow_missing_pre_restore_backup)
            # 同 /import 的 zip 分支：提交点在策略层，此处只统一异常→HTTP 的映射
            try:
                result = await backup_service.restore_from_zip(
                    content, db,
                    decrypt_password=decrypt_password,
                    confirm_sensitive=confirm_sensitive,
                )
            except BackupError as e:
                raise HTTPException(status_code=500, detail=_sanitize_error(str(e))) from e
        finally:
            await backup_service.release_restore_lock(zip_lock_owner)
        result['pre_restore_backup'] = pre_restore_info
        total_rows = sum(td.get('rows', 0) for td in result.get('_manifest_tables', {}).values())
        result.pop('_manifest_tables', None)
        verification_ok = result.get('verification', {}).get('overall_pass', True)
        return {
            'success': verification_ok, 'format': 'zip', 'filename': safe_name,
            'results': result, 'total_inserted': total_rows,
            'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    # 2026-10-18 OCR 评审：非 zip 分支的 .json.enc 解密、.gz 解压已在入口 sniff 完成，
    # 此处 content 已是可直接 json.loads 的明文。
    # JSON path
    try:
        backup_data = await asyncio.to_thread(json.loads, content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail='备份文件格式无效') from None
    if 'tables' not in backup_data:
        raise HTTPException(status_code=400, detail='JSON 备份文件缺少 tables 字段')

    json_lock_owner = await _acquire_sync_restore_lock('sync_restore_by_name_json')
    try:
        pre_restore_info = await _pre_restore_info_or_fail(db, allow_missing_pre_restore_backup)
        # 同 /import：提交点归 db_transaction，异常回滚由它统一负责
        async with db_transaction(db, error_map={
            BackupError: _restore_error_to_http,
            ValueError: _restore_error_to_http,
        }):
            result = await backup_service.restore_legacy_json(backup_data, db)
    finally:
        await backup_service.release_restore_lock(json_lock_owner)
    verification_ok = result.get('verification', {}).get('overall_pass', True)
    return {
        'success': verification_ok, 'format': 'json', 'filename': safe_name,
        'total_inserted': result['total_inserted'], 'results': result['results'],
        'errors': result['errors'], 'pre_restore_backup': pre_restore_info,
        'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ---------------------------------------------------------------------------
# GET /progress/{task_id}
# ---------------------------------------------------------------------------
@router.get('/progress/{task_id}', response_model=BackupProgressOut)
async def get_restore_progress(
    task_id: str,
    user: User = Depends(require_backup_permission('get_restore_progress')),
):
    """查询异步任务进度"""
    from fastapi_app.core.backup_progress import get_progress as _get_progress
    progress = await _get_progress(task_id)
    if progress is None:
        raise HTTPException(status_code=404, detail='任务不存在或已过期')
    return success_response(**{**progress})


# ---------------------------------------------------------------------------
# POST /async-import
# ---------------------------------------------------------------------------
@router.post('/async-import', response_model=AsyncTaskResponse)
async def async_import_backup(
    file: UploadFile = File(...),
    confirm: bool = False,
    confirm_sensitive: bool = Query(False, description='确认同时还原敏感配置文件，默认跳过'),
    allow_missing_pre_restore_backup: bool = Query(
        False, description='安全备份失败时仍继续还原（无回滚点，慎用）',
    ),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('async_import_backup')),
):
    """异步恢复：从上传文件恢复

    解密密码仅通过 X-Backup-Password 请求头或环境变量提供（H3：multipart 端点
    无法安全混合 JSON body，且密码不进 URL query 避免落入访问日志/浏览器历史）。
    """
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    content, is_zip, filename = await _read_backup_file(file, _get_encryption_password(None, x_backup_password))
    decrypt_password = _get_encryption_password(None, x_backup_password)

    # 并发检查：避免同时启动多个恢复任务。委托共享助手区分「Redis 故障(503)」
    # 与「锁真实占用(409)」，并自愈崩溃残留的陈旧锁（同 actions._check_task_mutex）
    from fastapi_app.api.v1.endpoints.backup._mutex import ensure_restore_slot_free
    await ensure_restore_slot_free()

    from fastapi_app.core.backup_progress import create_progress, generate_task_id
    task_id = generate_task_id()
    await create_progress(task_id, 'file_import')
    # B1 修复：必须检查锁获取结果，失败时清理进度键并拒绝启动，消除
    # is_restore_in_progress 与 acquire 之间 TOCTOU 窗口内的并发还原
    if not await backup_service.acquire_restore_lock(task_id):
        await fail_progress_quietly(task_id)
        if await _redis_unavailable():
            raise HTTPException(status_code=503, detail='恢复锁服务暂时不可用，请稍后重试')
        raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')

    task = asyncio.create_task(_run_async_file_restore(
        task_id, content, is_zip, filename,
        confirm_sensitive=confirm_sensitive, decrypt_password=decrypt_password,
        allow_missing_pre_restore_backup=allow_missing_pre_restore_backup,
    ))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return success_response(task_id=task_id, message='恢复任务已启动')


# ---------------------------------------------------------------------------
# POST /async-restore-by-name/{filename}
# ---------------------------------------------------------------------------
@router.post('/async-restore-by-name/{filename}', response_model=AsyncTaskResponse)
async def async_restore_server_backup(
    filename: str,
    confirm: bool = Query(False),
    confirm_sensitive: bool = Query(False, description='确认同时还原敏感配置文件，默认跳过'),
    allow_missing_pre_restore_backup: bool = Query(
        False, description='安全备份失败时仍继续还原（无回滚点，慎用）',
    ),
    password: str | None = Body(None, embed=True, description='加密备份解密密码（H3：经 body 传递，避免进入访问日志/浏览器历史；为空时依次使用请求头/环境变量）'),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('async_restore_server_backup')),
):
    """异步恢复：从服务器文件恢复"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')

    # 并发检查（同 async_import_backup：区分 Redis 故障与真实占用 + 陈旧锁自愈）
    from fastapi_app.api.v1.endpoints.backup._mutex import ensure_restore_slot_free
    await ensure_restore_slot_free()
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = backup_service.BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    try:
        if filepath.stat().st_size > backup_service.MAX_BACKUP_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)',
            )
        # H5: 大文件读取为阻塞 IO，移入线程池避免卡住事件循环
        content = await asyncio.to_thread(filepath.read_bytes)
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=_sanitize_error(f'读取备份文件失败: {e}')) from e

    decrypt_password = _get_encryption_password(password, x_backup_password)

    # 2026-10-18 OCR 复评：格式识别（可能因缺密码/错密码/坏 gzip/未知格式抛 400）
    # 必须在取恢复锁之前完成。取锁后再抛会让 Redis 锁一直占到 1h TTL，
    # 后续每次恢复请求都被 409 拒绝。
    content, is_zip = await _sniff_server_backup_format(content, safe_name, decrypt_password)

    from fastapi_app.core.backup_progress import create_progress, generate_task_id
    task_id = generate_task_id()
    await create_progress(task_id, 'server_restore')
    # B1 修复：必须检查锁获取结果（同 async_import_backup）
    if not await backup_service.acquire_restore_lock(task_id):
        await fail_progress_quietly(task_id)
        if await _redis_unavailable():
            raise HTTPException(status_code=503, detail='恢复锁服务暂时不可用，请稍后重试')
        raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')

    task = asyncio.create_task(_run_async_file_restore(
        task_id, content, is_zip, safe_name,
        confirm_sensitive=confirm_sensitive, decrypt_password=decrypt_password,
        allow_missing_pre_restore_backup=allow_missing_pre_restore_backup,
    ))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return success_response(task_id=task_id, message='恢复任务已启动')


# ---------------------------------------------------------------------------
# 异步恢复后台任务
# ---------------------------------------------------------------------------
async def _report_restore_outcome(task_id: str, result: dict) -> None:
    """按库状态与校验结果上报异步恢复任务的终态。"""
    from fastapi_app.core.backup_progress import complete_progress, fail_progress

    if result.get('database', {}).get('status', '') == 'error':
        database = result.get('database', {})
        error_msg = database.get('error') or database.get('message') or '数据库恢复失败'
        await fail_progress(task_id, f'数据库恢复失败: {error_msg}')
        return

    verification = result.get('verification', {})
    if not verification.get('overall_pass', True):
        l1_summary = verification.get('l1_row_count', {}).get('summary', '')
        l2_summary = verification.get('l2_fingerprint', {}).get('summary', '')
        verify_err = f'数据验证未通过: {l1_summary}'
        if l2_summary:
            verify_err += f'; {l2_summary}'
        await fail_progress(task_id, verify_err)
        return

    await complete_progress(task_id, result)


async def _run_async_file_restore(
    task_id: str, content: bytes, is_zip: bool, filename: str,
    *, confirm_sensitive: bool = False, decrypt_password: str | None = None,
    allow_missing_pre_restore_backup: bool = False,
):
    """异步恢复后台执行"""
    from fastapi_app.core.backup_progress import fail_progress, update_progress
    from fastapi_app.core.database import get_async_db_context

    # B1 修复：锁续期 watchdog——还原超 TTL(3600s) 时锁会被 Redis 回收，
    # 每 10 分钟续期一次防止长任务锁丢失后被并发还原抢占
    async def _lock_watchdog():
        while True:
            await asyncio.sleep(600)
            if not await backup_service.renew_restore_lock(task_id):
                logger.warning(f'还原任务 {task_id} 恢复锁续期失败（锁已易主或 Redis 不可用）')

    watchdog = asyncio.create_task(_lock_watchdog())
    try:
        await update_progress(task_id, 'pre_backup', detail='准备恢复')
        pre_restore_info = None

        async with get_async_db_context() as db:
            try:
                await update_progress(task_id, 'pre_backup', 0.0, '创建安全备份')
                # 异步路径已持有还原锁，须跳过还原互斥检查，否则安全备份必然失败。
                # 闸门失败时本处无法向已返回的客户端抛 HTTP，由下面 `except HTTPException`
                # 转 fail_progress —— 与同步端点同一道闸，只是出口不同。
                pre_restore_info = await _pre_restore_info_or_fail(
                    db, allow_missing_pre_restore_backup, skip_restore_check=True,
                )
                await update_progress(task_id, 'pre_backup', 1.0, '安全备份完成')

                if is_zip:
                    result = await backup_service.restore_from_zip(
                        content, db,
                        decrypt_password=decrypt_password,
                        task_id=task_id,
                        confirm_sensitive=confirm_sensitive,
                    )
                else:
                    try:
                        backup_data = await asyncio.to_thread(json.loads, content)
                    except json.JSONDecodeError:
                        await fail_progress(task_id, '备份文件格式无效（非 ZIP 亦非有效 JSON）')
                        return
                    if 'tables' not in backup_data:
                        await fail_progress(task_id, 'JSON 备份文件缺少 tables 字段')
                        return
                    # JSON 恢复路径（Redis 还原锁已由入口端点获取，见 finally 统一释放）
                    await update_progress(task_id, 'restore_db', 0.0, '通过 JSON 恢复数据库')
                    result = await backup_service.restore_legacy_json(backup_data, db)

                result['pre_restore_backup'] = pre_restore_info
                result['restored_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                result['filename'] = filename
                result['format'] = 'zip' if is_zip else 'json'

                if is_zip:
                    manifest_tables = result.get('_manifest_tables', {})
                    total_rows = sum(td.get('rows', 0) for td in manifest_tables.values()) if manifest_tables else 0
                    result['total_inserted'] = total_rows
                    result.pop('_manifest_tables', None)

                await _report_restore_outcome(task_id, result)

            except HTTPException as e:
                await fail_progress(task_id, e.detail)
            except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
                # fail_progress 内部经 _sanitize_error 清洗（去除路径并截断），可安全写入 str(e)
                await fail_progress(task_id, str(e))
    except asyncio.CancelledError:
        # P1-10：停机/重启取消在跑任务，必须落失败终态——否则进度键停在中间态，
        # is_stale_restore_lock 判不了陈旧锁，还原锁要占满 TTL 才释放。
        logger.warning(f'异步恢复任务被取消（服务停止/重启）: {task_id}')
        try:
            await asyncio.shield(
                fail_progress(task_id, '恢复任务被中断（服务停止或重启），请检查数据后重试')
            )
        except Exception as e:  # defensive: 取消态写进度失败不得掩盖取消语义
            logger.error(f'取消态进度写入失败: {e}')
        raise
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error(f'异步恢复任务异常: {e}')
        await fail_progress(task_id, str(e))
    finally:
        watchdog.cancel()
        # 释放恢复锁（B1 修复：按持有者 task_id 释放，避免误删他人锁）
        await backup_service.release_restore_lock(task_id)


# ---------------------------------------------------------------------------
# POST /restore/plan  还原差异预览（只读，原型向导第 2 步数据源）
# ---------------------------------------------------------------------------
@router.post('/restore/plan', response_model=BackupRestorePlanOut)
async def restore_plan(
    payload: BackupRestorePlanRequest,
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('restore_plan')),
    db: AsyncSession = Depends(get_async_db),
):
    """还原差异预览：manifest 行数 vs 当前库实时 COUNT(*)。

    权限:backup_read。仅做只读探测，不触发任何写/还原。
    解密密码与其他还原端点同一条兜底链：body → X-Backup-Password 头 →
    环境变量 BACKUP_ENCRYPTION_PASSWORD —— 服务端自加密的包无需用户输密即可预览。
    """
    try:
        # Z05-R10：manifest 读取（含整包解密）是同步阻塞 IO，下沉线程池
        manifest = await asyncio.to_thread(
            restore_plan_service.read_manifest_from_backup,
            payload.filename,
            password=_get_encryption_password(payload.password, x_backup_password),
        )
    except restore_plan_service.EncryptedBackupError as e:
        # 三层兜底都拿不到密码（服务端未配置 BACKUP_ENCRYPTION_PASSWORD）才会走到这里：
        # 仍回 encrypted=True 让界面能区分「加密包解不开」与「文件损坏」
        return BackupRestorePlanOut(
            success=False, filename=payload.filename, encrypted=True, error=str(e),
        )
    except (FileNotFoundError, ValueError) as e:
        # 加密包解密失败（密码错/文件损坏）也要回 encrypted=True，界面据此区分「加密包解不开」与「文件损坏」
        return BackupRestorePlanOut(
            success=False, filename=payload.filename,
            encrypted=payload.filename.endswith('.enc'), error=str(e),
        )
    try:
        plan = await restore_plan_service.build_restore_plan(db, manifest)
    except Exception as e:  # broad-except: 预览失败返回 message，不中断请求
        logger.warning(f'还原差异预览失败: {e}')
        return BackupRestorePlanOut(success=False, filename=payload.filename, error=str(e))
    # manifest 固化发生在加密**之前**，其内没有 encrypted 键（恒 False）；.enc 后缀才是
    # 加密的权威信号——不覆盖的话加密包预览成功时会被误标为「明文包」
    plan.pop('encrypted', None)
    return BackupRestorePlanOut(
        success=True, filename=payload.filename,
        encrypted=payload.filename.endswith('.enc'), **plan,
    )

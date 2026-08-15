"""分块/合并功能。"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from ._constants import BACKUP_CHUNK_SIZE, BACKUP_MAX_CHUNKS
from .exceptions import BackupError

logger = logging.getLogger(__name__)


def split_backup_into_chunks(
    backup_bytes: bytes,
    chunk_size: int = BACKUP_CHUNK_SIZE,
    max_chunks: int = BACKUP_MAX_CHUNKS,
) -> list[tuple[int, bytes]]:
    """将备份数据分割为多个 chunk

    Args:
        backup_bytes: 备份数据字节
        chunk_size: 每个 chunk 的大小（字节）
        max_chunks: 最大 chunk 数量

    Returns:
        列表，每个元素为 (chunk_index, chunk_bytes)
    """
    total_size = len(backup_bytes)
    if total_size <= chunk_size:
        # 如果数据小于等于 chunk_size，直接返回单个 chunk
        return [(0, backup_bytes)]

    # 计算需要的 chunk 数量
    num_chunks = (total_size + chunk_size - 1) // chunk_size
    if num_chunks > max_chunks:
        raise BackupError(f"备份文件太大，需要 {num_chunks} 个 chunk，超过最大限制 {max_chunks}")

    chunks = []
    for i in range(num_chunks):
        start = i * chunk_size
        end = min((i + 1) * chunk_size, total_size)
        chunk_data = backup_bytes[start:end]
        chunks.append((i, chunk_data))

    logger.info(f"将备份文件分割为 {len(chunks)} 个 chunk，每个最大 {chunk_size} 字节")
    return chunks


def combine_backup_chunks(
    chunks: list[tuple[int, bytes]],
    total_size: int | None = None,
) -> bytes:
    """将多个 chunk 合并为完整的备份数据

    Args:
        chunks: chunk 列表，每个元素为 (chunk_index, chunk_bytes)
        total_size: 预期的总大小，用于验证

    Returns:
        合并后的字节数据
    """
    if not chunks:
        raise BackupError("没有提供任何 chunk")

    # 按索引排序
    chunks.sort(key=lambda x: x[0])

    # 验证索引连续性
    expected_index = 0
    for chunk_index, chunk_data in chunks:
        if chunk_index != expected_index:
            raise BackupError(f"Chunk 索引不连续，期望 {expected_index}，实际 {chunk_index}")
        expected_index += 1

    # 合并数据
    combined = b''.join(chunk_data for _, chunk_data in chunks)

    # 验证总大小
    if total_size is not None and len(combined) != total_size:
        raise BackupError(f"合并后大小不匹配，期望 {total_size} 字节，实际 {len(combined)} 字节")

    logger.info(f"成功合并 {len(chunks)} 个 chunk，总大小 {len(combined)} 字节")
    return combined


async def create_backup_chunks(
    db,
    user,
    remark: str = '',
    chunk_size: int = BACKUP_CHUNK_SIZE,
    max_chunks: int = BACKUP_MAX_CHUNKS,
    use_snapshot: bool = True,
    encrypt_password: str | bytearray | None = None,
) -> list[dict]:
    """创建备份并将其分割为多个 chunk

    Args:
        db: 数据库会话
        user: 用户信息
        remark: 备份备注
        chunk_size: 每个 chunk 的大小（字节）
        max_chunks: 最大 chunk 数量
        use_snapshot: 是否使用数据库快照
        encrypt_password: 加密密码

    Returns:
        包含 chunk 信息的字典列表
    """
    from .orchestration import create_full_backup

    # 创建备份
    backup_bytes, manifest = await create_full_backup(
        db=db,
        user=user,
        remark=remark,
        encrypt_password=encrypt_password,
        use_snapshot=use_snapshot,
    )

    # 分割为 chunk
    chunks = split_backup_into_chunks(backup_bytes, chunk_size, max_chunks)

    # 为每个 chunk 创建元数据
    chunk_metadata = []
    total_chunks = len(chunks)
    backup_id = datetime.now().strftime('%Y%m%d_%H%M%S')

    for chunk_index, chunk_data in chunks:
        chunk_info = {
            'backup_id': backup_id,
            'chunk_index': chunk_index,
            'total_chunks': total_chunks,
            'chunk_size': len(chunk_data),
            'total_size': len(backup_bytes),
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'checksum': hashlib.sha256(chunk_data).hexdigest(),
            'manifest': manifest if chunk_index == 0 else None,  # 只在第一个 chunk 中包含完整 manifest
        }

        # 如果是第一个 chunk，添加额外的元数据
        if chunk_index == 0:
            chunk_info['is_first_chunk'] = True
            chunk_info['full_manifest'] = manifest
        else:
            chunk_info['is_first_chunk'] = False

        chunk_metadata.append({
            'metadata': chunk_info,
            'data': chunk_data,
        })

    logger.info(f"备份分割完成: {total_chunks} 个 chunk，总大小 {len(backup_bytes)} 字节")
    return chunk_metadata


async def restore_from_chunks(
    chunks_metadata: list[dict],
    db,
    decrypt_password: str | bytearray | None = None,
    task_id: str | None = None,
) -> dict:
    """从多个 chunk 恢复备份

    Args:
        chunks_metadata: chunk 元数据列表，每个元素包含 'metadata' 和 'data'
        db: 数据库会话
        decrypt_password: 解密密码
        task_id: 任务 ID，用于进度报告

    Returns:
        恢复结果
    """
    from .restore import restore_from_zip

    if not chunks_metadata:
        raise BackupError("没有提供任何 chunk")

    # 验证所有 chunk 属于同一个备份
    backup_ids = set(chunk['metadata'].get('backup_id') for chunk in chunks_metadata)
    if len(backup_ids) != 1:
        raise BackupError(f"chunk 属于不同的备份: {backup_ids}")

    backup_id = next(iter(backup_ids))

    # 按索引排序
    chunks_metadata.sort(key=lambda x: x['metadata'].get('chunk_index', 0))

    # 验证 chunk 连续性
    expected_index = 0
    total_chunks = chunks_metadata[0]['metadata'].get('total_chunks')
    total_size = chunks_metadata[0]['metadata'].get('total_size')

    for chunk in chunks_metadata:
        metadata = chunk['metadata']
        chunk_index = metadata.get('chunk_index')

        if chunk_index != expected_index:
            raise BackupError(f"Chunk 索引不连续，期望 {expected_index}，实际 {chunk_index}")

        # 验证 checksum
        expected_checksum = metadata.get('checksum')
        actual_checksum = hashlib.sha256(chunk['data']).hexdigest()
        if expected_checksum != actual_checksum:
            raise BackupError(f"Chunk {chunk_index} 校验和不匹配")

        expected_index += 1

    # 验证总数
    if len(chunks_metadata) != total_chunks:
        raise BackupError(f"Chunk 数量不匹配，期望 {total_chunks}，实际 {len(chunks_metadata)}")

    # 合并数据
    chunk_data_list = [chunk['data'] for chunk in chunks_metadata]
    backup_bytes = b''.join(chunk_data_list)

    # 验证总大小
    if len(backup_bytes) != total_size:
        raise BackupError(f"合并后大小不匹配，期望 {total_size} 字节，实际 {len(backup_bytes)} 字节")

    logger.info(f"成功验证并合并 {len(chunks_metadata)} 个 chunk，备份 ID: {backup_id}")

    # 恢复备份
    return await restore_from_zip(
        zip_bytes=backup_bytes,
        db=db,
        decrypt_password=decrypt_password,
        task_id=task_id,
    )
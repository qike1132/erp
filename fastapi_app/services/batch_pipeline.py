"""
批量导入统一 Pipeline 基类

为 batch.py 中的 6 个 150+ 行导入函数提供统一抽象。
新增批量导入功能应继承此基类实现 parse → validate → persist 三阶段。
现有函数可逐步迁移。

用法示例:
    class OrderImportPipeline(BatchImportPipeline[Order]):
        async def parse(self, file, db):
            ...
        async def validate(self, raw_data, db):
            ...
        async def persist(self, validated_data, db, user):
            ...
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TypeVar

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 批量导入文件大小上限（5MB），防止OOM攻击
MAX_BATCH_UPLOAD_SIZE = 5 * 1024 * 1024


@dataclass
class BatchImportResult:
    """批量导入结果"""
    success_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_ids: list[int] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.success_count + self.error_count

    def to_dict(self) -> dict:
        return {
            "success_count": self.success_count,
            "error_count": self.error_count,
            "total": self.total,
            "errors": self.errors[:50],
            "warnings": self.warnings[:50],
        }


class BatchImportPipeline[T](ABC):
    """批量导入三阶段 Pipeline 基类"""

    async def execute(
        self,
        file: UploadFile,
        db: AsyncSession,
        user: User,
    ) -> BatchImportResult:
        """执行完整的导入管道: parse → validate → persist"""
        result = BatchImportResult()

        # 1. 文件大小检查
        content = await file.read()
        if len(content) > MAX_BATCH_UPLOAD_SIZE:
            result.errors.append(f"文件大小超过限制({MAX_BATCH_UPLOAD_SIZE // 1024 // 1024}MB)")
            result.error_count = 1
            return result

        try:
            # 2. 解析
            raw_data = await self.parse(content, db)
            if not raw_data:
                result.warnings.append("文件中未找到有效数据")
                return result

            # 3. 校验
            validated_data, validation_errors = await self.validate(raw_data, db)
            result.errors.extend(validation_errors)
            result.error_count = len(validation_errors)

            if not validated_data:
                return result

            # 4. 持久化
            created_ids = await self.persist(validated_data, db, user)
            result.success_count = len(created_ids)
            result.created_ids = created_ids

            await db.commit()
        except (ValueError, TypeError, OSError) as e:
            await db.rollback()
            logger.exception(f"批量导入失败: {e}")
            result.errors.append(f"导入失败: {str(e)}")
            result.error_count += 1

        return result

    @abstractmethod
    async def parse(self, content: bytes, db: AsyncSession) -> list[dict]:
        """解析文件内容为原始数据列表"""
        ...

    @abstractmethod
    async def validate(
        self, raw_data: list[dict], db: AsyncSession
    ) -> tuple[list[dict], list[str]]:
        """校验原始数据，返回 (有效数据, 错误列表)"""
        ...

    @abstractmethod
    async def persist(
        self, validated_data: list[dict], db: AsyncSession, user: User
    ) -> list[int]:
        """持久化有效数据，返回创建的 ID 列表"""
        ...

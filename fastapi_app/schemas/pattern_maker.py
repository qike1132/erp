"""版师 Pydantic Schemas

对应版师模块的列表查询与新增接口。
保持极简：仅列表查询 + 新增。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PatternMakerItem(BaseModel):
    """版师条目"""
    id: int
    name: str


class PatternMakerListResponse(BaseModel):
    """版师列表响应"""
    success: bool = True
    items: list[PatternMakerItem] = Field(default_factory=list)


class PatternMakerCreateRequest(BaseModel):
    """新增版师请求"""
    name: str = Field(..., min_length=1, max_length=100, description='版师姓名')


class PatternMakerActionResponse(BaseModel):
    """版师操作响应"""
    success: bool = True
    message: str = '操作成功'
    id: int | None = None

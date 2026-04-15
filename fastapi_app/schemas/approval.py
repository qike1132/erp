"""审批管理相关 Schema"""
from pydantic import BaseModel, Field


class ApprovalActionRequest(BaseModel):
    reason: str | None = Field(default=None, description="拒绝原因")


class ApprovalListResponse(BaseModel):
    success: bool = True
    data: list[dict]
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0


class ApprovalDetailResponse(BaseModel):
    success: bool = True
    data: dict


class ApprovalActionResponse(BaseModel):
    success: bool = True
    message: str


class ApprovalPendingCountResponse(BaseModel):
    success: bool = True
    count: int = 0

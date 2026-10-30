"""审批管理相关 Schema"""
from pydantic import BaseModel, Field


class ApprovalActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500, description="拒绝原因")


class ApprovalItemSchema(BaseModel):
    id: int
    order_id: int
    order_no: str | None = None
    requester_id: int
    requester_name: str | None = None
    operation_type: str
    operation_type_display: str
    operation_data: str | None = None
    status: str
    status_display: str
    request_time: str | None = None
    approver_id: int | None = None
    approver_name: str | None = None
    approval_time: str | None = None
    rejection_reason: str | None = None
    lock_time: str | None = None


class ApprovalLogItemSchema(BaseModel):
    id: int
    approval_request_id: int
    action: str
    action_display: str
    actor_id: int | None = None
    actor_name: str | None = None
    action_time: str | None = None
    details: str | None = None


class ApprovalListResponse(BaseModel):
    success: bool = True
    data: list[ApprovalItemSchema]
    total: int = 0
    pages: int = 0
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

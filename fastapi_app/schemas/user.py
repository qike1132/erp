"""用户管理相关 Schema"""
from pydantic import BaseModel, Field, field_validator


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")
    is_super: bool = Field(default=False, description="是否超级用户")

    @field_validator('password')
    @classmethod
    def validate_password_complexity(cls, v: str):
        from utils.password_validator import PasswordValidator
        is_valid, error_msg = PasswordValidator.validate(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128, description="密码（不修改则不传）")
    is_super: bool | None = Field(default=None, description="是否超级用户")

    @field_validator('password')
    @classmethod
    def validate_password_complexity(cls, v: str | None):
        if v is None:
            return v
        from utils.password_validator import PasswordValidator
        is_valid, error_msg = PasswordValidator.validate(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v


class UserPermissionUpdate(BaseModel):
    permission_ids: list[int] = Field(default_factory=list, description="权限ID列表")


class UserResponse(BaseModel):
    id: int
    username: str
    is_super: bool
    status: bool
    create_time: str | None = None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    success: bool = True
    users: list[UserResponse]
    total: int = 0


class UserActionResponse(BaseModel):
    success: bool = True
    message: str


class PermissionResponse(BaseModel):
    id: int
    name: str
    code: str
    parent_id: int | None = None
    icon: str | None = None
    url: str | None = None
    section: str | None = None
    section_name: str | None = None
    sort_order: int = 0
    is_nav: bool = True
    children: list["PermissionResponse"] = Field(default_factory=list)

    class Config:
        from_attributes = True


class UserPermissionResponse(BaseModel):
    success: bool = True
    user_id: int
    user_permission_ids: list[int]
    permissions: list[PermissionResponse]

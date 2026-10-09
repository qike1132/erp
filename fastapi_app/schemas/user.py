"""用户管理相关 Schema"""
from pydantic import BaseModel, Field, field_validator

from fastapi_app.schemas.product import _validate_factory
from utils.password_validator import PasswordValidator

# 用户所属部门（组织部门）。与 core/production_scope.py 的生产报表部门
# （充棉部/手工部/包装部）无关，勿混用。
VALID_DEPARTMENTS: tuple[str, ...] = ('生产部', '仓库', '业务部', '采购部')


def _validate_department(v: str | None) -> str | None:
    """校验部门值必须属于允许的选项集合，允许为空"""
    if v and v not in VALID_DEPARTMENTS:
        raise ValueError(f'部门值无效，必须是 {"/".join(VALID_DEPARTMENTS)} 之一')
    return v


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=50, description="用户名")
    password: str = Field(
        ...,
        min_length=PasswordValidator.MIN_LENGTH,
        max_length=PasswordValidator.MAX_LENGTH,
        description="密码",
    )
    is_super: bool = Field(default=False, description="是否超级用户")
    factory: str | None = Field(default=None, max_length=20, description="所属工厂：东莞/湖北/NULL")
    department: str | None = Field(default=None, max_length=20, description="所属部门：生产部/仓库/业务部/采购部/NULL")

    @field_validator('password')
    @classmethod
    def validate_password_complexity(cls, v: str):
        is_valid, error_msg = PasswordValidator.validate(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v

    @field_validator('factory')
    @classmethod
    def validate_factory(cls, v: str | None) -> str | None:
        return _validate_factory(v)

    @field_validator('department')
    @classmethod
    def validate_department(cls, v: str | None) -> str | None:
        return _validate_department(v)


class UserUpdate(BaseModel):
    password: str | None = Field(
        default=None,
        min_length=PasswordValidator.MIN_LENGTH,
        max_length=PasswordValidator.MAX_LENGTH,
        description="密码（不修改则不传）",
    )
    is_super: bool | None = Field(default=None, description="是否超级用户")
    factory: str | None = Field(default=None, max_length=20, description="所属工厂：东莞/湖北/NULL（传空字符串表示清除）")
    department: str | None = Field(default=None, max_length=20, description="所属部门：生产部/仓库/业务部/采购部/NULL（传空字符串表示清除）")

    @field_validator('password')
    @classmethod
    def validate_password_complexity(cls, v: str | None):
        if v is None:
            return v
        is_valid, error_msg = PasswordValidator.validate(v)
        if not is_valid:
            raise ValueError(error_msg)
        return v

    @field_validator('factory')
    @classmethod
    def validate_factory(cls, v: str | None) -> str | None:
        return _validate_factory(v)

    @field_validator('department')
    @classmethod
    def validate_department(cls, v: str | None) -> str | None:
        return _validate_department(v)


class UserPermissionUpdate(BaseModel):
    permission_ids: list[int] = Field(default_factory=list, description="权限ID列表")


class UserResponse(BaseModel):
    id: int
    username: str
    is_super: bool
    status: bool
    factory: str | None = None
    department: str | None = None
    create_time: str | None = None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    success: bool = True
    users: list[UserResponse]
    total: int = 0
    page: int = 1
    per_page: int = 15


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

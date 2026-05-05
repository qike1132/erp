"""应用自定义异常"""


class AppError(Exception):
    """业务异常基类"""

    def __init__(self, message: str = "操作失败", code: str = "APP_ERROR", status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)

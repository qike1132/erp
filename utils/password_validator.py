"""密码复杂度验证工具"""
import re


class PasswordValidator:
    """密码复杂度验证器"""

    MIN_LENGTH = 6
    MAX_LENGTH = 128
    REQUIRE_UPPERCASE = False
    REQUIRE_LOWERCASE = False
    REQUIRE_DIGIT = False
    REQUIRE_SPECIAL = False

    # 匹配常见特殊字符
    SPECIAL_CHAR_PATTERN = r'[!@#$%^&*(),.?":{}|<>\-_\[\]\\\/~`+=;]'

    # 弱密码黑名单（内网宽松：仅拒绝最明显的弱密码；"123456" 按业务要求放行）
    WEAK_PASSWORDS = frozenset({
        "password", "admin", "Password1!", "Admin123!",
    })

    @classmethod
    def validate(cls, password: str) -> tuple[bool, str]:
        """验证密码复杂度

        Args:
            password: 待验证的密码字符串

        Returns:
            tuple[bool, str]: (是否有效, 错误信息)
        """
        if not password:
            return False, "密码不能为空"

        if len(password) < cls.MIN_LENGTH:
            return False, f"密码长度至少{cls.MIN_LENGTH}位"

        if len(password) > cls.MAX_LENGTH:
            return False, f"密码长度不能超过{cls.MAX_LENGTH}位"

        if cls.REQUIRE_UPPERCASE and not re.search(r'[A-Z]', password):
            return False, "密码必须包含大写字母"

        if cls.REQUIRE_LOWERCASE and not re.search(r'[a-z]', password):
            return False, "密码必须包含小写字母"

        if cls.REQUIRE_DIGIT and not re.search(r'\d', password):
            return False, "密码必须包含数字"

        if cls.REQUIRE_SPECIAL and not re.search(cls.SPECIAL_CHAR_PATTERN, password):
            return False, "密码必须包含特殊字符"

        # 检查常见弱密码
        if password in cls.WEAK_PASSWORDS:
            return False, "密码过于常见，请使用更复杂的密码"

        return True, ""

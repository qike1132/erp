"""密码复杂度验证工具"""
import re


class PasswordValidator:
    """密码复杂度验证器"""

    MIN_LENGTH = 8
    MAX_LENGTH = 128
    REQUIRE_UPPERCASE = True
    REQUIRE_LOWERCASE = True
    REQUIRE_DIGIT = True
    REQUIRE_SPECIAL = True

    # 匹配常见特殊字符
    SPECIAL_CHAR_PATTERN = r'[!@#$%^&*(),.?":{}|<>\-_\[\]\\\/~`+=;]'

    # 常见弱密码黑名单（即使满足复杂度规则也应拒绝）
    WEAK_PASSWORDS = frozenset({
        "Password1!", "Password12!", "Password123!", "Password1234!",
        "Admin123!", "Admin1234!", "Administrator1!",
        "Qwerty123!", "Qwerty1!", "Qwerty12!",
        "Abc12345!", "Abcd1234!",
        "Aa123456!", "Aa1234567!",
        "P@ssw0rd!", "P@ssword1!", "P@ss1234!",
        "Passw0rd!", "Passw0rd1!",
        "Welcome1!", "Welcome123!",
        "Changeme1!", "Changeme123!",
        "Test1234!", "Test12345!",
        "Root1234!", "Root12345!",
        "User1234!", "User12345!",
    })

    # 连续重复字符模式（3个或以上相同字符）
    REPEAT_PATTERN = re.compile(r'(.)\1{2,}')
    # 键盘序列
    KEYBOARD_SEQUENCES = (
        "qwertyuiop", "asdfghjkl", "zxcvbnm",
        "1234567890", "qwerty123",
    )

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

        # 检查连续重复字符（如 "aaabbb"）
        if cls.REPEAT_PATTERN.search(password):
            return False, "密码不能包含3个或以上连续重复字符"

        # 检查键盘序列
        lower_pwd = password.lower()
        for seq in cls.KEYBOARD_SEQUENCES:
            for i in range(len(seq) - 3):
                if seq[i:i+4] in lower_pwd:
                    return False, "密码不能包含键盘序列字符"

        return True, ""

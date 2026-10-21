"""scripts/scan_secrets.py 自测。

存在理由
--------
`.githooks/pre-commit` 第 2 层做了密钥扫描，但**本地 hook 可被 `git commit --no-verify`
绕过**（hook 头部自述），因此 CI 侧必须有第二道扫描。本文件把该扫描器的分类能力钉住：
一旦规则被改松或路径漏扫，CI 会给出**假绿**——比没有扫描更危险。

规则语义与 `.githooks/pre-commit` 第 2 层一致，并复用 scripts/_selftest_hook.py 的
同一套镜像规则（避免出现第三份正则）。因此本文件的用例与 _selftest_hook 的
CASES / SECRET_CASES 保持同样的期望。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.scan_secrets import (
    _display_reason,
    content_scan_applies,
    content_secret_reason,
    dangerous_path_reason,
    load_allowlist,
    scan_tracked,
)


class TestDangerousPath:
    """第 1 层镜像：危险路径一律拒绝入库。"""

    @pytest.mark.parametrize(
        'path',
        [
            'config/jwt/private.pem',
            'android-app/release.keystore',
            'certs/server.key',
            'deploy/id_rsa',
            'cert.p12',
            '.env',
            '.env.production',
            '.env.local',
            'docs/ui-redesign/v4/_edge_profile_ov/Login Data',
            'chrome_profile_x/Cookies',
            'db/main.db-journal',
            # 2026-09-17 的凭据泄漏事故正发生在 docs/ 下 —— 这里**刻意不豁免**私钥类文件，
            # 否则与内容层的 docs/ 豁免叠加会形成双层盲区。
            'docs/leaked.pem',
            'docs/keys/id_rsa',
            'docs/plans/service.key',
        ],
    )
    def test_blocks_sensitive_paths(self, path: str) -> None:
        assert dangerous_path_reason(path) is not None, f'{path} 应被拒绝'

    @pytest.mark.parametrize(
        'path',
        [
            '.env.example',
            '.env.production.example',
            'frontend-vite/.env.example',
            'docs/runbooks/service-lifecycle.md',
            'fastapi_app/main.py',
            'frontend-vite/vite.config.ts',
            'config/jwt/README.md',
        ],
    )
    def test_allows_ordinary_and_template_paths(self, path: str) -> None:
        assert dangerous_path_reason(path) is None, f'{path} 不应被拒绝'


class TestContentRules:
    """第 2 层镜像：真实凭据必须命中，表达式/占位符不得误报。"""

    def test_private_key_header_detected(self) -> None:
        assert content_secret_reason('-----BEGIN RSA PRIVATE KEY-----', require_quoted_rhs=False)

    def test_aws_access_key_detected(self) -> None:
        assert content_secret_reason('aws_key = AKIAIOSFODNN7EXAMPLE', require_quoted_rhs=False)

    def test_github_token_detected(self) -> None:
        assert content_secret_reason('token = ghp_' + 'a' * 36, require_quoted_rhs=False)

    def test_hardcoded_python_literal_detected(self) -> None:
        assert content_secret_reason('    password = "hunter2secret123"', require_quoted_rhs=True)

    def test_yaml_bare_value_detected(self) -> None:
        # 非 .py 不受「右值必须带引号」收窄影响：不带引号就是字面量
        assert content_secret_reason('  POSTGRES_PASSWORD: erp_test_pass', require_quoted_rhs=False)

    def test_python_attribute_read_not_flagged(self) -> None:
        # ④ 层核心：.py 中不带引号的右值是表达式，不是硬编码
        assert content_secret_reason('    password = data.password', require_quoted_rhs=True) is None

    def test_python_variable_passthrough_not_flagged(self) -> None:
        assert content_secret_reason('        decrypt_password=decrypt_password,', require_quoted_rhs=True) is None

    def test_placeholder_not_flagged(self) -> None:
        assert content_secret_reason('    password = "<your-password>"', require_quoted_rhs=True) is None

    def test_ordinary_code_not_flagged(self) -> None:
        assert content_secret_reason('    result = compute_total(rows)', require_quoted_rhs=True) is None

    def test_inline_suppression_skips_only_that_line(self) -> None:
        suppressed = 'password = "hunter2secret123"  # secret-scan:allow'
        assert content_secret_reason(suppressed, require_quoted_rhs=True) is None

        # 关键：豁免是**行级**的，同一文件里未标注的行仍必须被检出
        mixed = 'password = "hunter2secret123"  # secret-scan:allow\npassword = "another1234567890"'
        assert content_secret_reason(mixed, require_quoted_rhs=True) is not None

    def test_next_line_suppression(self) -> None:
        # 供 HTML/Vue 模板使用（注释不能写在标签属性列表里）
        text = '<!-- secret-scan:allow-next-line -->\nv-model:show-password="showPassword"'
        assert content_secret_reason(text, require_quoted_rhs=True) is None

        # 只豁免紧邻的一行
        text2 = (
            '<!-- secret-scan:allow-next-line -->\n'
            'v-model:show-password="showPassword"\n'
            'password = "another1234567890"'
        )
        assert content_secret_reason(text2, require_quoted_rhs=True) is not None


class TestContentScanScope:
    """内容层的作用域：解释型语言的「右值必须带引号」+ 文档/测试夹具免扫。"""

    def test_ts_object_property_variable_not_flagged(self) -> None:
        # 实测误报：login/backup 前端把变量塞进请求体，不是硬编码
        assert content_secret_reason('  password: form.password,', require_quoted_rhs=True) is None

    def test_ts_boolean_toggle_not_flagged(self) -> None:
        # 实测误报：showPassword = !showPassword（`!showPassword` 恰好 ≥12 字符）
        assert content_secret_reason("  @click=\"showPassword = !showPassword\"", require_quoted_rhs=True) is None

    def test_ts_hardcoded_literal_still_flagged(self) -> None:
        assert content_secret_reason('  password: "hunter2secret123",', require_quoted_rhs=True)

    @pytest.mark.parametrize(
        'rel',
        ['tests/x.py', 'fastapi_app/tests/x.py', 'docs/a.md'],
    )
    def test_content_scan_skipped_for_tests_and_docs(self, rel: str) -> None:
        assert content_scan_applies(rel) is False

    @pytest.mark.parametrize(
        'rel',
        [
            'fastapi_app/main.py',
            'frontend-vite/src/views/login/useLogin.ts',
            'scripts/tool.py',
            # 以下三处**刻意不豁免**：实测这些目录的内容命中全来自 .md（已由后缀豁免），
            # 继续保留前缀豁免等于「今天零收益、未来留洞」。
            'backups/db_dump.sql',
            '.archive/old/a.py',
            'deliverables/x.txt',
            # docs/ 整目录豁免已于 F3-4 收窄：只有 .md 走后缀豁免，docs 下的
            # .py/.sql/.json 照常扫描（70 个受控文件曾是盲区）。
            'docs/plan.py',
        ],
    )
    def test_content_scan_applies_outside_tests_and_docs(self, rel: str) -> None:
        assert content_scan_applies(rel) is True


class TestScanTracked:
    """整仓扫描：当前受版本控制的文件里不得有任何凭据命中。"""

    def test_repo_has_no_tracked_secrets(self, project_root: Path) -> None:
        findings = scan_tracked(project_root, allow_patterns=load_allowlist(project_root))
        assert findings == [], (
            '受版本控制的文件中检出疑似凭据（若为脱敏测试夹具，请加入 .githooks/allowlist.txt）：\n'
            + '\n'.join(f'  ✗ {p} —— {r}' for p, r in findings)
        )


class TestDisplayReason:
    """CI 日志里的命中原因必须收敛到固定文案。

    这是 CodeQL `py/clear-text-logging-sensitive-data` 误报的处置：reason 本就是常量
    文案，但把「读过文件文本的函数」的返回值直接打印，静态分析无法区分。更实际的
    价值是——将来若有人把命中内容塞进 reason，也不会被原样打进 CI 日志。
    """

    def test_known_reason_is_echoed(self) -> None:
        assert _display_reason('私钥/证书文件') == '私钥/证书文件'

    def test_unknown_reason_is_generalized_not_echoed(self) -> None:
        """关键契约：未知原因一律泛化，绝不回显原值（原值可能正是凭据本身）。"""
        assert _display_reason('AKIAIOSFODNN7EXAMPLE') == '命中疑似凭据'


class TestAllowlist:
    def test_loads_and_strips_comments(self, tmp_path: Path) -> None:
        f = tmp_path / '.githooks' / 'allowlist.txt'
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('# 注释\n\ndocs/**\n  scripts/fixtures/*  # 行尾注释\n', encoding='utf-8')

        patterns = load_allowlist(tmp_path)

        assert 'docs/**' in patterns
        assert 'scripts/fixtures/*' in patterns
        assert all(not p.startswith('#') for p in patterns)

"""`scripts/review_packet.py` 的风险规则单测。

为什么要有：这些规则决定「评审者先看哪里」，误报会让合规动作被拦
（例如同步 `.env.example` 被判成凭据泄露），漏报则等于没有防线。
纯函数、不碰 git、不连库。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import review_packet as rp


def _risks(files: list[rp.ChangedFile], added: dict[str, list[str]]) -> list[rp.Risk]:
    return rp.detect_risks(files, added, "main", "HEAD", 0)


class TestSensitivePaths:
    def test_env_example_is_not_sensitive(self) -> None:
        # 合规动作：env_drift 门禁要求同步模板，不能反被判成凭据泄露
        assert rp.is_sensitive(".env.example") is False

    def test_real_env_files_are_sensitive(self) -> None:
        assert rp.is_sensitive(".env") is True
        assert rp.is_sensitive(".env.production") is True

    def test_credentials_and_keys_are_sensitive(self) -> None:
        assert rp.is_sensitive("_ops/credentials/db.txt") is True
        assert rp.is_sensitive("config/pgbouncer/userlist.txt") is True
        assert rp.is_sensitive("deploy/cert.pem") is True
        assert rp.is_sensitive("docs/notes.md") is False


class TestContentScope:
    def test_only_code_files_feed_content_rules(self) -> None:
        assert rp.is_code("fastapi_app/services/x.py") is True
        assert rp.is_code("frontend-vite/src/a.vue") is True
        assert rp.is_code("start.py") is True
        assert rp.is_code("docs/devlog.md") is False
        assert rp.is_code("mockups/index.html") is False
        assert rp.is_code("scripts/review_packet.py") is False
        assert rp.is_code("tests/test_x.py") is False

    def test_markdown_prose_does_not_trigger_code_rules(self) -> None:
        files = [rp.ChangedFile("M", "docs/devlog.md", added=1)]
        risks = _risks(files, {"docs/devlog.md": ["修复了 datetime.now() 与 except Exception 的旧例"]})
        titles = " ".join(risk.title for risk in risks)
        assert "datetime" not in titles
        assert "宽泛" not in titles

    def test_test_fixtures_do_not_trigger_suppression_rules(self) -> None:
        # 本仓实测：单测夹具里的抑制标记字符串曾让评审包报「新增 1 处 noqa 抑制」
        files = [rp.ChangedFile("M", "tests/test_x.py", added=1)]
        risks = _risks(files, {"tests/test_x.py": ['x = ["y = 1  # nosec B105"]']})
        assert not any("nosec" in risk.title for risk in risks)

    def test_secret_scan_allow_ignores_markdown_but_flags_config(self) -> None:
        md = _risks(
            [rp.ChangedFile("M", "docs/a.md", added=1)],
            {"docs/a.md": ["示例：secret-scan:allow 标记"]},
        )
        assert not any("secret-scan:allow" in risk.title for risk in md)
        yml = _risks(
            [rp.ChangedFile("M", ".github/workflows/ci.yml", added=1)],
            {".github/workflows/ci.yml": ["  DB_PASSWORD: x  # secret-scan:allow CI 测试口令"]},
        )
        assert any("secret-scan:allow" in risk.title for risk in yml)

    def test_comment_only_lines_and_self_definition_are_not_suppression_sites(self) -> None:
        # 纯注释里描述标记、以及规则定义文件自身的正则字面量，都不是人肉核验过的例外
        assert rp.is_suppression_site("scripts/review_packet.py", "x = 1  # secret-scan:allow") is False
        assert rp.is_suppression_site("fastapi_app/a.py", "# 说明：secret-scan:allow 的用法") is False
        assert rp.is_suppression_site("fastapi_app/a.py", "PASSWORD = 'x'  # secret-scan:allow 测试夹具") is True


class TestNoTestRisk:
    def test_business_code_without_tests_is_high(self) -> None:
        files = [rp.ChangedFile("M", "fastapi_app/services/order_service.py", added=5)]
        risks = _risks(files, {})
        assert any(risk.level == "H" and "业务代码" in risk.title for risk in risks)

    def test_config_only_is_medium_not_high(self) -> None:
        files = [rp.ChangedFile("M", "config/nginx-windows.conf", added=3)]
        risks = _risks(files, {})
        assert any(risk.level == "M" and "配置/运维/脚本" in risk.title for risk in risks)
        assert not any("业务代码" in risk.title for risk in risks)

    def test_doc_assets_do_not_require_tests(self) -> None:
        files = [rp.ChangedFile("M", "mockups/index.html", added=20)]
        risks = _risks(files, {})
        assert not any("测试" in risk.title for risk in risks)


class TestHighRiskRules:
    def test_migration_change_is_high(self) -> None:
        files = [rp.ChangedFile("M", "migrations/versions/999_x.py", added=10)]
        risks = _risks(files, {"migrations/versions/999_x.py": ["op.drop_column('t', 'c')"]})
        assert any(risk.level == "H" and "迁移" in risk.title for risk in risks)

    def test_binding_all_interfaces_is_blocker(self) -> None:
        files = [rp.ChangedFile("M", "fastapi_app/main.py", added=1)]
        risks = _risks(files, {"fastapi_app/main.py": ["uvicorn.run(app, host='0.0.0.0')"]})
        assert any(risk.level == "B" and "0.0.0.0" in risk.title for risk in risks)

    def test_suppression_in_code_is_flagged(self) -> None:
        files = [rp.ChangedFile("M", "fastapi_app/services/x.py", added=1)]
        risks = _risks(files, {"fastapi_app/services/x.py": ["x = 1  # noqa"]})
        assert any("noqa" in risk.title for risk in risks)

    def test_naive_datetime_is_flagged(self) -> None:
        files = [rp.ChangedFile("M", "fastapi_app/services/x.py", added=1)]
        risks = _risks(files, {"fastapi_app/services/x.py": ["ts = datetime.now()"]})
        assert any("datetime" in risk.title for risk in risks)


class TestDiffParsing:
    def test_rename_target_forms(self) -> None:
        assert rp.rename_target("dir/{old => new}/file.py") == "dir/new/file.py"
        assert rp.rename_target("old.py => new.py") == "new.py"

    def test_name_status_parsing(self) -> None:
        parsed = rp.parse_name_status("R100\told.py\tnew.py\nM\ta.py\nA\tb.py")
        assert parsed == [("R", "new.py", "old.py"), ("M", "a.py", None), ("A", "b.py", None)]

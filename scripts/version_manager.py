"""
ERP APK 版本号自动管理器

支持 X.Y 格式版本号（如 1.0, 1.1, 2.0），提供版本号递增、读取、写入功能。
版本信息存储在 frontend-vite/android/version.properties 文件中。

用法:
    python scripts/version_manager.py bump     # 次版本号+1 (1.0 -> 1.1)
    python scripts/version_manager.py major    # 主版本号+1 (1.1 -> 2.0)
    python scripts/version_manager.py current  # 查看当前版本
    python scripts/version_manager.py set 2.1  # 设置指定版本号
"""

import re
import sys
import json
import hashlib
from datetime import datetime
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "frontend-vite" / "android" / "version.properties"
CHANGELOG_FILE = Path(__file__).resolve().parent.parent / "version_changelog.jsonl"


class VersionInfo:
    def __init__(self, major: int, minor: int, code: int):
        self.major = major
        self.minor = minor
        self.code = code

    @property
    def name(self) -> str:
        return f"{self.major}.{self.minor}"

    def to_dict(self) -> dict:
        return {
            "version_name": self.name,
            "version_code": self.code,
            "major": self.major,
            "minor": self.minor,
        }

    def __repr__(self):
        return f"VersionInfo({self.name}, code={self.code})"


def read_version() -> VersionInfo:
    if not VERSION_FILE.exists():
        return VersionInfo(1, 0, 1)

    content = VERSION_FILE.read_text(encoding="utf-8")
    code_match = re.search(r"VERSION_CODE=(\d+)", content)
    name_match = re.search(r"VERSION_NAME=(\d+\.\d+)", content)

    code = int(code_match.group(1)) if code_match else 1
    if name_match:
        parts = name_match.group(1).split(".")
        major, minor = int(parts[0]), int(parts[1])
    else:
        major, minor = 1, 0

    return VersionInfo(major, minor, code)


def write_version(version: VersionInfo) -> None:
    VERSION_FILE.write_text(
        f"VERSION_CODE={version.code}\nVERSION_NAME={version.name}\n",
        encoding="utf-8",
    )


def bump_version(level: str = "minor") -> VersionInfo:
    version = read_version()

    if level == "major":
        version.major += 1
        version.minor = 0
    elif level == "minor":
        version.minor += 1
    else:
        raise ValueError(f"Unknown bump level: {level}. Use major/minor")

    version.code += 1
    write_version(version)
    return version


def set_version(version_str: str) -> VersionInfo:
    if not re.match(r"^\d+\.\d+$", version_str):
        raise ValueError(f"Invalid version format: {version_str}. Expected X.Y (e.g. 1.1)")

    version = read_version()
    parts = version_str.split(".")
    new_major, new_minor = int(parts[0]), int(parts[1])

    if (new_major, new_minor) <= (version.major, version.minor):
        raise ValueError(
            f"New version {version_str} must be greater than current {version.name}"
        )

    version.major = new_major
    version.minor = new_minor
    version.code += 1
    write_version(version)
    return version


def compute_md5(file_path: str) -> str:
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def log_changelog(
    old_version: VersionInfo,
    new_version: VersionInfo,
    trigger: str,
    changelog: str = "",
    sync_status: str = "pending",
    sync_detail: str = "",
) -> None:
    entry = {
        "timestamp": datetime.now().isoformat(),
        "old_version": old_version.name,
        "old_code": old_version.code,
        "new_version": new_version.name,
        "new_code": new_version.code,
        "trigger": trigger,
        "changelog": changelog,
        "sync_status": sync_status,
        "sync_detail": sync_detail,
    }
    with open(CHANGELOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "current":
        v = read_version()
        print(f"当前版本: v{v.name} (code={v.code})")
    elif command in ("major", "minor", "bump"):
        level = "minor" if command == "bump" else command
        old = read_version()
        new = bump_version(level)
        log_changelog(old, new, trigger=f"bump_{level}")
        print(f"版本已更新: v{old.name} -> v{new.name} (code={new.code})")
    elif command == "set":
        if len(sys.argv) < 3:
            print("用法: python version_manager.py set X.Y")
            sys.exit(1)
        old = read_version()
        new = set_version(sys.argv[2])
        log_changelog(old, new, trigger="manual_set")
        print(f"版本已设置: v{old.name} -> v{new.name} (code={new.code})")
    else:
        print(f"未知命令: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

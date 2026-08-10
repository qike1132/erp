"""
ERP APK 打包发布一体化脚本

自动化流程：
  1. 递增版本号（patch/minor/major）
  2. 写入 version.properties
  3. 执行 Gradle Release 构建
  4. 定位生成的 APK 文件
  5. 计算 MD5 校验值
  6. 上传 APK 到后端 API
  7. 可选：推送 FCM 通知
  8. 记录完整日志

用法:
    python scripts/build_and_release.py                    # 默认 patch 递增
    python scripts/build_and_release.py --bump minor       # 次版本号递增
    python scripts/build_and_release.py --bump major       # 主版本号递增
    python scripts/build_and_release.py --changelog "修复登录bug"  # 附带更新日志
    python scripts/build_and_release.py --publish          # 上传后自动发布+推送FCM
    python scripts/build_and_release.py --skip-build       # 跳过构建，仅上传已有APK
    python scripts/build_and_release.py --apk-path /path/to/app.apk  # 指定APK路径
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
ANDROID_DIR = PROJECT_ROOT / "frontend-vite" / "android"
CHANGELOG_FILE = PROJECT_ROOT / "version_changelog.jsonl"

API_BASE_URL = os.getenv("ERP_API_URL", "http://192.168.0.95:5002/api/v1")
FRONTEND_URL = os.getenv("ERP_FRONTEND_URL", "http://192.168.0.95:3000")

sys.path.insert(0, str(SCRIPTS_DIR))
from version_manager import (
    VersionInfo,
    bump_version,
    compute_md5,
    log_changelog,
    read_version,
    write_version,
)


def run_command(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print(f"  [CMD] {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def find_apk() -> Path | None:
    apk_dir = ANDROID_DIR / "app" / "build" / "outputs" / "apk" / "release"
    if not apk_dir.exists():
        return None

    apk_files = list(apk_dir.glob("*.apk"))
    if not apk_files:
        return None

    return max(apk_files, key=lambda f: f.stat().st_mtime)


def upload_apk(apk_path: Path, version: VersionInfo, changelog: str, force_update: bool, retries: int = 3) -> dict:
    import urllib.request
    import urllib.error

    url = f"{API_BASE_URL}/app/upload"
    boundary = "----ERPUploadBoundary" + hashlib.md5(str(time.time()).encode()).hexdigest()

    parts = []
    for field_name, field_value in [
        ("version_name", version.name),
        ("version_code", str(version.code)),
        ("changelog", changelog),
        ("force_update", str(force_update).lower()),
    ]:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'
            f"{field_value}\r\n"
        )

    with open(apk_path, "rb") as f:
        apk_content = f.read()

    apk_filename = f"erp-v{version.name}-code{version.code}.apk"
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{apk_filename}"\r\n'
        f"Content-Type: application/vnd.android.package-archive\r\n\r\n"
    )

    body = "".join(parts).encode("utf-8") + apk_content + f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    token = os.getenv("ERP_AUTH_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
                print(f"  [OK] 上传成功 (attempt {attempt})")
                return response_data
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {e.code}: {error_body}"
            print(f"  [WARN] 上传失败 (attempt {attempt}/{retries}): {last_error}")
            if attempt < retries:
                wait = 2 ** attempt
                print(f"  [RETRY] {wait}秒后重试...")
                time.sleep(wait)
        except Exception as e:
            last_error = str(e)
            print(f"  [WARN] 上传异常 (attempt {attempt}/{retries}): {last_error}")
            if attempt < retries:
                wait = 2 ** attempt
                print(f"  [RETRY] {wait}秒后重试...")
                time.sleep(wait)

    raise RuntimeError(f"APK上传失败（重试{retries}次）: {last_error}")


def publish_version(version_id: int, retries: int = 3) -> dict:
    import urllib.request
    import urllib.error

    url = f"{API_BASE_URL}/app/{version_id}/publish"
    headers = {"Content-Type": "application/json"}
    token = os.getenv("ERP_AUTH_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
                print(f"  [OK] 版本发布成功 (attempt {attempt})")
                return response_data
        except Exception as e:
            last_error = str(e)
            print(f"  [WARN] 版本发布失败 (attempt {attempt}/{retries}): {last_error}")
            if attempt < retries:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"版本发布失败（重试{retries}次）: {last_error}")


def verify_version_sync(version_code: int, timeout: int = 10) -> bool:
    import urllib.request
    import urllib.error

    url = f"{API_BASE_URL}/app/latest?current_version_code=0"
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("latest_version", {}).get("version_code") == version_code:
                    elapsed = time.time() - start
                    print(f"  [OK] 版本同步验证通过 ({elapsed:.1f}s)")
                    return True
        except Exception:
            pass
        time.sleep(1)

    print(f"  [FAIL] 版本同步验证超时 ({timeout}s)")
    return False


def main():
    parser = argparse.ArgumentParser(description="ERP APK 打包发布一体化脚本")
    parser.add_argument("--bump", choices=["minor", "major"], default="minor", help="版本递增级别")
    parser.add_argument("--changelog", default="", help="更新日志")
    parser.add_argument("--force-update", action="store_true", help="标记为强制更新")
    parser.add_argument("--publish", action="store_true", help="上传后自动发布并推送FCM通知")
    parser.add_argument("--skip-build", action="store_true", help="跳过构建步骤")
    parser.add_argument("--apk-path", default="", help="指定APK文件路径")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  ERP APK 自动打包发布  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # === Step 1: 递增版本号 ===
    print("\n[Step 1/7] 递增版本号...")
    old_version = read_version()
    new_version = bump_version(args.bump)
    print(f"  v{old_version.name} (code={old_version.code}) -> v{new_version.name} (code={new_version.code})")

    # === Step 2: 写入 version.properties (已由 bump_version 完成) ===
    print("\n[Step 2/7] 版本信息已写入 version.properties")

    # === Step 3: Gradle Release 构建 ===
    apk_path = None
    if args.apk_path:
        apk_path = Path(args.apk_path)
        if not apk_path.exists():
            print(f"  [ERROR] 指定的APK文件不存在: {apk_path}")
            sys.exit(1)
        print(f"\n[Step 3/7] 使用指定APK: {apk_path}")
    elif args.skip_build:
        apk_path = find_apk()
        if apk_path:
            print(f"\n[Step 3/7] 跳过构建，使用已有APK: {apk_path}")
        else:
            print("\n[Step 3/7] [ERROR] 跳过构建但未找到APK文件")
            sys.exit(1)
    else:
        print("\n[Step 3/7] 执行 Gradle Release 构建...")
        gradlew = "gradlew.bat" if sys.platform == "win32" else "./gradlew"
        try:
            result = run_command(
                [str(ANDROID_DIR / gradlew), "assembleRelease"],
                cwd=str(ANDROID_DIR),
            )
            if result.returncode != 0:
                print(f"  [ERROR] 构建失败:\n{result.stderr}")
                log_changelog(old_version, new_version, "build_failed", args.changelog, "build_error", result.stderr[:500])
                sys.exit(1)
            print("  [OK] 构建成功")
        except subprocess.CalledProcessError as e:
            print(f"  [ERROR] 构建异常: {e}")
            log_changelog(old_version, new_version, "build_failed", args.changelog, "build_error", str(e)[:500])
            sys.exit(1)

        apk_path = find_apk()
        if not apk_path:
            print("  [ERROR] 构建成功但未找到APK文件")
            sys.exit(1)
        print(f"  [OK] APK: {apk_path} ({apk_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # === Step 4: 计算 MD5 ===
    print("\n[Step 4/7] 计算MD5校验值...")
    md5_hash = compute_md5(str(apk_path))
    print(f"  MD5: {md5_hash}")

    # === Step 5: 上传 APK ===
    print("\n[Step 5/7] 上传APK到服务器...")
    try:
        upload_result = upload_apk(apk_path, new_version, args.changelog, args.force_update)
        version_id = upload_result.get("id")
        sync_status = "success"
        sync_detail = json.dumps(upload_result, ensure_ascii=False)
        print(f"  [OK] 上传成功, version_id={version_id}")
    except RuntimeError as e:
        sync_status = "upload_failed"
        sync_detail = str(e)
        version_id = None
        print(f"  [ERROR] {e}")

    # === Step 6: 验证同步 ===
    if sync_status == "success":
        print("\n[Step 6/7] 验证版本同步...")
        verified = verify_version_sync(new_version.code)
        if not verified:
            sync_status = "sync_timeout"
            sync_detail += " | 验证超时"
    else:
        print("\n[Step 6/7] 跳过同步验证（上传失败）")

    # === Step 7: 可选发布版本 ===
    if args.publish and version_id:
        print("\n[Step 7/7] 发布版本并推送FCM通知...")
        try:
            publish_version(version_id)
            print("  [OK] 版本发布成功，升级通知已推送到所有设备")
        except RuntimeError as e:
            print(f"  [ERROR] 版本发布失败: {e}")
    else:
        print(f"\n[Step 7/7] {'跳过发布（版本处于待发布状态）' if not args.publish else '无法发布（上传失败）'}")
        print(f"  [INFO] 可在管理页面手动发布: {FRONTEND_URL}/app-update")

    # === 记录日志 ===
    log_changelog(old_version, new_version, f"build_and_release_{args.bump}", args.changelog, sync_status, sync_detail)

    # === 复制APK到发布目录 ===
    release_dir = PROJECT_ROOT / "static" / "releases"
    release_dir.mkdir(parents=True, exist_ok=True)
    release_apk = release_dir / f"erp-v{new_version.name}.apk"
    shutil.copy2(apk_path, release_apk)
    print(f"\n  [INFO] APK已复制到: {release_apk}")

    # === 汇总 ===
    print("\n" + "=" * 60)
    print(f"  发布完成!")
    print(f"  版本: v{new_version.name} (code={new_version.code})")
    print(f"  MD5:  {md5_hash}")
    print(f"  同步: {sync_status}")
    print(f"  管理页: {FRONTEND_URL}/app-update")
    print("=" * 60)

    if sync_status != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()

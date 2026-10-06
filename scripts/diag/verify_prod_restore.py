"""验证生产恢复：两个地址的构建指纹、erp-web 服务状态。全部字面量命令，无拼接。"""
import re
import subprocess
import sys

DIST_INDEX = r"D:\erp_system\frontend-vite\dist\index.html"
RESTORE_LOG = r"D:\erp_system\logs\restore_web_result.txt"


def read_dist_fingerprint():
    try:
        with open(DIST_INDEX, encoding="utf-8", errors="ignore") as f:
            dist = f.read()
    except OSError as e:
        print("dist/index.html : READ FAIL", e)
        return
    m = re.findall(r"assets/index-[A-Za-z0-9_-]+\.js", dist)
    print("dist/index.html :", m[0] if m else "NONE")


def read_restore_log():
    try:
        with open(RESTORE_LOG, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        print("--- restore_web_result.txt ---")
        print(content.strip()[:800])
    except OSError:
        print("restore_web_result.txt : (not exists, bat not run yet)")


def main():
    read_dist_fingerprint()

    # 127.0.0.1 与 192.168.0.95 都要验：冲突期可能命中不同进程
    r1 = subprocess.run(
        ["curl", "-s", "-m", "6", "--noproxy", "*", "http://127.0.0.1:3000/"],
        capture_output=True, text=True, shell=False, errors="ignore",
    )
    body1 = r1.stdout or ""
    if "@vite/client" in body1:
        print("127.0.0.1:3000  : VITE-DEV!")
    else:
        m1 = re.findall(r"assets/index-[A-Za-z0-9_-]+\.js", body1)
        print("127.0.0.1:3000  :", m1[0] if m1 else f"empty/other (len={len(body1)})")

    r2 = subprocess.run(
        ["curl", "-s", "-m", "6", "--noproxy", "*", "http://192.168.0.95:3000/"],
        capture_output=True, text=True, shell=False, errors="ignore",
    )
    body2 = r2.stdout or ""
    if "@vite/client" in body2:
        print("192.168.0.95    : VITE-DEV!")
    else:
        m2 = re.findall(r"assets/index-[A-Za-z0-9_-]+\.js", body2)
        print("192.168.0.95    :", m2[0] if m2 else f"empty/other (len={len(body2)})")

    r3 = subprocess.run(
        ["sc", "query", "erp-web"],
        capture_output=True, text=True, shell=False, errors="ignore",
    )
    state = [l.strip() for l in (r3.stdout or "").splitlines() if "STATE" in l]
    print("erp-web service :", state or (r3.stderr or "NOT FOUND").strip())

    read_restore_log()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="ignore")
    main()

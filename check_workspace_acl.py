"""检测工作区中所有「因 ACL 损坏而不可访问」的路径。

用途：当 IDE / 编辑器报 `EPERM: operation not permitted, realpath '<path>'`
或出现「部分会话资源加载失败」时，运行本脚本即可列出全部可疑路径。

判据：路径存在（os.lstat 可用）但无法枚举（os.scandir 抛 WinError 5）。
这是「安全描述符被设为受保护且拒绝所有主体」的典型特征——仅凭属性缓存
仍可读到文件属性，但任何打开对象的操作都会被拒。

用法：
    python check_workspace_acl.py [工作区根目录]

退出码：0 = 无故障路径；1 = 存在故障路径。
"""
import os
import sys
import time

SKIP_DIR_NAMES = {".git"}
MAX_DEPTH = 12


def scan(root):
    bad = []
    dir_count = 0
    t0 = time.time()

    def onerror(err):
        p = getattr(err, "filename", None)
        if p:
            bad.append((p, getattr(err, "errno", None), str(err)))

    for cur, dirs, _files in os.walk(root, topdown=True, onerror=onerror):
        dir_count += 1
        if cur[len(root):].count(os.sep) >= MAX_DEPTH:
            dirs[:] = []
            continue

        keep = []
        for d in dirs:
            if d in SKIP_DIR_NAMES:
                continue
            full = os.path.join(cur, d)
            try:
                with os.scandir(full) as it:
                    next(iter(it), None)
            except OSError as e:
                if getattr(e, "winerror", None) == 5 or isinstance(e, PermissionError):
                    bad.append((full, getattr(e, "errno", None), f"scandir: {e}"))
                    continue
            keep.append(d)
        dirs[:] = keep

    return bad, dir_count, time.time() - t0


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(root)

    if not os.path.isdir(root):
        print(f"错误: 不是目录 -> {root}")
        return 2

    print("=" * 74)
    print(f"扫描根目录 : {root}")
    print("=" * 74)

    bad, dir_count, elapsed = scan(root)

    seen = []
    for item in bad:
        if item[0] not in [x[0] for x in seen]:
            seen.append(item)

    print(f"遍历目录数 : {dir_count}")
    print(f"耗时       : {elapsed:.2f}s")
    print()
    print(f"### 不可访问的路径：{len(seen)} 个 ###")
    if not seen:
        print("  无 —— 工作区权限正常，不会触发 EPERM / 资源加载失败")
    for p, eno, msg in seen:
        print(f"  [errno={eno}] {p}")
        print(f"      {msg}")
        print("      修复(需管理员): takeown /f \"%s\" /r /d y /a" % p)
        print("                      icacls \"%s\" /inheritance:e /t" % p)
        print("                      icacls \"%s\" /reset /t" % p)
    print("=" * 74)
    return 1 if seen else 0


if __name__ == "__main__":
    sys.exit(main())

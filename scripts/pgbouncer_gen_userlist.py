"""生成 PgBouncer userlist.txt（Windows 部署用）

用法:
    python scripts/pgbouncer_gen_userlist.py

说明:
    - PgBouncer auth_type=scram-sha-256 时 userlist 用明文密码即可
      （PgBouncer 需支持 scram；若不支持则用 md5，见 --md5）
    - md5 模式格式: "username" "md5" + md5(password + username)
"""
import argparse
import hashlib

DEFAULT_USERS = {
    "erp_app": "ERP应用连接用户（.env 的 DB_USER/DB_PASSWORD）",
    "erp_admin": "管理用户（SHOW STATS 等诊断）",
    "erp_monitor": "监控用户（stats_users）",
}


def md5_hash(password: str, username: str) -> str:
    return "md5" + hashlib.md5((password + username).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="生成 PgBouncer userlist.txt")
    parser.add_argument("--password", help="erp_app 用户密码（.env 的 DB_PASSWORD）")
    parser.add_argument("--admin-pass", help="erp_admin 密码")
    parser.add_argument("--monitor-pass", help="erp_monitor 密码")
    parser.add_argument("--md5", action="store_true", help="使用 md5 哈希（默认明文，适用于 scram-sha-256）")
    parser.add_argument("--output", default="config/pgbouncer/userlist.txt", help="输出路径")
    args = parser.parse_args()

    if not args.password:
        print("请提供 --password（= .env 的 DB_PASSWORD）")
        return

    passwords = {
        "erp_app": args.password,
        "erp_admin": args.admin_pass or args.password,
        "erp_monitor": args.monitor_pass or args.password,
    }

    lines = [";; PgBouncer 用户认证文件（由 scripts/pgbouncer_gen_userlist.py 生成）"]
    for user, pwd in passwords.items():
        if args.md5:
            lines.append(f'"{user}" "{md5_hash(pwd, user)}"')
        else:
            lines.append(f'"{user}" "{pwd}"')

    content = "\n".join(lines) + "\n"
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] 已写入 {args.output}")
    print("请将 userlist.txt 放到 PgBouncer 目录，并设置 auth_file 指向它")
    print("⚠️ 部署后请确保文件权限仅限运行用户可读（含明文密码）")


if __name__ == "__main__":
    main()

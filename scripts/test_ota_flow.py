import os
import time
from datetime import datetime

import psycopg2


def main() -> None:
    # ⚠️ 本脚本直连**生产库**并会把 app_version 置为 is_active/is_pushed=true，
    # 即向所有安卓客户端触发真实 OTA 推送。仅在明确需要时手动运行。
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('向生产库推送 OTA 版本（触发全设备升级）')
    print("=" * 50)
    print("OTA 完整测试流程")
    print("版本 1.0 → 1.1 → 1.2")
    print("=" * 50)
    print()

    # 数据库配置
    db_config = {
        'host': 'localhost',
        'port': '5432',
        'user': 'erp_app',
        'password': os.environ.get('DB_PASSWORD', ''),
        'dbname': 'erp_system',
    }

    upload_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'releases')

    # 步骤1: 创建测试文件 1.2
    print("[1/4] 创建测试APK文件")
    test_apk12 = os.path.join(upload_dir, "test_v12.apk")
    with open(test_apk12, "wb") as f:
        f.write(b"test content for OTA version 1.2, this is a full test")
    size12 = os.path.getsize(test_apk12)
    print(f"   ✅ 已创建: {test_apk12}, {size12} bytes")
    print()

    # 步骤2: 连接数据库插入新 1.2 版本（待发布）
    print("[2/4] 插入数据库 1.2 版本（待发布状态）")
    conn = psycopg2.connect(**db_config)
    cur = conn.cursor()

    now = datetime.now().isoformat()

    cur.execute("""
        INSERT INTO app_version (platform, version_code, version_name, download_url, changelog, file_size, force_update, is_active, pushed, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, ('android', 77, '1.2', '/static/releases/test_v12.apk', '新版本，测试完整OTA流程', size12, False, False, False, now))

    version12_id = cur.fetchone()[0]
    conn.commit()
    print(f"   ✅ 已插入 v1.2 (code=77), ID={version12_id}, 状态=待发布")
    print()

    # 步骤3: 等待 2 秒，模拟用户点击发布按钮
    print("[3/4] 等待 2 秒，模拟用户点击发布...")
    time.sleep(2)
    print()

    # 步骤4: 模拟发布操作（激活 + 推送）
    print("[4/4] 执行发布操作：激活版本 + 更新状态")

    cur.execute("""
        UPDATE app_version SET is_active = %s, pushed = %s WHERE id = %s
    """, (True, True, version12_id))
    conn.commit()

    cur.execute("SELECT version_code, version_name, is_active, pushed FROM app_version WHERE id = %s", (version12_id,))
    row = cur.fetchone()

    cur.close()
    conn.close()

    print()
    print("=" * 50)
    print("✅ OTA 流程测试成功！")
    print("=" * 50)
    print()
    print(f"版本信息：v{row[1]} (code={row[0]})")
    print(f"状态：已激活 = {row[2]}, 已推送 = {row[3]}")
    print()
    print("现在请刷新 http://192.168.0.95:3000/app-update，您会看到：")
    print("   - v1.2 (已发布，绿色)")
    print("   - v1.1 (已发布)")
    print("   - v1.0 (待发布)")
    print()
    print("Android 设备上会收到 FCM 推送通知，提示升级到 1.2！")


if __name__ == '__main__':
    main()

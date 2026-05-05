
import os
import struct

apk_path = r"d:\erp_system\static\releases\erp-v1.3.apk"

if os.path.exists(apk_path):
    size = os.path.getsize(apk_path)
    print(f"APK 文件存在: {apk_path}")
    print(f"文件大小: {size} 字节 ({size / 1024:.2f} KB)")
    
    # 检查文件头
    with open(apk_path, 'rb') as f:
        header = f.read(4)
        print(f"文件头: {header.hex()}")
        
        # ZIP 文件的魔术数字是 50 4B 03 04
        if header == b'PK\x03\x04':
            print("✓ 这是一个有效的 ZIP/APK 文件")
        else:
            print("✗ 这不是一个有效的 ZIP/APK 文件")
            
            # 显示前100个字节看看内容
            f.seek(0)
            content = f.read(100)
            print(f"前100个字节: {content!r}")
else:
    print(f"APK 文件不存在: {apk_path}")

# 检查是否有其他 APK 文件
print("\n检查其他可能的 APK 位置...")
releases_dir = r"d:\erp_system\static\releases"
if os.path.exists(releases_dir):
    files = os.listdir(releases_dir)
    for f in files:
        if f.endswith('.apk'):
            fp = os.path.join(releases_dir, f)
            print(f"  - {f}: {os.path.getsize(fp)} 字节")


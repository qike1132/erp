
import os
from pathlib import Path

def main():
    print("="*60)
    print("  验证 APK 文件")
    print("="*60)
    
    apk_path = Path("static/releases/erp-v1.3.apk")
    
    if not apk_path.exists():
        print(f"\n❌ APK 不存在: {apk_path}")
        return
    
    size = apk_path.stat().st_size
    print(f"\n✓ APK 存在: {apk_path}")
    print(f"  大小: {size} 字节 ({size / 1024 / 1024:.2f} MB)")
    
    # 检查文件头
    with open(apk_path, 'rb') as f:
        header = f.read(4)
        print(f"\n文件头: {header.hex()}")
        
        if header == b'PK\x03\x04':
            print("✓ 这是有效的 ZIP/APK 文件")
            
            # 显示一些信息
            print("\n前 100 字节内容预览:")
            f.seek(0)
            preview = f.read(100)
            print(repr(preview))
        else:
            print("✗ 这不是有效的 ZIP/APK 文件")
            
            # 显示内容
            print("\n文件内容:")
            f.seek(0)
            content = f.read(200)
            print(repr(content))
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()


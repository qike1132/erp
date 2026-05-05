
import os
from pathlib import Path

def main():
    print("="*60)
    print("  检查项目中的 APK")
    print("="*60)
    
    # 检查 static/releases
    releases_dir = Path("static/releases")
    print(f"\n1. 检查 {releases_dir}")
    if releases_dir.exists():
        files = list(releases_dir.iterdir())
        for f in files:
            if f.is_file():
                size = f.stat().st_size
                print(f"   - {f.name}: {size} bytes")
    
    # 检查 android-app/build
    android_build = Path("android-app/app/build/outputs")
    print(f"\n2. 检查 {android_build}")
    if android_build.exists():
        for root, dirs, files in os.walk(android_build):
            for f in files:
                if f.endswith('.apk'):
                    fp = Path(root) / f
                    size = fp.stat().st_size
                    print(f"   - {fp.relative_to('android-app')}: {size} bytes")
    
    # 检查是否有其他目录
    print(f"\n3. 检查项目根目录")
    for f in Path('.').iterdir():
        if f.is_file() and f.name.endswith('.apk'):
            size = f.stat().st_size
            print(f"   - {f.name}: {size} bytes")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    main()


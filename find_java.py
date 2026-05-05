import os
import glob

search_dirs = [
    r"C:\Users\Administrator\AppData\Local\Android\Sdk",
    r"C:\Program Files\Android\Android Studio",
    r"C:\Program Files\Java",
    r"C:\Program Files\Eclipse Adoptium",
    r"C:\Program Files\Microsoft",
]

for base in search_dirs:
    if os.path.exists(base):
        pattern = os.path.join(base, "**", "bin", "java.exe")
        matches = glob.glob(pattern, recursive=True)
        for m in matches:
            jbr = os.path.dirname(os.path.dirname(m))
            print(f"FOUND: {jbr}")
            # Check if it's valid
            if os.path.exists(os.path.join(jbr, "bin", "java.exe")):
                print(f"  VALID: {jbr}")

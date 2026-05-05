import os
import glob

for base in [
    r"C:\Users\Administrator\AppData\Local\Android",
    r"C:\Program Files\Android",
    r"C:\Program Files\Java",
    r"C:\Program Files\Eclipse Adoptium",
]:
    if os.path.exists(base):
        pattern = os.path.join(base, "**", "bin", "java.exe")
        matches = glob.glob(pattern, recursive=True)
        for m in matches:
            jbr = os.path.dirname(os.path.dirname(m))
            print(f"VALID: {jbr}")

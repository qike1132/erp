import os
import subprocess
import sys

# List ALL java.exe files on the system
drives = ['C:\\']
results = []

for drive in drives:
    try:
        # Use dir command to find java.exe in common locations
        locations = [
            os.path.join(drive, 'Users', 'Administrator', 'AppData', 'Local', 'Android'),
            os.path.join(drive, 'Program Files', 'Android'),
            os.path.join(drive, 'Program Files', 'Java'),
            os.path.join(drive, 'Program Files', 'Eclipse Adoptium'),
            os.path.join(drive, 'Program Files', 'Microsoft'),
            os.path.join(drive, 'Program Files', 'JetBrains'),
            os.path.join(drive, 'Program Files (x86)', 'Java'),
        ]
        
        for loc in locations:
            if os.path.exists(loc):
                for root, dirs, files in os.walk(loc):
                    if 'java.exe' in files:
                        java_path = os.path.join(root, 'java.exe')
                        jvm_dir = os.path.dirname(root) if root.endswith('bin') else root
                        results.append(java_path)
                        print(f"Found: {java_path}")
                        # Only go 3 levels deep from bin
                        if len(root.split(os.sep)) - len(loc.split(os.sep)) > 4:
                            dirs.clear()
    except Exception as e:
        print(f"Error scanning {drive}: {e}")

if not results:
    print("No java.exe found in standard locations")
    print("Trying system PATH...")
    try:
        result = subprocess.run(['where', 'java'], capture_output=True, text=True)
        print(f"where java: {result.stdout}")
    except:
        print("where command failed")
else:
    print(f"\nTotal found: {len(results)}")

import os
import glob

workspace = r"c:\Users\VIBUDH\Desktop\projects\job assistant"
files = glob.glob(os.path.join(workspace, "**", "*.py"), recursive=True)

keywords = ["otp", "verification", "gmail", "imap", "email", "code", "mail"]

for file_path in files:
    if "venv" in file_path or ".gemini" in file_path:
        continue
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            for kw in keywords:
                if kw in line.lower():
                    print(f"{os.path.basename(file_path)}:L{idx+1} ({kw}): {line.strip()[:100]}")
                    break
    except Exception as e:
        pass

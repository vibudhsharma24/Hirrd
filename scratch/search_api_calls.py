import os

file_path = r"c:\Users\VIBUDH\Desktop\projects\job assistant\frontend\dashboard.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

lines = content.splitlines()
for idx, line in enumerate(lines):
    if "fetch(" in line or "api/" in line:
        print(f"L{idx+1}: {line.strip()[:120]}")

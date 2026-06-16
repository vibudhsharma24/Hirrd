import os

file_path = r"c:\Users\VIBUDH\Desktop\projects\job assistant\core\database.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

lines = content.splitlines()
for idx, line in enumerate(lines):
    if "posts" in line.lower() or "jobs" in line.lower():
        if "insert" in line.lower() or "select" in line.lower() or "update" in line.lower() or "create" in line.lower():
            print(f"L{idx+1}: {line.strip()[:120]}")

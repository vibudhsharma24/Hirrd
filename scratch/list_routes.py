import os

file_path = r"c:\Users\VIBUDH\Desktop\projects\job assistant\core\app.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

lines = content.splitlines()
for idx, line in enumerate(lines):
    if "@app.route" in line:
        print(f"L{idx+1}: {line.strip()}")

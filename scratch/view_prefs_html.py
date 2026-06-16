import os

file_path = r"c:\Users\VIBUDH\Desktop\projects\job assistant\frontend\dashboard.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Let's find lines around detailed preferences section
lines = content.splitlines()
start_line = None
for idx, line in enumerate(lines):
    if 'id="preferencesSection"' in line:
        start_line = idx
        break

if start_line is not None:
    print(f"Detailed preferences section lines {start_line+1} to {start_line+150}:")
    for idx in range(start_line, min(start_line + 150, len(lines))):
        print(f"{idx+1}: {lines[idx].strip()}")

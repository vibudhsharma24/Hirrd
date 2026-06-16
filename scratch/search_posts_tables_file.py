import os

file_path = r"c:\Users\VIBUDH\Desktop\projects\job assistant\core\database.py"
out_path = r"c:\Users\VIBUDH\Desktop\projects\job assistant\scratch\db_search_output.txt"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

lines = content.splitlines()
matches = []
for idx, line in enumerate(lines):
    if "posts" in line.lower() or "jobs" in line.lower():
        if "insert" in line.lower() or "select" in line.lower() or "update" in line.lower() or "create" in line.lower():
            matches.append(f"L{idx+1}: {line.strip()}")

with open(out_path, "w", encoding="utf-8") as out:
    out.write("\n".join(matches))
print(f"Saved {len(matches)} matches to {out_path}")

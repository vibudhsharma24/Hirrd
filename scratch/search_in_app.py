with open("core/app.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "match" in line.lower() or "score" in line.lower() or "icp" in line.lower():
        print(f"Line {i+1}: {line.strip()}")

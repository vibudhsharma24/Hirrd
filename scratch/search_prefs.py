import os

files = [
    r"c:\Users\VIBUDH\Desktop\projects\job assistant\core\app.py",
    r"c:\Users\VIBUDH\Desktop\projects\job assistant\frontend\dashboard.html",
    r"c:\Users\VIBUDH\Desktop\projects\job assistant\job_seeker_agent\runner.py"
]

for file_path in files:
    print(f"=== {os.path.basename(file_path)} ===")
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # print lines containing job_preferences
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if "job_preferences" in line or "preferences" in line.lower():
            print(f"Line {idx+1}: {line.strip()[:120]}")

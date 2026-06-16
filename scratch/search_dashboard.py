import os

file_path = r"c:\Users\VIBUDH\Desktop\projects\job assistant\frontend\dashboard.html"

search_terms = ["run agent", "run-agent", "apply", "trigger", "fetch", "button", "status"]

with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

for term in search_terms:
    print(f"=== Search for '{term}' ===")
    count = 0
    for idx, line in enumerate(lines):
        if term.lower() in line.lower():
            print(f"Line {idx+1}: {line.strip()[:100]}")
            count += 1
            if count >= 20:
                print("... truncated ...")
                break

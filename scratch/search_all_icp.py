import os

directories = [".", "../career-ops-main/career-ops-main"]
search_word = "icp"

for root_path in directories:
    root_path = os.path.abspath(root_path)
    print(f"Searching in: {root_path}")
    for dirpath, _, filenames in os.walk(root_path):
        if "node_modules" in dirpath or ".git" in dirpath or ".gemini" in dirpath:
            continue
        for filename in filenames:
            if filename.endswith((".js", ".mjs", ".ts", ".py", ".md", ".yml", ".yaml")):
                filepath = os.path.join(dirpath, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        for line_num, line in enumerate(f, 1):
                            if search_word in line.lower():
                                rel_path = os.path.relpath(filepath, root_path)
                                print(f"  {rel_path}:{line_num}: {line.strip()}")
                except Exception:
                    pass

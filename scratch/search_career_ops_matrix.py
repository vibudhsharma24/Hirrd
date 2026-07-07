import os

root_dir = os.path.abspath("../career-ops-main/career-ops-main")
search_words = ["matrix", "dimension", "weight", "relevance"]

for dirpath, _, filenames in os.walk(root_dir):
    if any(ignored in dirpath.lower() for ignored in ["node_modules", ".git", ".gemini", "venv", "pycache"]):
        continue
    for filename in filenames:
        if filename.endswith((".js", ".mjs", ".ts", ".py", ".md", ".yml", ".yaml")):
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        matched = [w for w in search_words if w in line.lower()]
                        if matched:
                            rel_path = os.path.relpath(filepath, root_dir)
                            print(f"  {rel_path}:{line_num} ({matched}): {line.strip()}")
            except Exception:
                pass

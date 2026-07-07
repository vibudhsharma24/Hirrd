import os

root_dir = os.path.abspath("../career-ops-main/career-ops-main")
search_words = ["icp", "relevance", "score", "match"]

for dirpath, _, filenames in os.walk(root_dir):
    if "node_modules" in dirpath or ".git" in dirpath:
        continue
    for filename in filenames:
        if filename.endswith((".js", ".mjs", ".ts", ".py", ".md", ".yml", ".yaml")):
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                matches = [w for w in search_words if w in content.lower()]
                if matches:
                    rel_path = os.path.relpath(filepath, root_dir)
                    print(f"{rel_path}: matches {matches}")
            except Exception:
                pass

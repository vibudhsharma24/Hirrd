import sqlite3
import json

conn = sqlite3.connect("users.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT * FROM master_cv")
rows = cursor.fetchall()
for r in rows:
    print(f"\n================ USER ID: {r['user_id']} ================")
    data = json.loads(r["cv_data"])
    print(json.dumps(data, indent=2))
conn.close()

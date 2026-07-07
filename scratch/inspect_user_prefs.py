import sqlite3
import json

conn = sqlite3.connect("users.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT id, name, job_preferences, naukri_preferences FROM users WHERE id IN (14, 9999)")
rows = cursor.fetchall()
for r in rows:
    print(f"\n================ USER ID: {r['id']} ({r['name']}) ================")
    print("job_preferences:", r["job_preferences"])
    print("naukri_preferences:", r["naukri_preferences"])
conn.close()

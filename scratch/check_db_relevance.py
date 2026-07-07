import sqlite3

conn = sqlite3.connect("jobs.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT title, company, location, experience, relevance_percent, url FROM naukri_jobs ORDER BY relevance_percent DESC LIMIT 10")
rows = cursor.fetchall()
print("=== TOP 10 RANKED NAUKRI JOBS IN DATABASE ===")
for r in rows:
    print(f"Score: {r['relevance_percent']}% | {r['title']} | {r['company']} | {r['location']} | {r['experience']}")
conn.close()

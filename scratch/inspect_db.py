import sqlite3

for db_name in ["users.db", "jobs.db"]:
    print(f"=== {db_name} ===")
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    for table in tables:
        t_name = table[0]
        cursor.execute(f"PRAGMA table_info({t_name})")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"  Table: {t_name}")
        print(f"    Columns: {columns}")
    conn.close()

import sqlite3

def main():
    conn = sqlite3.connect('users.db')
    cur = conn.execute("UPDATE users SET status='approved' WHERE email='testuser_antigravity@test.com'")
    conn.commit()
    print('Approved test user in users.db. Rows updated:', cur.rowcount)
    
    # Also let's make sure if a verification request exists we set it to APPROVED
    cur2 = conn.execute("UPDATE verification_requests SET status='APPROVED' WHERE user_id = (SELECT id FROM users WHERE email='testuser_antigravity@test.com')")
    conn.commit()
    print('Approved verification request. Rows updated:', cur2.rowcount)
    conn.close()

if __name__ == '__main__':
    main()

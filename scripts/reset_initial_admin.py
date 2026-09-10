import sqlite3
from ariadne.auth.security import hash_password

def main():
    conn = sqlite3.connect('data/ariadne.db')
    cur = conn.cursor()

    # Clear active tokens and session state
    cur.execute('DELETE FROM refresh_tokens')
    cur.execute('DELETE FROM events')
    cur.execute('DELETE FROM alerts')
    cur.execute('DELETE FROM trajectory_records')
    cur.execute('DELETE FROM runs')

    # Ensure clean admin user
    cur.execute("DELETE FROM users WHERE email != 'admin@example.com'")
    cur.execute(
        "UPDATE users SET last_login_at = NULL, password_hash = ? WHERE email = 'admin@example.com'",
        (hash_password('password123'),)
    )
    conn.commit()

    print("Initial Admin & MCP Connection state configured successfully:")
    print("Users:", cur.execute("SELECT email, role, last_login_at FROM users").fetchall())
    print("Runs count:", cur.execute("SELECT count(*) FROM runs").fetchone()[0])
    print("Refresh tokens count:", cur.execute("SELECT count(*) FROM refresh_tokens").fetchone()[0])
    conn.close()

if __name__ == '__main__':
    main()
